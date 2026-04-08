"""Sync orchestration service for connector-based ingestion (P5-003).

Responsibilities:
- Create and manage SyncRun records (pending → running → terminal state)
- Prevent overlapping runs for the same source
- Enumerate remote objects via the connector
- Compare against SourceObject records to skip unchanged objects
- Download and import new/changed objects through the existing upload service
- Reserve and hand off quota per imported file (same as manual upload path)
- Update per-object state and run counters throughout
- Update Source.connector_status and Source.last_synced_at on completion

This module does NOT reimplement file validation, hashing, dedup, storage,
media-item creation, or analysis enqueueing — all of that happens inside the
existing UploadService and quota/analysis pipeline.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.connectors.base import ConnectorBase
from src.connectors.factory import build_connector
from src.connectors.secrets import decrypt_credentials
from src.models import Source, SourceConnector, SourceObject, SyncRun
from src.ingestion.upload_service import UploadService
from src.storage.file_store import FileStore
from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class SyncRunResult:
    sync_run_id: str
    status: str
    discovered_count: int = 0
    imported_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_summary: str | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def trigger_sync(
    *,
    source_id: str,
    user_id: str,
    db: AsyncSession,
    file_store: FileStore,
    upload_service: UploadService,
    trigger_type: str = "manual",
) -> SyncRunResult:
    """Trigger a manual sync for a connected source.

    Creates a SyncRun, runs the sync, and returns the result.
    Raises ValueError on bad preconditions (no connector, overlap, missing key).
    """
    from src.connectors.secrets import require_encryption_key
    require_encryption_key()

    # Load source — must be owned by this user and not archived
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise ValueError("Source not found")
    if source.archived_at is not None:
        raise ValueError("Cannot sync an archived source")

    # Load connector config
    conn_result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.source_id == source_id,
            SourceConnector.user_id == user_id,
        )
    )
    connector_row = conn_result.scalar_one_or_none()
    if connector_row is None:
        raise ValueError("No connector configured for this source")

    # Prevent overlapping runs
    overlap_result = await db.execute(
        select(SyncRun).where(
            SyncRun.source_id == source_id,
            SyncRun.status.in_(["pending", "running"]),
        )
    )
    if overlap_result.scalar_one_or_none() is not None:
        raise ValueError("A sync run is already in progress for this source")

    # Create sync_run in pending state
    now = datetime.now(timezone.utc)
    sync_run = SyncRun(
        source_id=source_id,
        user_id=user_id,
        connector_type=connector_row.connector_type,
        trigger_type=trigger_type,
        status="running",
        started_at=now,
    )
    db.add(sync_run)
    # Mark source as syncing
    source.connector_status = "syncing"
    await db.commit()
    await db.refresh(sync_run)

    result = SyncRunResult(sync_run_id=sync_run.id, status="running")

    try:
        result = await _run_sync(
            sync_run=sync_run,
            source=source,
            connector_row=connector_row,
            user_id=user_id,
            db=db,
            file_store=file_store,
            upload_service=upload_service,
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Sync run %s failed with unhandled exception: %s", sync_run.id, exc, exc_info=True)
        sync_run.status = "failed"
        sync_run.error_summary = f"Unexpected error: {exc}"[:500]
        sync_run.completed_at = datetime.now(timezone.utc)
        source.connector_status = "error"
        await db.commit()
        result.status = "failed"
        result.error_summary = sync_run.error_summary

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _run_sync(
    *,
    sync_run: SyncRun,
    source: Source,
    connector_row: SourceConnector,
    user_id: str,
    db: AsyncSession,
    file_store: FileStore,
    upload_service: UploadService,
    result: SyncRunResult,
) -> SyncRunResult:
    """Execute the sync: list → compare → import → finalize."""
    # Decrypt connector credentials
    try:
        credentials = decrypt_credentials(connector_row.credentials_encrypted)
    except Exception as exc:
        raise ValueError(f"Failed to decrypt connector credentials: {exc}") from exc

    # Build connector instance
    connector: ConnectorBase = build_connector(connector_row, credentials)

    # List remote objects
    try:
        remote_objects = await connector.list_objects(
            max_keys=settings.connector.max_objects_per_sync
        )
    except Exception as exc:
        sync_run.status = "failed"
        sync_run.error_summary = f"Object listing failed: {exc}"[:500]
        sync_run.completed_at = datetime.now(timezone.utc)
        source.connector_status = "error"
        await db.commit()
        result.status = "failed"
        result.error_summary = sync_run.error_summary
        return result

    result.discovered_count = len(remote_objects)
    sync_run.discovered_count = result.discovered_count
    await db.commit()

    # Load existing source_objects for this source into a lookup dict
    existing_result = await db.execute(
        select(SourceObject).where(
            SourceObject.source_id == source.id,
            SourceObject.user_id == user_id,
        )
    )
    existing_objects: dict[str, SourceObject] = {
        so.external_object_key: so for so in existing_result.scalars().all()
    }

    # Import via quota service (imported inline to avoid circular at module level)
    from src.quota.quota_service import QuotaService, QuotaExceededError
    from src.analysis.processor import analyze_media_item
    from src.analysis.anthropic_provider import AnthropicVisionProvider, AnalysisError
    from src.search.embedder import Embedder
    from src.search.chromadb_store import ChromaDBVectorStore
    from src.search.indexing_service import IndexingService

    quota_service = QuotaService()
    vision_provider = _get_vision_provider()
    indexing_service = _get_indexing_service()

    for remote_obj in remote_objects:
        so = existing_objects.get(remote_obj.key)

        # Idempotency check: skip if key+version unchanged
        if so is not None and so.state in ("imported", "duplicate"):
            if (
                remote_obj.version is not None
                and so.external_version == remote_obj.version
            ):
                result.skipped_count += 1
                sync_run.skipped_count = result.skipped_count
                continue

        # Use display_name for the upload filename (P7-002: do not derive from key
        # for non-path-based connectors such as Google Drive)
        filename = remote_obj.display_name or os.path.basename(remote_obj.key) or remote_obj.key

        # Download
        try:
            file_bytes = await connector.download_object(remote_obj.key)
        except Exception as exc:
            logger.warning("Failed to download %s: %s", remote_obj.key, exc)
            _upsert_source_object(
                db, so, source.id, user_id, remote_obj, sync_run.id, "failed", str(exc)[:500]
            )
            result.failed_count += 1
            sync_run.failed_count = result.failed_count
            await db.commit()
            continue

        # Import via existing upload service
        try:
            upload_result = await upload_service.process_upload(
                db=db,
                user_id=user_id,
                filename=filename,
                file_bytes=file_bytes,
                source_id=source.id,
            )
        except Exception as exc:
            logger.warning("Upload failed for %s: %s", remote_obj.key, exc)
            _upsert_source_object(
                db, so, source.id, user_id, remote_obj, sync_run.id, "failed", str(exc)[:500]
            )
            result.failed_count += 1
            sync_run.failed_count = result.failed_count
            await db.commit()
            continue

        if not upload_result.success:
            _upsert_source_object(
                db, so, source.id, user_id, remote_obj, sync_run.id, "failed",
                upload_result.error or "upload validation failed",
            )
            result.failed_count += 1
            sync_run.failed_count = result.failed_count
            await db.commit()
            continue

        media_item = upload_result.media_item

        if upload_result.is_duplicate:
            _upsert_source_object(
                db, so, source.id, user_id, remote_obj, sync_run.id, "duplicate",
                None, media_item_id=media_item.id, content_hash=media_item.content_hash,
            )
            result.duplicate_count += 1
            sync_run.duplicate_count = result.duplicate_count
            await db.commit()
            continue

        # New import — reserve quota and enqueue analysis
        enqueued = False
        if vision_provider is not None and upload_result.processing_job_id:
            try:
                reservation_id = await quota_service.reserve(db, user_id, media_item.id)
                import asyncio
                asyncio.create_task(
                    analyze_media_item(
                        upload_result.processing_job_id,
                        vision_provider,
                        file_store,
                        indexing_service,
                        reservation_id,
                    )
                )
                enqueued = True
            except QuotaExceededError:
                logger.warning(
                    "Quota exceeded during sync run %s at object %s — stopping ingestion",
                    sync_run.id,
                    remote_obj.key,
                )
                # Record this object as skipped due to quota, then terminate
                _upsert_source_object(
                    db, so, source.id, user_id, remote_obj, sync_run.id, "skipped",
                    "quota exceeded",
                )
                result.skipped_count += 1
                sync_run.skipped_count = result.skipped_count
                await db.commit()
                # Finalize run as completed_with_errors due to quota
                sync_run.status = "completed_with_errors"
                sync_run.error_summary = "Sync stopped: monthly quota exhausted"
                break

        _upsert_source_object(
            db, so, source.id, user_id, remote_obj, sync_run.id, "imported",
            None, media_item_id=media_item.id, content_hash=media_item.content_hash,
        )
        result.imported_count += 1
        sync_run.imported_count = result.imported_count

        # Auto-add to target collection if configured
        if connector_row.target_collection_id:
            try:
                from src.models import CollectionItem
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                # Use INSERT OR IGNORE style: only add if not already a member
                existing_ci = await db.execute(
                    select(CollectionItem).where(
                        CollectionItem.collection_id == connector_row.target_collection_id,
                        CollectionItem.media_item_id == media_item.id,
                    )
                )
                if existing_ci.scalar_one_or_none() is None:
                    db.add(CollectionItem(
                        collection_id=connector_row.target_collection_id,
                        media_item_id=media_item.id,
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to add item %s to collection %s: %s",
                               media_item.id, connector_row.target_collection_id, exc)

        await db.commit()

    # Determine terminal status if not already set by quota break
    if sync_run.status == "running":
        if result.failed_count > 0:
            sync_run.status = "completed_with_errors"
        else:
            sync_run.status = "completed"

    completed_at = datetime.now(timezone.utc)
    sync_run.completed_at = completed_at
    if sync_run.status == "completed":
        source.last_synced_at = completed_at
        source.connector_status = "configured"
    elif sync_run.status == "completed_with_errors":
        source.last_synced_at = completed_at
        source.connector_status = "error"

    await db.commit()
    result.status = sync_run.status
    return result


def _upsert_source_object(
    db: AsyncSession,
    existing: SourceObject | None,
    source_id: str,
    user_id: str,
    remote_obj,
    sync_run_id: str,
    state: str,
    last_error: str | None,
    *,
    media_item_id: str | None = None,
    content_hash: str | None = None,
) -> None:
    """Insert or update a SourceObject row in the session (not yet committed)."""
    now = datetime.now(timezone.utc)
    if existing is None:
        so = SourceObject(
            source_id=source_id,
            user_id=user_id,
            external_object_key=remote_obj.key,
            external_version=remote_obj.version,
            external_last_modified_at=remote_obj.last_modified_at,
            external_size=remote_obj.size,
            last_sync_run_id=sync_run_id,
            last_imported_media_item_id=media_item_id,
            last_content_hash=content_hash,
            state=state,
            last_error=last_error,
        )
        db.add(so)
    else:
        existing.external_version = remote_obj.version
        existing.external_last_modified_at = remote_obj.last_modified_at
        existing.external_size = remote_obj.size
        existing.last_sync_run_id = sync_run_id
        if media_item_id is not None:
            existing.last_imported_media_item_id = media_item_id
        if content_hash is not None:
            existing.last_content_hash = content_hash
        existing.state = state
        existing.last_error = last_error
        existing.updated_at = now


def _get_vision_provider():
    """Attempt to build vision provider; return None if unavailable."""
    try:
        from src.analysis.anthropic_provider import AnthropicVisionProvider, AnalysisError
        return AnthropicVisionProvider()
    except Exception:
        return None


def _get_indexing_service():
    """Attempt to build indexing service; return None if unavailable."""
    try:
        from src.search.embedder import Embedder
        from src.search.chromadb_store import ChromaDBVectorStore
        from src.search.indexing_service import IndexingService
        return IndexingService(Embedder(), ChromaDBVectorStore())
    except Exception:
        return None
