"""Connector and sync API endpoints (P5-003).

Endpoints:
  POST   /api/v1/sources/{source_id}/connector/s3      — create or replace S3-compatible connector config
  GET    /api/v1/sources/{source_id}/connector         — get current connector config (no secrets)
  POST   /api/v1/sources/{source_id}/sync              — manual sync trigger
  GET    /api/v1/sources/{source_id}/sync-runs         — recent sync run history

All endpoints enforce DB-layer user_id scoping. Secret fields are never returned.
Connector operations fail closed when CONNECTOR_CREDENTIALS_KEY is not configured.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import (
    ConnectorDriveStartResponse,
    ConnectorResponse,
    ConnectorS3ConfigRequest,
    SyncRunResponse,
    SyncRunsResponse,
    TriggerSyncResponse,
    AutoSyncUpdateRequest,
)
from src.connectors.secrets import encrypt_credentials, MissingEncryptionKeyError
from src.connectors.sync_service import trigger_sync
from src.models import Source, SourceConnector, SyncRun
from src.ingestion.upload_service import UploadService
from src.storage.file_store import get_file_store
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sources", tags=["connectors"])

_file_store = get_file_store(settings.storage)
_upload_service = UploadService(_file_store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_owned_source(source_id: str, user_id: str, db: AsyncSession) -> Source:
    """Return the Source or raise 404. Never returns another user's source."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def _check_encryption_key() -> None:
    """Raise 503 if CONNECTOR_CREDENTIALS_KEY is not configured."""
    if not settings.connector.credentials_key:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Connector feature is not available: encryption key not configured.",
                "error_code": "connector_unavailable",
            },
        )


# ---------------------------------------------------------------------------
# POST /sources/{source_id}/connector/s3
# ---------------------------------------------------------------------------

@router.post("/{source_id}/connector/s3", status_code=200)
async def upsert_s3_connector(
    source_id: str,
    body: ConnectorS3ConfigRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorResponse:
    """Create or replace the S3-compatible connector configuration for a source.

    Credentials are encrypted at rest. They are NEVER returned after save.
    """
    _check_encryption_key()
    source = await _require_owned_source(source_id, user_id, db)
    if source.archived_at is not None:
        raise HTTPException(status_code=409, detail="Cannot configure a connector on an archived source")

    # Encrypt credentials — only secret fields go in the encrypted payload
    try:
        credentials_payload = {
            "access_key_id": body.access_key_id,
            "secret_access_key": body.secret_access_key,
        }
        encrypted = encrypt_credentials(credentials_payload)
    except MissingEncryptionKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # Upsert connector row
    existing_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
        )
    )
    connector = existing_result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if connector is None:
        connector = SourceConnector(
            source_id=source_id,
            user_id=user_id,
            connector_type="s3_compatible",
            remote_container_id=body.bucket_name,
            remote_container_label=body.bucket_name,
            prefix=body.prefix,
            region=body.region,
            endpoint_url=body.endpoint_url,
            credentials_encrypted=encrypted,
            config_validated_at=None,
            last_validation_error=None,
        )
        db.add(connector)
    else:
        connector.remote_container_id = body.bucket_name
        connector.remote_container_label = body.bucket_name
        connector.prefix = body.prefix
        connector.region = body.region
        connector.endpoint_url = body.endpoint_url
        connector.credentials_encrypted = encrypted
        connector.config_validated_at = None
        connector.last_validation_error = None
        connector.updated_at = now

    # Update source to reflect connected state
    source.source_type = "s3_compatible"
    source.connector_status = "configured"
    source.updated_at = now

    await db.commit()
    await db.refresh(connector)
    return ConnectorResponse.from_connector(connector)


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/connector
# ---------------------------------------------------------------------------

@router.get("/{source_id}/connector")
async def get_connector(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorResponse:
    """Return connector configuration. Credentials are never included."""
    await _require_owned_source(source_id, user_id, db)

    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
        )
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="No connector configured for this source")

    return ConnectorResponse.from_connector(connector)


# ---------------------------------------------------------------------------
# POST /sources/{source_id}/sync
# ---------------------------------------------------------------------------

@router.patch("/{source_id}/connector/auto-sync", status_code=200)
async def update_auto_sync(
    source_id: str,
    body: AutoSyncUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ConnectorResponse:
    """Enable or disable the auto-sync scheduler for a source connector (P7-006).

    ``interval_minutes`` must be between 15 and 1440 (1 day).
    """
    await _require_owned_source(source_id, user_id, db)

    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
        )
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="No connector configured for this source")

    connector.auto_sync_enabled = body.enabled
    connector.auto_sync_interval_minutes = body.interval_minutes
    connector.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(connector)
    return ConnectorResponse.from_connector(connector)


# ---------------------------------------------------------------------------
# POST /sources/{source_id}/sync
# ---------------------------------------------------------------------------

@router.post("/{source_id}/sync", status_code=202)
async def trigger_source_sync(
    source_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> TriggerSyncResponse:
    """Trigger a manual sync for a connected source.

    Returns immediately after the sync run record is created; the sync executes
    as a background task.
    """
    _check_encryption_key()
    await _require_owned_source(source_id, user_id, db)

    # Attempt to create the sync run synchronously to catch overlap/config errors
    # before returning 202; the actual object enumeration + download runs in background.
    try:
        from src.connectors.secrets import require_encryption_key
        require_encryption_key()

        # Validate no overlap + connector exists + source not archived
        from sqlalchemy import select as _select
        conn_check = await db.execute(
            _select(SourceConnector).where(
                SourceConnector.source_id == source_id,
                SourceConnector.user_id == user_id,
            )
        )
        if conn_check.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=422,
                detail={"message": "No connector configured for this source", "error_code": "no_connector"},
            )

        overlap_check = await db.execute(
            _select(SyncRun).where(
                SyncRun.source_id == source_id,
                SyncRun.status.in_(["pending", "running"]),
            )
        )
        if overlap_check.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail={"message": "A sync is already in progress for this source", "error_code": "sync_overlap"},
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Schedule sync as background task using a new DB session (background tasks
    # need their own session lifetime)
    background_tasks.add_task(
        _run_sync_background,
        source_id=source_id,
        user_id=user_id,
        file_store=_file_store,
        upload_service=_upload_service,
    )

    return TriggerSyncResponse(
        sync_run_id="pending",
        status="accepted",
        message="Sync triggered. Check sync-runs for progress.",
    )


async def _run_sync_background(
    *,
    source_id: str,
    user_id: str,
    file_store,
    upload_service,
) -> None:
    """Background wrapper that creates its own DB session for the full sync run."""
    from src.database import async_session
    async with async_session() as db:
        try:
            await trigger_sync(
                source_id=source_id,
                user_id=user_id,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Background sync failed for source %s: %s", source_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/sync-runs
# ---------------------------------------------------------------------------

@router.get("/{source_id}/sync-runs")
async def list_sync_runs(
    source_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SyncRunsResponse:
    """Return paginated sync run history for a source, newest first."""
    await _require_owned_source(source_id, user_id, db)

    total_result = await db.execute(
        select(func.count()).select_from(SyncRun).where(
            SyncRun.source_id == source_id,
            SyncRun.user_id == user_id,
        )
    )
    total = total_result.scalar_one()

    offset = (page - 1) * per_page
    runs_result = await db.execute(
        select(SyncRun)
        .where(SyncRun.source_id == source_id, SyncRun.user_id == user_id)
        .order_by(SyncRun.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    runs = runs_result.scalars().all()

    return SyncRunsResponse(
        runs=[SyncRunResponse.model_validate(r) for r in runs],
        total=total,
    )
