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

import json
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.source_capability_service import ensure_drive_capability_snapshot, mark_snapshot_error
from src.analysis.writeback_operation_service import (
    OP_STATE_APPLIED,
    OP_STATE_BLOCKED,
    OP_STATE_FAILED,
    apply_writeback_operation_to_mirror,
    ensure_writeback_operation,
    ensure_origin_asset_ref,
)
from src.connectors.google_drive_tokens import DriveTokenManager, DriveTokenError
from src.connectors.secrets import decrypt_credentials
from src.config import settings
from src.models import MediaItem, MediaMetadata, SourceConnector, SourceMutationHistory, SourceObject

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
_ERR_CAPABILITY_STALE = "capability_stale"
_ERR_NO_DRIVE_FILE_ID = "no_drive_file_id"


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

    origin_asset_ref = await ensure_origin_asset_ref(db, media_item)
    if origin_asset_ref is None:
        return

    now = datetime.now(timezone.utc)

    # --- Set first_seen_source_filename once ---
    if media_item.first_seen_source_filename is None:
        media_item.first_seen_source_filename = media_item.original_filename

    current_filename = media_item.first_seen_source_filename
    target = _target_filename(metadata.title, media_item.original_filename)
    snapshot = await ensure_drive_capability_snapshot(db, connector)
    operation = await ensure_writeback_operation(
        db,
        media_item=media_item,
        origin_asset_ref=origin_asset_ref,
        operation_type="rename",
        provider_type=origin_asset_ref.provider_type,
        source_connector_id=connector.id,
        requested_filename=target,
    )
    operation.attempt_count += 1
    operation.last_attempted_at = now

    # --- Check writable scope ---
    if snapshot.verification_state != "current":
        operation.state = OP_STATE_BLOCKED
        operation.last_error_code = snapshot.last_error_code or _ERR_CAPABILITY_STALE
        operation.last_error_message = snapshot.last_error_message or "Source capability snapshot is not current."
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="rename",
            prior_filename=current_filename,
            new_filename=target,
            source_locator_snapshot={"origin_asset_ref_id": origin_asset_ref.id},
            succeeded=False,
            error_code=operation.last_error_code,
            error_message=operation.last_error_message,
        )
        return

    if not snapshot.can_write:
        logger.info(
            "Drive item %s blocked_writeback: connector has no write scope (source %s)",
            media_item.id, media_item.source_id,
        )
        operation.state = OP_STATE_BLOCKED
        operation.last_error_code = _ERR_NO_WRITE_SCOPE
        operation.last_error_message = (
            "Drive connector was authorized with read-only scope. "
            "Reconnect via 'Upgrade Drive permissions' to enable rename and write-back."
        )
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="rename",
            prior_filename=current_filename,
            new_filename=target,
            source_locator_snapshot={"origin_asset_ref_id": origin_asset_ref.id},
            succeeded=False,
            error_code=_ERR_NO_WRITE_SCOPE,
            error_message=operation.last_error_message,
        )
        return

    # --- Attempt Drive rename via API ---
    try:
        credentials = decrypt_credentials(connector.credentials_encrypted)
    except Exception as exc:
        logger.warning("Cannot decrypt Drive credentials for item %s: %s", media_item.id, exc)
        mark_snapshot_error(
            snapshot,
            error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message="Drive credentials could not be decrypted.",
        )
        operation.state = OP_STATE_BLOCKED
        operation.last_error_code = _ERR_DRIVE_AUTH_EXPIRED
        operation.last_error_message = "Drive credentials could not be decrypted."
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="rename",
            prior_filename=current_filename,
            new_filename=target,
            source_locator_snapshot={"origin_asset_ref_id": origin_asset_ref.id},
            succeeded=False,
            error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message=operation.last_error_message,
        )
        return

    if not credentials.get("refresh_token"):
        mark_snapshot_error(
            snapshot,
            error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message="Drive connector is disconnected (no refresh token).",
        )
        operation.state = OP_STATE_BLOCKED
        operation.last_error_code = _ERR_DRIVE_AUTH_EXPIRED
        operation.last_error_message = "Drive connector is disconnected (no refresh token)."
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="rename",
            prior_filename=current_filename,
            new_filename=target,
            source_locator_snapshot={"origin_asset_ref_id": origin_asset_ref.id},
            succeeded=False,
            error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message=operation.last_error_message,
        )
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
        mark_snapshot_error(
            snapshot,
            error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message=str(exc),
        )
        operation.state = OP_STATE_BLOCKED
        operation.last_error_code = _ERR_DRIVE_AUTH_EXPIRED
        operation.last_error_message = str(exc)[:500]
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db, media_item=media_item, operation_type="rename",
            prior_filename=current_filename, new_filename=target,
            source_locator_snapshot=None,
            succeeded=False, error_code=_ERR_DRIVE_AUTH_EXPIRED,
            error_message=operation.last_error_message,
        )
        return

    source_object: SourceObject | None = None
    drive_file_id = origin_asset_ref.provider_object_id
    if origin_asset_ref.source_object_id:
        so_result = await db.execute(
            select(SourceObject).where(SourceObject.id == origin_asset_ref.source_object_id)
        )
        source_object = so_result.scalar_one_or_none()
        if not drive_file_id and source_object is not None:
            drive_file_id = source_object.external_object_key

    if not drive_file_id:
        # Item ingested before source-object tracking or via manual upload —
        # cannot locate Drive file; mark blocked.
        operation.state = OP_STATE_BLOCKED
        operation.last_error_code = _ERR_NO_DRIVE_FILE_ID
        operation.last_error_message = (
            "Cannot locate Drive file ID for this item. "
            "Re-sync the Drive source to re-establish the link."
        )
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="rename",
            prior_filename=current_filename,
            new_filename=target,
            source_locator_snapshot={"origin_asset_ref_id": origin_asset_ref.id},
            succeeded=False,
            error_code=_ERR_NO_DRIVE_FILE_ID,
            error_message=operation.last_error_message,
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
            operation.state = OP_STATE_APPLIED
            operation.applied_at = now
            operation.last_error_code = None
            operation.last_error_message = None
            apply_writeback_operation_to_mirror(media_item, operation)
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
            if err_code == _ERR_DRIVE_AUTH_EXPIRED:
                mark_snapshot_error(snapshot, error_code=err_code, error_message=err_msg)
            operation.state = OP_STATE_BLOCKED
            operation.last_error_code = err_code
            operation.last_error_message = err_msg
            apply_writeback_operation_to_mirror(media_item, operation)
            await _record_mutation_attempt(
                db, media_item=media_item, operation_type="rename",
                prior_filename=current_filename, new_filename=target,
                source_locator_snapshot=locator_snapshot,
                succeeded=False, error_code=err_code, error_message=err_msg,
            )

        elif resp.status_code == 404:
            err_msg = "Drive file no longer exists at the expected location."
            operation.state = OP_STATE_BLOCKED
            operation.last_error_code = _ERR_DRIVE_NOT_FOUND
            operation.last_error_message = err_msg
            apply_writeback_operation_to_mirror(media_item, operation)
            await _record_mutation_attempt(
                db, media_item=media_item, operation_type="rename",
                prior_filename=current_filename, new_filename=target,
                source_locator_snapshot=locator_snapshot,
                succeeded=False, error_code=_ERR_DRIVE_NOT_FOUND, error_message=err_msg,
            )

        else:
            # Transient server-side error → pending_writeback for retry
            err_msg = f"Drive API returned HTTP {resp.status_code}: {resp.text[:200]}"
            operation.state = OP_STATE_FAILED
            operation.last_error_code = _ERR_DRIVE_API_ERROR
            operation.last_error_message = err_msg
            apply_writeback_operation_to_mirror(media_item, operation)
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
        operation.state = OP_STATE_FAILED
        operation.last_error_code = _ERR_DRIVE_API_ERROR
        operation.last_error_message = err_msg
        apply_writeback_operation_to_mirror(media_item, operation)
        await _record_mutation_attempt(
            db, media_item=media_item, operation_type="rename",
            prior_filename=current_filename, new_filename=target,
            source_locator_snapshot=locator_snapshot,
            succeeded=False, error_code=_ERR_DRIVE_API_ERROR, error_message=err_msg,
        )
        logger.warning("Drive rename failed for item %s: %s", media_item.id, exc)


# ---------------------------------------------------------------------------
# Metadata embed write-back — uploads enriched bytes back to Drive
# ---------------------------------------------------------------------------

async def attempt_drive_metadata_embed(
    db: AsyncSession,
    media_item: MediaItem,
    file_bytes: bytes,
) -> None:
    """Embed AI metadata into the file bytes and upload the result back to Drive.

    Called immediately after analysis + rename, while the original bytes are
    still available in memory.  Silently skips if:
      - Item has no Drive connector
      - Connector lacks write scope
      - MIME type does not support embedding (BMP, GIF, etc.)

    Does NOT set mutation_state — that belongs to the rename operation.
    Records a row in source_mutation_history for auditing.
    """
    if not media_item.source_id:
        return

    conn_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == media_item.source_id,
            SourceConnector.user_id == media_item.user_id,
        )
    )
    connector = conn_result.scalar_one_or_none()
    if connector is None or connector.connector_type != "google_drive":
        return

    # Load analysis metadata
    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_item.id)
    )
    metadata = meta_result.scalar_one_or_none()
    if metadata is None:
        return

    # Check write scope
    snapshot = await ensure_drive_capability_snapshot(db, connector)
    if not snapshot.can_write:
        logger.debug(
            "Drive embed skipped for item %s: connector has no write scope",
            media_item.id,
        )
        return

    # Get Drive file ID
    origin_asset_ref = await ensure_origin_asset_ref(db, media_item)
    if origin_asset_ref is None:
        return
    drive_file_id = origin_asset_ref.provider_object_id
    if not drive_file_id and origin_asset_ref.source_object_id:
        so_result = await db.execute(
            select(SourceObject).where(SourceObject.id == origin_asset_ref.source_object_id)
        )
        so = so_result.scalar_one_or_none()
        if so is not None:
            drive_file_id = so.external_object_key
    if not drive_file_id:
        logger.debug("Drive embed skipped for item %s: no drive_file_id", media_item.id)
        return

    # Embed metadata into bytes
    import json
    from src.enrichment.embedder import MetadataEmbedder
    from src.analysis.schemas import MediaMetadataResult

    embedder = MetadataEmbedder()
    metadata_result = MediaMetadataResult(
        title=metadata.title,
        description=metadata.description,
        tags=json.loads(metadata.tags) if metadata.tags else [],
        objects=json.loads(metadata.objects) if metadata.objects else [],
        scenes=json.loads(metadata.scenes) if metadata.scenes else [],
        context=metadata.context or "",
        mood=metadata.mood or "",
        people=json.loads(metadata.people) if metadata.people else [],
        people_count=metadata.people_count or 0,
        orientation=metadata.orientation or "landscape",
        colors=json.loads(metadata.colors) if metadata.colors else [],
        location_hint=metadata.location_hint,
        quality_notes=metadata.quality_notes,
    )
    result = embedder.embed(
        file_bytes,
        media_item.mime_type,
        metadata_result,
        media_item.original_filename,
    )
    if not result.embedded:
        logger.debug(
            "Drive embed skipped for item %s: MIME type %s does not support embedding",
            media_item.id,
            media_item.mime_type,
        )
        return

    # Get access token
    try:
        credentials = decrypt_credentials(connector.credentials_encrypted)
    except Exception as exc:
        logger.warning("Drive embed: failed to decrypt credentials for item %s: %s", media_item.id, exc)
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
        logger.warning("Drive embed: token refresh failed for item %s: %s", media_item.id, exc)
        return

    # PATCH the file content back to Drive (media-only upload)
    upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{drive_file_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                upload_url,
                params={"uploadType": "media", "fields": "id,md5Checksum"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": result.output_mime_type,
                },
                content=result.enriched_bytes,
                timeout=60.0,
            )

        if resp.status_code == 200:
            logger.info(
                "Drive metadata embed succeeded for item %s (file_id=%s)",
                media_item.id, drive_file_id,
            )
            # Update the SourceObject's stored version to the post-embed md5 so
            # that the next sync sees a matching version and does not reimport.
            embed_response = resp.json()
            new_embed_md5 = embed_response.get("md5Checksum")
            if new_embed_md5:
                so_result = await db.execute(
                    select(SourceObject).where(
                        SourceObject.last_imported_media_item_id == media_item.id
                    )
                )
                embed_so = so_result.scalar_one_or_none()
                if embed_so is not None:
                    embed_so.external_version = new_embed_md5
                    embed_so.updated_at = datetime.now(timezone.utc)
                    logger.info(
                        "Drive metadata embed: updated SO %s external_version to post-embed md5 %s",
                        embed_so.id, new_embed_md5,
                    )
            await _record_mutation_attempt(
                db,
                media_item=media_item,
                operation_type="metadata_embed",
                prior_filename=media_item.original_filename,
                new_filename=None,
                source_locator_snapshot={"drive_file_id": drive_file_id},
                succeeded=True,
            )
        else:
            logger.warning(
                "Drive metadata embed returned HTTP %s for item %s: %s",
                resp.status_code, media_item.id, resp.text[:200],
            )
            await _record_mutation_attempt(
                db,
                media_item=media_item,
                operation_type="metadata_embed",
                prior_filename=media_item.original_filename,
                new_filename=None,
                source_locator_snapshot={"drive_file_id": drive_file_id},
                succeeded=False,
                error_code=_ERR_DRIVE_API_ERROR,
                error_message=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
    except Exception as exc:
        logger.warning("Drive metadata embed failed for item %s: %s", media_item.id, exc)
        await _record_mutation_attempt(
            db,
            media_item=media_item,
            operation_type="metadata_embed",
            prior_filename=media_item.original_filename,
            new_filename=None,
            source_locator_snapshot={"drive_file_id": drive_file_id},
            succeeded=False,
            error_code=_ERR_DRIVE_API_ERROR,
            error_message=str(exc)[:500],
        )


async def download_and_embed_drive_metadata(
    media_item_id: str,
    user_id: str,
) -> None:
    """Re-download the Drive file and embed the current DB metadata into it.

    Used by manual-edit and re-analyze flows where the original bytes are no
    longer in memory.  Creates its own DB session so it can be called as a
    FastAPI BackgroundTask.

    Silently no-ops if the item has no Drive connector or no write scope.
    """
    from src.database import async_session
    from src.connectors.factory import build_connector
    from src.connectors.secrets import decrypt_credentials

    async with async_session() as db:
        item_result = await db.execute(
            select(MediaItem).where(MediaItem.id == media_item_id, MediaItem.user_id == user_id)
        )
        media_item = item_result.scalar_one_or_none()
        if media_item is None or media_item.storage_mode != "reference":
            return

        conn_result = await db.execute(
            select(SourceConnector).where(
                SourceConnector.source_id == media_item.source_id,
                SourceConnector.user_id == user_id,
            )
        )
        connector_row = conn_result.scalar_one_or_none()
        if connector_row is None or connector_row.connector_type != "google_drive":
            return

        # Get the Drive file ID from OriginAssetRef
        origin_asset_ref = await ensure_origin_asset_ref(db, media_item)
        if origin_asset_ref is None:
            return
        drive_file_id = origin_asset_ref.provider_object_id
        if not drive_file_id:
            return

        # Build connector and download current file bytes
        try:
            credentials = decrypt_credentials(connector_row.credentials_encrypted)
            connector = build_connector(connector_row, credentials)
            file_bytes = await connector.download_object(drive_file_id)
        except Exception as exc:
            logger.warning(
                "download_and_embed_drive_metadata: failed to download item %s: %s",
                media_item_id, exc,
            )
            return

        await attempt_drive_metadata_embed(db, media_item, file_bytes)

