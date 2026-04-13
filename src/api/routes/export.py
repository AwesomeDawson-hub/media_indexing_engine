"""Async connector-aware bulk export (P11-002).

Routes
------
POST   /api/v1/media/export-batch             — submit a batch, get immediate outcomes
GET    /api/v1/media/export-jobs/{job_id}     — poll job status and per-item results
GET    /api/v1/media/export-jobs/{job_id}/download  — stream the ZIP artifact (once)
"""

import asyncio
import io
import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_id, get_db
from src.api.schemas import (
    ExportBatchRequest,
    ExportBatchResponse,
    ExportItemOutcome,
    ExportItemResult,
    ExportJobStatusResponse,
)
import src.api.routes.upload as upload_mod
from src.config import settings
from src.database import async_session
from src.models import ExportJob, MediaItem, MediaMetadata, OriginAssetRef

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["export"])

# Bounded concurrency for Drive fetches (per plan Q5 — same value as analysis batch)
_DRIVE_EXPORT_SEMAPHORE = asyncio.Semaphore(settings.export.drive_concurrency)

# ---------------------------------------------------------------------------
# Submission helpers
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = {"completed", "completed_with_failures", "failed", "expired"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(dt: "datetime | None") -> "datetime | None":
    """Ensure datetime is timezone-aware (SQLite may return naive UTC datetimes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _classify_item(
    item: MediaItem,
    oar: "OriginAssetRef | None",
    accepted_ids: set[str],
) -> ExportItemOutcome:
    """Return the submission-time ExportItemOutcome for a found media item."""
    if item.status != "completed":
        return ExportItemOutcome(
            media_id=item.id,
            outcome="blocked",
            reason_code="analysis_not_completed",
            message="Analysis has not completed for this item.",
        )

    if item.storage_mode == "full":
        return ExportItemOutcome(
            media_id=item.id,
            outcome="accepted",
            reason_code="eligible",
            message="Item is eligible for export.",
        )

    # Reference item — check OAR
    if oar is None:
        return ExportItemOutcome(
            media_id=item.id,
            outcome="blocked",
            reason_code="connector_refetch_not_available",
            message="No origin asset reference found; cannot re-fetch from source.",
        )

    if oar.provider_type == "local_folder":
        return ExportItemOutcome(
            media_id=item.id,
            outcome="blocked",
            reason_code="local_reference_not_supported",
            message="Local-folder reference items cannot be bulk-exported.",
        )

    if oar.provider_type == "google_drive":
        return ExportItemOutcome(
            media_id=item.id,
            outcome="accepted",
            reason_code="eligible",
            message="Item is eligible for export via Drive.",
        )

    # Any other provider
    return ExportItemOutcome(
        media_id=item.id,
        outcome="blocked",
        reason_code="provider_bulk_export_not_supported",
        message=f"Provider '{oar.provider_type}' does not support bulk export.",
    )


# ---------------------------------------------------------------------------
# Route 1: POST /media/export-batch
# ---------------------------------------------------------------------------

@router.post("/media/export-batch", status_code=202, response_model=ExportBatchResponse)
async def submit_export_batch(
    body: ExportBatchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ExportBatchResponse:
    """Submit a batch-export request.

    Returns HTTP 202 immediately with per-item submission outcomes.
    The actual export runs asynchronously.
    """
    max_batch = settings.export.max_batch_size

    # Guard: batch too large
    if len(body.media_ids) > max_batch:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "export_batch_too_large",
                "message": f"Batch size {len(body.media_ids)} exceeds maximum of {max_batch}.",
                "max_batch_size": max_batch,
            },
        )

    # Guard: too many active jobs for this user
    active_count_result = await db.execute(
        select(func.count())
        .select_from(ExportJob)
        .where(
            ExportJob.user_id == user_id,
            ExportJob.status.in_(["pending", "running"]),
        )
    )
    active_count = active_count_result.scalar_one()
    if active_count >= settings.export.max_active_jobs_per_user:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "export_job_limit_reached",
                "message": "You have reached the maximum number of concurrent export jobs.",
                "max_active_jobs": settings.export.max_active_jobs_per_user,
            },
        )

    # Deduplicate requested IDs (preserve first occurrence)
    seen: set[str] = set()
    unique_ids: list[str] = []
    for mid in body.media_ids:
        if mid not in seen:
            seen.add(mid)
            unique_ids.append(mid)

    # Load found media items (single query, ownership-scoped)
    items_result = await db.execute(
        select(MediaItem).where(
            MediaItem.id.in_(unique_ids),
            MediaItem.user_id == user_id,
        )
    )
    found_items: dict[str, MediaItem] = {item.id: item for item in items_result.scalars().all()}

    # Load OARs for all found reference items (single query)
    reference_ids = [i.id for i in found_items.values() if i.storage_mode == "reference"]
    oar_map: dict[str, OriginAssetRef] = {}
    if reference_ids:
        oar_result = await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id.in_(reference_ids))
        )
        for oar in oar_result.scalars().all():
            oar_map[oar.media_item_id] = oar

    # Check for items already in an active export job for this user
    active_accepted_ids: set[str] = set()
    active_jobs_result = await db.execute(
        select(ExportJob).where(
            ExportJob.user_id == user_id,
            ExportJob.status.in_(["pending", "running"]),
        )
    )
    for active_job in active_jobs_result.scalars().all():
        try:
            prior_outcomes = json.loads(active_job.submission_outcomes or "[]")
            for o in prior_outcomes:
                if o.get("outcome") == "accepted":
                    active_accepted_ids.add(o["media_id"])
        except (json.JSONDecodeError, KeyError):
            pass

    # Build per-item outcomes
    accepted_ids: set[str] = set()
    outcomes: list[ExportItemOutcome] = []

    for mid in unique_ids:
        if mid not in found_items:
            outcomes.append(
                ExportItemOutcome(
                    media_id=mid,
                    outcome="rejected",
                    reason_code="media_item_not_found",
                    message="Item not found or access denied.",
                )
            )
            continue

        item = found_items[mid]

        # Already being exported by an active job
        if mid in active_accepted_ids:
            outcomes.append(
                ExportItemOutcome(
                    media_id=mid,
                    outcome="blocked",
                    reason_code="export_in_progress",
                    message="Item is already being exported by another active job.",
                )
            )
            continue

        outcome = _classify_item(item, oar_map.get(mid), accepted_ids)
        if outcome.outcome == "accepted":
            accepted_ids.add(mid)
        outcomes.append(outcome)

    accepted_count = sum(1 for o in outcomes if o.outcome == "accepted")
    blocked_count = sum(1 for o in outcomes if o.outcome == "blocked")
    rejected_count = sum(1 for o in outcomes if o.outcome == "rejected")

    # Guard: no eligible items — return full locked detail payload, create no job
    if accepted_count == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "export_no_eligible_items",
                "message": "No eligible items found in the request.",
                "request_count": len(unique_ids),
                "accepted_count": 0,
                "blocked_count": blocked_count,
                "rejected_count": rejected_count,
                "outcomes": [o.model_dump() for o in outcomes],
            },
        )

    # Persist the ExportJob
    job = ExportJob(
        user_id=user_id,
        status="pending",
        request_count=len(unique_ids),
        accepted_count=accepted_count,
        blocked_count=blocked_count,
        rejected_count=rejected_count,
        submission_outcomes=json.dumps([o.model_dump() for o in outcomes]),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Schedule background export (opens its own session — does not rely on request db)
    background_tasks.add_task(_run_export_job, job.id, user_id)

    return ExportBatchResponse(
        job_id=job.id,
        status=job.status,
        request_count=job.request_count,
        accepted_count=job.accepted_count,
        blocked_count=job.blocked_count,
        rejected_count=job.rejected_count,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Route 2: GET /media/export-jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/media/export-jobs/{job_id}", response_model=ExportJobStatusResponse)
async def get_export_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ExportJobStatusResponse:
    """Return the current status of an export job owned by the caller."""
    job = await _load_user_job(db, job_id, user_id)

    # Lazily expire if TTL has passed
    job = await _maybe_expire_job(db, job)

    item_results: list[ExportItemResult] | None = None
    exported_count: int | None = None
    failed_count: int | None = None

    if job.item_results is not None:
        try:
            raw_results = json.loads(job.item_results)
            item_results = [ExportItemResult(**r) for r in raw_results]
            exported_count = sum(1 for r in item_results if r.status == "exported")
            failed_count = sum(1 for r in item_results if r.status == "failed")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    artifact_ready = (
        job.status in ("completed", "completed_with_failures")
        and not job.artifact_downloaded
        and job.artifact_path is not None
        and (_normalize_dt(job.artifact_expires_at) is None or _normalize_dt(job.artifact_expires_at) > _now())
    )

    return ExportJobStatusResponse(
        job_id=job.id,
        status=job.status,
        request_count=job.request_count,
        accepted_count=job.accepted_count,
        blocked_count=job.blocked_count,
        rejected_count=job.rejected_count,
        exported_count=exported_count,
        failed_count=failed_count,
        item_results=item_results,
        artifact_ready=artifact_ready,
        artifact_expires_at=_normalize_dt(job.artifact_expires_at),
        created_at=_normalize_dt(job.created_at) or _now(),
        completed_at=_normalize_dt(job.completed_at),
    )


# ---------------------------------------------------------------------------
# Route 3: GET /media/export-jobs/{job_id}/download
# ---------------------------------------------------------------------------

@router.get("/media/export-jobs/{job_id}/download")
async def download_export_artifact(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Stream the assembled ZIP artifact for a completed export job (single-use)."""
    job = await _load_user_job(db, job_id, user_id)

    if job.status not in ("completed", "completed_with_failures"):
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "export_not_ready",
                "message": "Export job has not completed yet.",
                "current_status": job.status,
            },
        )

    if job.artifact_downloaded or job.artifact_path is None:
        raise HTTPException(
            status_code=410,
            detail={
                "error_code": "export_artifact_expired",
                "message": "The export artifact has already been downloaded or has expired.",
            },
        )

    now = _now()
    expires = _normalize_dt(job.artifact_expires_at)
    if expires is not None and expires <= now:
        job.status = "expired"
        await db.commit()
        raise HTTPException(
            status_code=410,
            detail={
                "error_code": "export_artifact_expired",
                "message": "The export artifact has expired.",
            },
        )

    # Read the artifact
    try:
        zip_bytes = await upload_mod._file_store.read(job.artifact_path)
    except Exception:
        logger.exception("Failed to read export artifact %s", job.artifact_path)
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "export_artifact_read_failed",
                "message": "Failed to read export artifact.",
            },
        )

    # Mark as consumed
    job.artifact_downloaded = True
    await db.commit()

    # Best-effort delete (do not block the response on failure)
    artifact_path = job.artifact_path
    asyncio.create_task(_delete_artifact(artifact_path))

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="export_{job_id[:8]}.zip"'},
    )


# ---------------------------------------------------------------------------
# Background job executor
# ---------------------------------------------------------------------------

async def _run_export_job(job_id: str, user_id: str) -> None:
    """Execute the export job: fetch bytes, embed metadata, assemble ZIP, save artifact."""
    from src.api.routes.download import (
        _embedder,
        _ext_for_mime,
        _metadata_to_result,
        _sanitize_filename,
    )

    async with async_session() as db:
        job_result = await db.execute(select(ExportJob).where(ExportJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job is None:
            logger.error("Export job %s not found in background task", job_id)
            return

        # Parse accepted item IDs from submission outcomes
        try:
            all_outcomes = json.loads(job.submission_outcomes or "[]")
        except json.JSONDecodeError:
            all_outcomes = []
        accepted_ids = [o["media_id"] for o in all_outcomes if o.get("outcome") == "accepted"]

        if not accepted_ids:
            job.status = "failed"
            await db.commit()
            return

        # Load items, metadata and OARs for all accepted IDs
        items_result = await db.execute(
            select(MediaItem).where(
                MediaItem.id.in_(accepted_ids),
                MediaItem.user_id == user_id,
            )
        )
        items_map: dict[str, MediaItem] = {i.id: i for i in items_result.scalars().all()}

        meta_result = await db.execute(
            select(MediaMetadata).where(MediaMetadata.media_item_id.in_(accepted_ids))
        )
        meta_map: dict[str, MediaMetadata] = {m.media_item_id: m for m in meta_result.scalars().all()}

        oar_result = await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id.in_(accepted_ids))
        )
        oar_map: dict[str, OriginAssetRef] = {o.media_item_id: o for o in oar_result.scalars().all()}

        # Transition to running
        job.status = "running"
        await db.commit()

    # -- DB session closed; do IO work outside the session -----------------

    item_results: list[ExportItemResult] = []

    # Write the ZIP incrementally to a temp file on disk (no full in-memory buffer).
    _tmp_fd, _tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(_tmp_fd)

    # Track used ZIP entry names to avoid collisions
    used_names: set[str] = set()

    try:
        with zipfile.ZipFile(_tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for mid in accepted_ids:
                item = items_map.get(mid)
                if item is None:
                    item_results.append(ExportItemResult(
                        media_id=mid,
                        status="failed",
                        error_code="drive_file_not_found",
                        message="Item not found when job executed.",
                    ))
                    continue

                meta = meta_map.get(mid)

                # Determine ZIP entry filename
                ext = _ext_for_mime(item.mime_type or "", item.original_filename or "file")
                if meta and meta.title:
                    candidate = _sanitize_filename(meta.title, ext)
                else:
                    candidate = None
                if not candidate:
                    candidate = item.original_filename or f"{mid[:8]}{ext}"

                # Deduplicate entry name
                entry_name = candidate
                counter = 1
                while entry_name in used_names:
                    base, file_ext = entry_name.rsplit(".", 1) if "." in entry_name else (entry_name, "")
                    suffix = f"_{counter}"
                    entry_name = f"{base}{suffix}.{file_ext}" if file_ext else f"{base}{suffix}"
                    counter += 1
                used_names.add(entry_name)

                # Fetch bytes
                try:
                    if item.storage_mode == "full":
                        file_bytes = await upload_mod._file_store.read(item.storage_path)
                    else:
                        oar = oar_map.get(mid)
                        if oar is None or oar.provider_type != "google_drive":
                            item_results.append(ExportItemResult(
                                media_id=mid,
                                status="failed",
                                error_code="drive_fetch_failed",
                                message="No Drive OAR found at execution time.",
                                filename=entry_name,
                            ))
                            continue

                        from src.connectors.drive_reference_fetch import fetch_drive_reference_bytes
                        async with _DRIVE_EXPORT_SEMAPHORE:
                            async with async_session() as db:
                                file_bytes = await fetch_drive_reference_bytes(db, item, user_id)

                except HTTPException as exc:
                    error_code, msg = _map_drive_exception(exc)
                    item_results.append(ExportItemResult(
                        media_id=mid,
                        status="failed",
                        error_code=error_code,
                        message=msg,
                        filename=entry_name,
                    ))
                    continue
                except Exception as exc:
                    logger.exception("Unexpected error fetching item %s for export job %s", mid, job_id)
                    item_results.append(ExportItemResult(
                        media_id=mid,
                        status="failed",
                        error_code="drive_fetch_failed",
                        message=str(exc),
                        filename=entry_name,
                    ))
                    continue

                # Embed metadata
                try:
                    if meta is not None:
                        from src.api.routes.download import _embedder, _metadata_to_result
                        metadata_result = _metadata_to_result(meta)
                        enrichment = _embedder.embed(file_bytes, item.mime_type, metadata_result, item.original_filename)
                        final_bytes = enrichment.enriched_bytes
                        final_mime = enrichment.output_mime_type
                        final_ext = _ext_for_mime(final_mime, entry_name)
                        # Update entry name with possibly-updated extension
                        base_no_ext = entry_name.rsplit(".", 1)[0] if "." in entry_name else entry_name
                        entry_name = f"{base_no_ext}{final_ext}"
                    else:
                        final_bytes = file_bytes
                except Exception:
                    logger.exception("Metadata embed failed for item %s", mid)
                    final_bytes = file_bytes

                try:
                    zf.writestr(entry_name, final_bytes)
                except Exception as exc:
                    logger.exception("Failed to write ZIP entry for item %s", mid)
                    item_results.append(ExportItemResult(
                        media_id=mid,
                        status="failed",
                        error_code="artifact_write_failed",
                        message=str(exc),
                        filename=entry_name,
                    ))
                    continue

                item_results.append(ExportItemResult(
                    media_id=mid,
                    status="exported",
                    filename=entry_name,
                ))
        # ZipFile context closed — all entries flushed to _tmp_path on disk.
        with open(_tmp_path, "rb") as _fh:
            zip_bytes = _fh.read()
    finally:
        try:
            os.unlink(_tmp_path)
        except OSError:
            pass

    artifact_path: str | None = None

    try:
        artifact_path = await upload_mod._file_store.save(
            user_id=user_id,
            content_hash=f"export_{job_id}",
            original_filename="export.zip",
            file_bytes=zip_bytes,
        )
    except Exception:
        logger.exception("Failed to save export artifact for job %s", job_id)

    # -- Persist final job state ------------------------------------------

    exported_count = sum(1 for r in item_results if r.status == "exported")
    failed_count = sum(1 for r in item_results if r.status == "failed")

    if artifact_path is None:
        final_status = "failed"
    elif failed_count == 0:
        final_status = "completed"
    else:
        final_status = "completed_with_failures"

    now = _now()
    async with async_session() as db:
        job_result = await db.execute(select(ExportJob).where(ExportJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job is None:
            logger.error("Export job %s vanished before final update", job_id)
            return

        job.status = final_status
        job.item_results = json.dumps([r.model_dump() for r in item_results])
        job.artifact_path = artifact_path
        job.artifact_expires_at = now + timedelta(hours=settings.export.artifact_ttl_hours)
        job.completed_at = now
        await db.commit()

    logger.info(
        "Export job %s finished: status=%s exported=%d failed=%d",
        job_id,
        final_status,
        exported_count,
        failed_count,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _load_user_job(db: AsyncSession, job_id: str, user_id: str) -> ExportJob:
    """Load an ExportJob scoped to the calling user or raise 404."""
    result = await db.execute(
        select(ExportJob).where(ExportJob.id == job_id, ExportJob.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "export_job_not_found",
                "message": "Export job not found or access denied.",
            },
        )
    return job


async def _maybe_expire_job(db: AsyncSession, job: ExportJob) -> ExportJob:
    """If the artifact TTL has passed, transition job status to 'expired' and persist.

    Only truly-terminal statuses (failed, expired) are skipped.  Jobs that are
    'completed' or 'completed_with_failures' must still be TTL-checked so that
    the status endpoint agrees with the download endpoint on expiry.
    """
    if job.status in {"failed", "expired"}:
        return job
    expires = _normalize_dt(job.artifact_expires_at)
    if expires is not None and expires <= _now():
        job.status = "expired"
        await db.commit()
    return job


async def _sweep_expired_export_artifacts(db: AsyncSession) -> None:
    """Sweep all non-terminal export jobs whose artifact TTL has elapsed (P11-002).

    Intended to run at startup and/or on a periodic schedule.  For each job
    whose ``artifact_expires_at`` is in the past and whose status is not yet
    'failed' or 'expired', the artifact file is best-effort deleted and the
    job status is promoted to 'expired'.
    """
    now = _now()
    result = await db.execute(
        select(ExportJob).where(
            ~ExportJob.status.in_(["failed", "expired"]),
        )
    )
    jobs = result.scalars().all()
    swept = 0
    for job in jobs:
        expires = _normalize_dt(job.artifact_expires_at)
        if expires is not None and expires <= now:
            if job.artifact_path:
                await _delete_artifact(job.artifact_path)
            job.status = "expired"
            swept += 1
    if swept:
        await db.commit()
        logger.info("Swept %d expired export artifact(s) on startup", swept)


async def _delete_artifact(artifact_path: str) -> None:
    """Best-effort deletion of an exported artifact from the file store."""
    try:
        await upload_mod._file_store.delete(artifact_path)
    except Exception:
        logger.warning("Could not delete export artifact at %s", artifact_path)


def _map_drive_exception(exc: HTTPException) -> tuple[str, str]:
    """Map a Drive-fetch HTTPException to an export error code and message."""
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("error_code", "drive_fetch_failed")
    elif isinstance(detail, str):
        code = "drive_fetch_failed"
        return code, detail
    else:
        code = "drive_fetch_failed"

    msg = detail.get("message", str(exc)) if isinstance(detail, dict) else str(exc)
    return code, msg
