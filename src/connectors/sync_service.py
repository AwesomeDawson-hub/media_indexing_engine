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

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.connectors.base import ConnectorBase
from src.connectors.factory import build_connector
from src.connectors.secrets import decrypt_credentials
from src.models import OriginAssetRef, Source, SourceConnector, SourceObject, SyncRun
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


@dataclass
class ConnectorAnalysisTaskResult:
    """Structured terminal outcome returned by _run_admitted_analysis_task (P12-010 D7).

    The coordinator inspects this to aggregate analysis failures into SyncRun
    accounting so sync-run counters reflect admitted-task outcomes, not only
    import/download success.
    """

    job_id: str
    outcome: str  # "success" | "failed"
    error: str | None = None


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
    """Execute the sync: list → compare → import → finalize.

    P12-010: admitted connector analysis tasks may now run concurrently up to
    settings.connector.connector_sync_analysis_concurrency (range 1..3, default 2).

    Listing, idempotency checks, import, quota reservation, and SourceObject
    persistence remain serial in the coordinator (D1, D2, D3).  Concurrency starts
    only after an item has been fully admitted — i.e. quota reserved and source
    identity persisted.  The admission semaphore is acquired BEFORE download so the
    coordinator never accumulates an unbounded in-memory byte backlog (D6).

    SyncRun finalization (completed_at and terminal status) is deferred until all
    admitted tasks have settled (D8, D10).  Task outcomes are aggregated into
    SyncRun failure accounting so counters reflect analysis results, not only
    import/download success (D7).
    """
    # Decrypt connector credentials
    try:
        credentials = decrypt_credentials(connector_row.credentials_encrypted)
    except Exception as exc:
        raise ValueError(f"Failed to decrypt connector credentials: {exc}") from exc

    # Build connector instance
    connector: ConnectorBase = build_connector(connector_row, credentials)

    # List remote objects (serial — D3)
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
    from src.ingestion.connector_ingest import process_connector_import

    quota_service = QuotaService()
    vision_provider = _get_vision_provider()
    indexing_service = _get_indexing_service()

    # P12-010: coordinator-owned per-run admission semaphore.  Concurrency applies
    # only to admitted connector analysis tasks (D3).  The slot is acquired before
    # download so at most one coordinator-owned candidate item is held while waiting
    # for a worker slot (D6).  Value 1 preserves the serialized baseline (D12).
    _concurrency = settings.connector.connector_sync_analysis_concurrency
    admission_sem: asyncio.Semaphore | None = (
        asyncio.Semaphore(_concurrency) if vision_provider is not None else None
    )
    # Admitted analysis tasks — drained after the import loop (D8, D10).
    admitted_tasks: list[asyncio.Task[ConnectorAnalysisTaskResult]] = []

    for remote_obj in remote_objects:
        so = existing_objects.get(remote_obj.key)

        # Serial: excluded check (D3)
        if so is not None and so.state == "excluded":
            # User explicitly deleted this item from the gallery — never reimport.
            result.skipped_count += 1
            sync_run.skipped_count = result.skipped_count
            continue

        # Serial: idempotency / version check (D3)
        if so is not None and so.state in ("imported", "duplicate"):
            new_version = str(remote_obj.version) if remote_obj.version is not None else None
            old_version = so.external_version  # always str (String DB column)
            version_changed = (
                new_version is not None
                and old_version is not None
                and new_version != old_version
            )
            logger.info(
                "Idempotency: key=%s state=%s old_version=%r new_version=%r version_changed=%s",
                remote_obj.key, so.state, old_version, new_version, version_changed,
            )
            if not version_changed:
                if new_version is not None and so.external_version != new_version:
                    so.external_version = new_version
                result.skipped_count += 1
                sync_run.skipped_count = result.skipped_count
                continue

        # Use display_name for the upload filename (P7-002: do not derive from key
        # for non-path-based connectors such as Google Drive)
        filename = remote_obj.display_name or os.path.basename(remote_obj.key) or remote_obj.key

        # Acquire admission slot BEFORE download to prevent accumulating an unbounded
        # in-memory byte backlog while waiting for analysis workers (D6).  If all
        # slots are occupied the coordinator waits here; at most one candidate item
        # is held in-flight between this acquire and the task spawn below.
        slot_acquired = False
        if admission_sem is not None:
            await admission_sem.acquire()
            slot_acquired = True

        try:
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
                continue  # slot released in finally

            # P9-001: Zero-transient import — no file_store.save() call
            try:
                upload_result = await process_connector_import(
                    db=db,
                    user_id=user_id,
                    filename=filename,
                    file_bytes=file_bytes,
                    source_id=source.id,
                    file_store=file_store,
                    provider_type=connector_row.connector_type,
                    provider_object_id=remote_obj.key,
                    revision_marker=remote_obj.version,
                )
            except Exception as exc:
                logger.warning("Upload failed for %s: %s", remote_obj.key, exc)
                _upsert_source_object(
                    db, so, source.id, user_id, remote_obj, sync_run.id, "failed", str(exc)[:500]
                )
                result.failed_count += 1
                sync_run.failed_count = result.failed_count
                await db.commit()
                continue  # slot released in finally

            if not upload_result.success:
                _upsert_source_object(
                    db, so, source.id, user_id, remote_obj, sync_run.id, "failed",
                    upload_result.error or "upload validation failed",
                )
                result.failed_count += 1
                sync_run.failed_count = result.failed_count
                await db.commit()
                continue  # slot released in finally

            media_item = upload_result.media_item

            if upload_result.is_duplicate:
                _upsert_source_object(
                    db, so, source.id, user_id, remote_obj, sync_run.id, "duplicate",
                    None, media_item_id=media_item.id, content_hash=media_item.content_hash,
                )
                result.duplicate_count += 1
                sync_run.duplicate_count = result.duplicate_count
                await db.commit()
                continue  # slot released in finally

            # Reserve quota before task spawn (D5)
            reservation_id = None
            if vision_provider is not None and upload_result.processing_job_id:
                try:
                    reservation_id = await quota_service.reserve(db, user_id, media_item.id)
                except QuotaExceededError:
                    logger.warning(
                        "Quota exceeded during sync run %s at object %s — stopping admission",
                        sync_run.id,
                        remote_obj.key,
                    )
                    _upsert_source_object(
                        db, so, source.id, user_id, remote_obj, sync_run.id, "skipped",
                        "quota exceeded",
                    )
                    result.skipped_count += 1
                    sync_run.skipped_count = result.skipped_count
                    sync_run.status = "completed_with_errors"
                    sync_run.error_summary = "Sync stopped: monthly quota exhausted"
                    await db.commit()
                    break  # D9: stop new admission immediately; finally releases slot

            # P8-002: persist SourceObject identity BEFORE spawning the analysis task
            # so the processor's eligibility check can find it (Decision 9).
            imported_so = _upsert_source_object(
                db, so, source.id, user_id, remote_obj, sync_run.id, "imported",
                None, media_item_id=media_item.id, content_hash=media_item.content_hash,
            )
            result.imported_count += 1
            sync_run.imported_count = result.imported_count
            await db.commit()

            # P9-003: Link OriginAssetRef to the now-committed SourceObject
            await db.execute(
                sa_update(OriginAssetRef)
                .where(OriginAssetRef.media_item_id == media_item.id)
                .values(source_object_id=imported_so.id)
            )

            # Auto-add to target collection (coordinator-owned, before task spawn so
            # collection membership is consistent regardless of analysis outcome)
            if connector_row.target_collection_id:
                try:
                    from src.models import CollectionItem
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

            # P12-010: spawn admitted analysis task (D1, D2, D4, D7, D11).
            # The admission slot is already held; it is transferred to the task and
            # released via _run_admitted_analysis_task's finally block.
            if vision_provider is not None and upload_result.processing_job_id and reservation_id is not None:
                task: asyncio.Task[ConnectorAnalysisTaskResult] = asyncio.create_task(
                    _run_admitted_analysis_task(
                        job_id=upload_result.processing_job_id,
                        file_bytes=file_bytes,
                        vision_provider=vision_provider,
                        file_store=file_store,
                        indexing_service=indexing_service,
                        reservation_id=reservation_id,
                        admission_sem=admission_sem,  # type: ignore[arg-type]
                    )
                )
                admitted_tasks.append(task)
                slot_acquired = False  # task now owns the slot; do not release in finally

        finally:
            # Release slot for early-exit paths (download fail, import fail, duplicate,
            # quota stop).  No-op if slot was transferred to the task or never acquired.
            if slot_acquired and admission_sem is not None:
                admission_sem.release()

    # D8 / D10: drain all admitted tasks before writing completed_at and terminal
    # status.  No fire-and-forget tasks survive past sync-run finalization.
    if admitted_tasks:
        task_results = await asyncio.gather(*admitted_tasks, return_exceptions=True)
        for tr in task_results:
            if isinstance(tr, Exception):
                # Unexpected task propagation (task raised rather than returning a result)
                logger.error("Admitted analysis task raised unexpectedly: %s", tr)
                result.failed_count += 1
                sync_run.failed_count = result.failed_count
            elif isinstance(tr, ConnectorAnalysisTaskResult) and tr.outcome == "failed":
                result.failed_count += 1
                sync_run.failed_count = result.failed_count

    # Determine terminal status if not already set by quota break (D9)
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
) -> SourceObject:
    """Insert or update a SourceObject row in the session (not yet committed)."""
    now = datetime.now(timezone.utc)
    if existing is None:
        so = SourceObject(
            source_id=source_id,
            user_id=user_id,
            external_object_key=remote_obj.key,
            external_version=str(remote_obj.version) if remote_obj.version is not None else None,
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
        so = existing
        so.external_version = str(remote_obj.version) if remote_obj.version is not None else None
        so.external_last_modified_at = remote_obj.last_modified_at
        so.external_size = remote_obj.size
        so.last_sync_run_id = sync_run_id
        if media_item_id is not None:
            so.last_imported_media_item_id = media_item_id
        if content_hash is not None:
            so.last_content_hash = content_hash
        so.state = state
        so.last_error = last_error
        so.updated_at = now
    return so


async def _run_admitted_analysis_task(
    *,
    job_id: str,
    file_bytes: bytes,
    vision_provider,
    file_store: FileStore,
    indexing_service,
    reservation_id: str | None,
    admission_sem: asyncio.Semaphore,
) -> ConnectorAnalysisTaskResult:
    """Run analyze_connector_item in a bounded task and release the admission slot.

    The admission slot was acquired by the coordinator before spawning this task
    (D6: no unbounded downloaded-byte backlog).  It is released in the finally
    block, which runs regardless of analysis outcome, so the next item can be
    admitted as soon as this task settles.

    Analysis failure is surfaced through the returned ConnectorAnalysisTaskResult
    so the coordinator can update SyncRun failure accounting (D7).

    Drive rename and metadata embed remain inside analyze_connector_item (D11).
    No storage_path dependency: caller-provided bytes are passed directly (ADR-031).
    """
    from src.analysis.processor import analyze_connector_item

    try:
        succeeded = await analyze_connector_item(
            job_id,
            file_bytes,
            vision_provider,
            file_store,
            indexing_service,
            reservation_id,
        )
        # analyze_connector_item returns True on success and False when it handled a
        # failure internally (wrote job/media-item failed state to DB).  Use this
        # explicit signal rather than exception-based detection so the contract remains
        # independent of whether exceptions escape (they don't in production, but may
        # in test mock injection scenarios).
        if succeeded:
            return ConnectorAnalysisTaskResult(job_id=job_id, outcome="success")
        return ConnectorAnalysisTaskResult(
            job_id=job_id, outcome="failed", error="analysis failed (see job record)"
        )
    except Exception as exc:
        # Unexpected propagation (e.g. mock injection in tests).  analyze_connector_item
        # may not have written DB failure state in this path, but the job status is
        # authoritative; we just ensure the coordinator counts this as a failure.
        logger.error(
            "_run_admitted_analysis_task: job %s raised unexpectedly: %s",
            job_id,
            exc,
        )
        return ConnectorAnalysisTaskResult(job_id=job_id, outcome="failed", error=str(exc))
    finally:
        # Release the admission slot so the coordinator can admit the next item (D4, D10).
        admission_sem.release()


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
