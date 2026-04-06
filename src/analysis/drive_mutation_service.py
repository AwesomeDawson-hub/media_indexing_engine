"""Drive source-mutation service (P7-004).

After AI analysis completes for a Drive-backed media item, this service
attempts to apply the computed target filename to the source Drive file.

Contract (per P7-004 plan):
  - fully_applied  : analysis done, Drive rename succeeded, history written
  - pending_writeback : Drive rename queued/retrying; no user action needed yet
  - blocked_writeback : Drive auth is read-only, permissions insufficient, or
                        terminal error; user action required

The target filename is derived from the AI-generated title:
  slugify(title) + original file extension (lower-cased)

Drive rename is a lightweight provider-metadata update (PATCH /drive/v3/files/{id}).
Embedded metadata write-back (EXIF/IPTC/XMP byte mutation) is recorded as
pending and is left for a future background write-back job (out of P7-004 scope).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.auth.google_drive_oauth import scope_has_write, DRIVE_SCOPE_READWRITE
from src.connectors.google_drive_tokens import DriveTokenManager, DriveTokenError
from src.connectors.secrets import decrypt_credentials
from src.config import settings
from src.models import MediaItem, MediaMetadata, SourceConnector, SourceMutationHistory

logger = logging.getLogger(__name__)

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

# Maximum filename length for Drive (bytes, not chars; we apply a conservative char limit)
_MAX_FILENAME_CHARS = 200

# Error codes surfaced on MediaItem.last_mutation_error_code
_ERR_NO_WRITE_SCOPE = "no_write_scope"
_ERR_DRIVE_AUTH_EXPIRED = "drive_auth_expired"
_ERR_DRIVE_PERMISSION_DENIED = "drive_permission_denied"
_ERR_DRIVE_NOT_FOUND = "drive_file_not_found"
_ERR_DRIVE_API_ERROR = "drive_api_error"
_ERR_NO_CONNECTOR = "no_connector"
_ERR_NOT_DRIVE_ITEM = "not_drive_item"


def _slugify(text: str) -> str:
    """Convert an arbitrary title into a filesystem-safe slug.

    Replaces whitespace and non-alphanumeric characters with underscores,
    collapses repeated underscores, and strips leading/trailing underscores.
    """
    # Lowercase, replace sequences of non-alphanumeric chars with underscore
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower())
    slug = slug.strip("_")
    return slug or "untitled"


def _target_filename(title: str, original_filename: str) -> str:
    """Compute the target Drive filename from the AI title and original extension."""
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()

    slug = _slugify(title)[:_MAX_FILENAME_CHARS]
    return f"{slug}{ext}"


async def _record_mutation_attempt(
    db: AsyncSession,
    *,
    media_item: MediaItem,
    operation_type: str,
    prior_filename: str | None,
    new_filename: str | None,
    source_locator_snapshot: dict | None,
    succeeded: bool,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata_payload_hash: str | None = None,
) -> None:
    """Write one row to source_mutation_history."""
    now = datetime.now(timezone.utc)
    history = SourceMutationHistory(
        media_item_id=media_item.id,
        user_id=media_item.user_id,
        operation_type=operation_type,
        prior_filename=prior_filename,
        new_filename=new_filename,
        source_locator_snapshot=json.dumps(source_locator_snapshot) if source_locator_snapshot else None,
        metadata_payload_hash=metadata_payload_hash,
        succeeded=succeeded,
        error_code=error_code,
        error_message=error_message[:500] if error_message else None,
        attempted_at=now,
        completed_at=now if succeeded else None,
    )
    db.add(history)


async def attempt_drive_rename_after_analysis(
    db: AsyncSession,
    media_item: MediaItem,
) -> None:
    """Attempt to rename the Drive source file immediately after analysis.

    Sets ``media_item.mutation_state`` to one of:
      - ``fully_applied``       — rename succeeded
      - ``pending_writeback``   — transient Drive error; will retry
      - ``blocked_writeback``   — no write scope, auth expired, or terminal error

    Also records the attempt in ``source_mutation_history`` and updates the
    current-state fields on ``media_item``.  Commits nothing — the caller is
    responsible for committing the session.

    If the item has no connector, is not a Drive item, or has no analysis
    metadata, returns immediately without changing ``mutation_state``.
    """
    # --- Guard: item must have a source ---
    if not media_item.source_id:
        return

    # --- Load connector ---
    conn_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == media_item.source_id,
            SourceConnector.user_id == media_item.user_id,
        )
    )
    connector = conn_result.scalar_one_or_none()
    if connector is None or connector.connector_type != "google_drive":
        return

    # --- Load analysis metadata (need title for target filename) ---
    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_item.id)
    )
    metadata = meta_result.scalar_one_or_none()
    if metadata is None:
        return

    now = datetime.now(timezone.utc)
    media_item.last_mutation_attempted_at = now

    # --- Set first_seen_source_filename once ---
    if media_item.first_seen_source_filename is None:
        media_item.first_seen_source_filename = media_item.original_filename

    current_filename = media_item.first_seen_source_filename
    target = _target_filename(metadata.title, media_item.original_filename)

    # --- Check writable scope ---
    if not scope_has_write(connector.granted_scopes):
        logger.info(
            "Drive item %s blocked_writeback: connector has no write scope (source %s)",
            media_item.id, media_item.source_id,
        )
        media_item.mutation_state = "blocked_writeback"
        media_item.last_mutation_error_code = _ERR_NO_WRITE_SCOPE
        media_item.last_mutation_error_message = (
            "Drive connector was authorized with read-only scope. "
            "Reconnect via 'Upgrade Drive permissions' to enable rename and write-back."
        )
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="rename",
            prior_filename=current_filename,
            new_filename=target,
            source_locator_snapshot={"drive_file_id": media_item.content_hash},
            succeeded=False,
            error_code=_ERR_NO_WRITE_SCOPE,
            error_message=media_item.last_mutation_error_message,
        )
        return

    # --- Attempt Drive rename via API ---
    try:
        credentials = decrypt_credentials(connector.credentials_encrypted)
    except Exception as exc:
        logger.warning("Cannot decrypt Drive credentials for item %s: %s", media_item.id, exc)
        media_item.mutation_state = "blocked_writeback"
        media_item.last_mutation_error_code = _ERR_DRIVE_AUTH_EXPIRED
        media_item.last_mutation_error_message = "Drive credentials could not be decrypted."
        return

    if not credentials.get("refresh_token"):
        media_item.mutation_state = "blocked_writeback"
        media_item.last_mutation_error_code = _ERR_DRIVE_AUTH_EXPIRED
        media_item.last_mutation_error_message = "Drive connector is disconnected (no refresh token)."
        return

    token_manager = DriveTokenManager(
        connector_row=connector,
        credentials=credentials,
        client_id=settings.google_drive.client_id,
        client_secret=settings.google_drive.client_secret,
        redirect_uri=settings.google_drive.redirect_uri,
    )

    try:
        access_token = await token_manager.get_access_token(db)
    except DriveTokenError as exc:
        logger.warning("Drive token refresh failed for item %s: %s", media_item.id, exc)
        media_item.mutation_state = "blocked_writeback"
        media_item.last_mutation_error_code = _ERR_DRIVE_AUTH_EXPIRED
        media_item.last_mutation_error_message = str(exc)[:500]
        await _record_mutation_attempt(
            db, media_item=media_item, operation_type="rename",
            prior_filename=current_filename, new_filename=target,
            source_locator_snapshot=None,
            succeeded=False, error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message=media_item.last_mutation_error_message,
        )
        return

    # The Drive file ID is stored as the external_object_key in SourceObject.
    # We use media_item.original_filename as the current name and look up the
    # drive file ID from the SourceObject table.
    from src.models import SourceObject
    so_result = await db.execute(
        select(SourceObject).where(
            SourceObject.source_id == media_item.source_id,
            SourceObject.last_imported_media_item_id == media_item.id,
        )
    )
    source_object = so_result.scalar_one_or_none()
    drive_file_id = source_object.external_object_key if source_object else None

    if not drive_file_id:
        # Item ingested before source-object tracking or via manual upload —
        # cannot locate Drive file; mark blocked.
        media_item.mutation_state = "blocked_writeback"
        media_item.last_mutation_error_code = "no_drive_file_id"
        media_item.last_mutation_error_message = (
            "Cannot locate Drive file ID for this item. "
            "Re-sync the Drive source to re-establish the link."
        )
        return

    locator_snapshot = {
        "drive_file_id": drive_file_id,
        "drive_version": source_object.external_version if source_object else None,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{DRIVE_FILES_URL}/{drive_file_id}",
                params={"fields": "id,name"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                content=json.dumps({"name": target}),
            )

        if resp.status_code == 200:
            renamed_to = resp.json().get("name", target)
            media_item.prior_source_filename = current_filename
            media_item.source_filename_applied_at = now
            media_item.last_mutation_error_code = None
            media_item.last_mutation_error_message = None
            media_item.mutation_state = "fully_applied"
            await _record_mutation_attempt(
                db, media_item=media_item, operation_type="rename",
                prior_filename=current_filename, new_filename=renamed_to,
                source_locator_snapshot=locator_snapshot,
                succeeded=True,
            )
            logger.info(
                "Drive rename succeeded for item %s: '%s' -> '%s'",
                media_item.id, current_filename, renamed_to,
            )

        elif resp.status_code in (401, 403):
            err_code = _ERR_DRIVE_PERMISSION_DENIED if resp.status_code == 403 else _ERR_DRIVE_AUTH_EXPIRED
            err_msg = f"Drive API returned HTTP {resp.status_code}: {resp.text[:200]}"
            media_item.mutation_state = "blocked_writeback"
            media_item.last_mutation_error_code = err_code
            media_item.last_mutation_error_message = err_msg
            await _record_mutation_attempt(
                db, media_item=media_item, operation_type="rename",
                prior_filename=current_filename, new_filename=target,
                source_locator_snapshot=locator_snapshot,
                succeeded=False, error_code=err_code, error_message=err_msg,
            )

        elif resp.status_code == 404:
            err_msg = "Drive file no longer exists at the expected location."
            media_item.mutation_state = "blocked_writeback"
            media_item.last_mutation_error_code = _ERR_DRIVE_NOT_FOUND
            media_item.last_mutation_error_message = err_msg
            await _record_mutation_attempt(
                db, media_item=media_item, operation_type="rename",
                prior_filename=current_filename, new_filename=target,
                source_locator_snapshot=locator_snapshot,
                succeeded=False, error_code=_ERR_DRIVE_NOT_FOUND, error_message=err_msg,
            )

        else:
            # Transient server-side error → pending_writeback for retry
            err_msg = f"Drive API returned HTTP {resp.status_code}: {resp.text[:200]}"
            media_item.mutation_state = "pending_writeback"
            media_item.last_mutation_error_code = _ERR_DRIVE_API_ERROR
            media_item.last_mutation_error_message = err_msg
            await _record_mutation_attempt(
                db, media_item=media_item, operation_type="rename",
                prior_filename=current_filename, new_filename=target,
                source_locator_snapshot=locator_snapshot,
                succeeded=False, error_code=_ERR_DRIVE_API_ERROR, error_message=err_msg,
            )
            logger.warning(
                "Drive rename transient error for item %s (pending_writeback): %s",
                media_item.id, err_msg,
            )

    except Exception as exc:
        err_msg = str(exc)[:500]
        media_item.mutation_state = "pending_writeback"
        media_item.last_mutation_error_code = _ERR_DRIVE_API_ERROR
        media_item.last_mutation_error_message = err_msg
        await _record_mutation_attempt(
            db, media_item=media_item, operation_type="rename",
            prior_filename=current_filename, new_filename=target,
            source_locator_snapshot=locator_snapshot,
            succeeded=False, error_code=_ERR_DRIVE_API_ERROR, error_message=err_msg,
        )
        logger.warning("Drive rename failed for item %s: %s", media_item.id, exc)
