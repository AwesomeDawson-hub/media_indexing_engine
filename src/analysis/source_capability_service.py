"""Connector capability snapshot helpers for P9-004."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.google_drive_oauth import scope_has_write
from src.connectors.secrets import decrypt_credentials
from src.models import SourceCapabilitySnapshot, SourceConnector

_ERR_CONNECTOR_UNAVAILABLE = "connector_unavailable"
_ERR_CREDENTIALS_UNAVAILABLE = "credentials_unavailable"


def _scope_tier(granted_scopes: str | None) -> str:
    if not granted_scopes:
        return "unknown"
    return "writable" if scope_has_write(granted_scopes) else "read_only"


def _derive_snapshot_state(connector: SourceConnector) -> tuple[bool, bool, bool, str, str | None, str | None]:
    if connector.connector_type != "google_drive":
        return False, False, False, "error", _ERR_CONNECTOR_UNAVAILABLE, "Unsupported connector type for capability snapshot."

    if connector.last_validation_error:
        return False, False, False, "error", _ERR_CONNECTOR_UNAVAILABLE, connector.last_validation_error[:500]

    try:
        credentials = decrypt_credentials(connector.credentials_encrypted)
    except Exception:
        return False, False, False, "error", _ERR_CREDENTIALS_UNAVAILABLE, "Connector credentials could not be decrypted."

    has_refresh_token = bool(credentials.get("refresh_token"))
    can_write = scope_has_write(connector.granted_scopes) and has_refresh_token
    can_read = has_refresh_token
    can_refetch = has_refresh_token
    if not has_refresh_token:
        return False, False, False, "error", _ERR_CREDENTIALS_UNAVAILABLE, "Connector is missing refresh credentials."
    return can_read, can_write, can_refetch, "current", None, None


async def get_capability_snapshot(
    db: AsyncSession,
    *,
    source_connector_id: str,
) -> SourceCapabilitySnapshot | None:
    result = await db.execute(
        select(SourceCapabilitySnapshot).where(
            SourceCapabilitySnapshot.source_connector_id == source_connector_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_drive_capability_snapshot(
    db: AsyncSession,
    connector: SourceConnector,
) -> SourceCapabilitySnapshot:
    now = datetime.now(timezone.utc)
    snapshot = await get_capability_snapshot(db, source_connector_id=connector.id)
    can_read, can_write, can_refetch, verification_state, error_code, error_message = _derive_snapshot_state(connector)

    if snapshot is None:
        snapshot = SourceCapabilitySnapshot(
            source_id=connector.source_id,
            source_connector_id=connector.id,
            user_id=connector.user_id,
            provider_type=connector.connector_type,
            can_read=can_read,
            can_write=can_write,
            can_refetch=can_refetch,
            scope_text=connector.granted_scopes,
            scope_tier=_scope_tier(connector.granted_scopes),
            verification_state=verification_state,
            last_verified_at=now,
            last_error_code=error_code,
            last_error_message=error_message,
        )
        db.add(snapshot)
        return snapshot

    snapshot.source_id = connector.source_id
    snapshot.user_id = connector.user_id
    snapshot.provider_type = connector.connector_type
    snapshot.can_read = can_read
    snapshot.can_write = can_write
    snapshot.can_refetch = can_refetch
    snapshot.scope_text = connector.granted_scopes
    snapshot.scope_tier = _scope_tier(connector.granted_scopes)
    snapshot.verification_state = verification_state
    snapshot.last_verified_at = now
    snapshot.last_error_code = error_code
    snapshot.last_error_message = error_message
    snapshot.updated_at = now
    return snapshot


async def ensure_drive_capability_snapshot(
    db: AsyncSession,
    connector: SourceConnector,
) -> SourceCapabilitySnapshot:
    snapshot = await get_capability_snapshot(db, source_connector_id=connector.id)
    if snapshot is None or snapshot.verification_state != "current":
        return await upsert_drive_capability_snapshot(db, connector)
    return snapshot


def mark_snapshot_error(
    snapshot: SourceCapabilitySnapshot,
    *,
    error_code: str,
    error_message: str,
    can_read: bool = False,
    can_refetch: bool = False,
) -> None:
    now = datetime.now(timezone.utc)
    snapshot.can_read = can_read
    snapshot.can_write = False
    snapshot.can_refetch = can_refetch
    snapshot.verification_state = "error"
    snapshot.last_verified_at = now
    snapshot.last_error_code = error_code
    snapshot.last_error_message = error_message[:500]
    snapshot.updated_at = now