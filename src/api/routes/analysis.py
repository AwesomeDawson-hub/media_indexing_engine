"""Analysis API endpoints: get analysis status and trigger re-analysis."""

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy import delete as sql_delete, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import AnalysisResponse, MetadataFields, JobInfo, ReanalyzeRequest, ReanalyzeResponse, MetadataUpdateRequest, BatchOperationRequest, BatchReanalyzeResponse, BatchReanalyzeItemOutcome, BatchReanalyzeResponseV2, BatchDeleteResponse, BatchTagRequest, BatchTagResponse
from src.api.routes.upload import _vision_provider, _file_store, _indexing_service
from src.api.storage_guards import assert_original_accessible, original_is_accessible
from src.analysis.processor import analyze_media_item, analyze_connector_item
from src.analysis.schemas import MediaMetadataResult
from src.connectors.drive_reference_fetch import fetch_drive_reference_bytes
from src.database import async_session
from src.models import MediaItem, MediaMetadata, OriginAssetRef, PreviewAsset, ProcessingJob, QuotaEvent, SourceMutationHistory, WriteBackOperation, CurationScore, SourceObject
from src.quota.quota_service import QuotaExceededError, QuotaService, build_quota_exceeded_detail

router = APIRouter(prefix="/api/v1", tags=["analysis"])

_quota_service = QuotaService()
_DRIVE_BATCH_SEMAPHORE = asyncio.Semaphore(3)


import logging as _logging

_logger = _logging.getLogger(__name__)


async def _run_drive_batch_item(
    job_id: str,
    media_item_id: str,
    user_id: str,
    hint: str | None,
    reservation_id: str | None,
) -> None:
    """Background task: fetch Drive bytes under bounded concurrency then run connector analysis."""
    async with _DRIVE_BATCH_SEMAPHORE:
        async with async_session() as db:
            item_result = await db.execute(
                select(MediaItem).where(MediaItem.id == media_item_id)
            )
            item = item_result.scalar_one_or_none()
            if item is None:
                _logger.error("_run_drive_batch_item: MediaItem %s not found", media_item_id)
                return

            try:
                file_bytes = await fetch_drive_reference_bytes(db, item, user_id)
            except Exception as exc:
                _logger.error(
                    "_run_drive_batch_item: Drive fetch failed for %s: %s", media_item_id, exc
                )
                job_res = await db.execute(
                    select(ProcessingJob).where(ProcessingJob.id == job_id)
                )
                job = job_res.scalar_one_or_none()
                if job is not None:
                    job.status = "failed"
                    job.error_message = f"Drive fetch failed: {exc}"
                    await db.commit()
                if reservation_id is not None:
                    await _quota_service.release(db, reservation_id)
                return

    await analyze_connector_item(
        job_id,
        file_bytes,
        _vision_provider,
        _file_store,
        _indexing_service,
        reservation_id,
        hint,
    )


@router.get("/media/{media_id}/analysis")
async def get_analysis(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> AnalysisResponse:
    """Get analysis status and metadata for a media item."""
    # Load media item
    result = await db.execute(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Load metadata (may not exist yet)
    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_id)
    )
    meta = meta_result.scalar_one_or_none()

    # Load latest processing job
    job_result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.media_item_id == media_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()

    if meta is not None:
        # If there's an active job, report its status instead of the stale completed metadata
        if job is not None and job.status in ("pending", "running"):
            job_info = JobInfo(
                id=job.id,
                status=job.status,
                attempts=job.attempts,
                error_message=job.error_message,
                created_at=job.created_at,
            )
            return AnalysisResponse(
                media_item_id=media_id,
                status="processing",
                job=job_info,
            )

        return AnalysisResponse(
            media_item_id=media_id,
            status="completed",
            metadata=MetadataFields(
                title=meta.title,
                description=meta.description,
                tags=json.loads(meta.tags),
                objects=json.loads(meta.objects),
                scenes=json.loads(meta.scenes),
                context=meta.context,
                mood=meta.mood,
                people=json.loads(meta.people),
                people_count=meta.people_count,
                orientation=meta.orientation,
                colors=json.loads(meta.colors),
                location_hint=meta.location_hint,
                quality_notes=meta.quality_notes,
                ocr_text=meta.ocr_text,
            ),
            ai_provider=meta.ai_provider,
            ai_model=meta.ai_model,
            analyzed_at=meta.analyzed_at,
        )

    # No metadata yet — return job status
    job_info = None
    status = item.status
    if job is not None:
        job_info = JobInfo(
            id=job.id,
            status=job.status,
            attempts=job.attempts,
            error_message=job.error_message,
            created_at=job.created_at,
        )
        if job.status == "failed":
            status = "failed"
        elif job.status in ("pending", "running"):
            status = job.status

    return AnalysisResponse(
        media_item_id=media_id,
        status=status,
        metadata=None,
        job=job_info,
    )


@router.post("/media/{media_id}/reanalyze", status_code=202)
async def reanalyze(
    media_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
    body: ReanalyzeRequest = Body(default=ReanalyzeRequest()),
) -> ReanalyzeResponse:
    """Trigger re-analysis for a media item."""
    # Load media item
    result = await db.execute(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    # For reference-mode items backed by Google Drive, fetch transiently via shared service.
    if item.storage_mode == "reference":
        oar_result = await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_id)
        )
        oar = oar_result.scalar_one_or_none()
        if oar is not None and oar.provider_type == "google_drive":
            from src.connectors.drive_reference_fetch import fetch_drive_reference_bytes

            # Check for in-progress analysis
            active_result = await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.media_item_id == media_id,
                    ProcessingJob.status.in_(["pending", "running"]),
                )
            )
            if active_result.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="Analysis already in progress")

            reservation_id: str | None = None
            if _vision_provider:
                try:
                    reservation_id = await _quota_service.reserve(db, user_id, media_id)
                except QuotaExceededError as exc:
                    raise HTTPException(status_code=429, detail=build_quota_exceeded_detail(exc))

            # Fetch bytes transiently — errors surface immediately with locked error contract
            try:
                file_bytes = await fetch_drive_reference_bytes(db, item, user_id)
            except Exception:
                if reservation_id is not None:
                    await _quota_service.release(db, reservation_id)
                raise

            try:
                new_job = ProcessingJob(
                    media_item_id=media_id,
                    job_type="analysis",
                    status="pending",
                )
                db.add(new_job)
                await db.flush()
                job_id = new_job.id
                item.status = "uploaded"
                await db.commit()
            except Exception:
                await db.rollback()
                if reservation_id is not None:
                    await _quota_service.release(db, reservation_id)
                raise

            if _vision_provider:
                background_tasks.add_task(
                    analyze_connector_item,
                    job_id,
                    file_bytes,
                    _vision_provider,
                    _file_store,
                    _indexing_service,
                    reservation_id,
                    body.hint,
                )

            return ReanalyzeResponse(
                media_item_id=media_id,
                job_id=job_id,
                message="Re-analysis queued",
            )

    # Standard path (full-mode) and non-Drive reference items (local_folder, etc.)
    assert_original_accessible(item)

    # Check for in-progress analysis
    active_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.media_item_id == media_id,
            ProcessingJob.status.in_(["pending", "running"]),
        )
    )
    active_job = active_result.scalar_one_or_none()
    if active_job is not None:
        raise HTTPException(status_code=409, detail="Analysis already in progress")

    reservation_id: str | None = None
    if _vision_provider:
        try:
            reservation_id = await _quota_service.reserve(db, user_id, media_id)
        except QuotaExceededError as exc:
            raise HTTPException(status_code=429, detail=build_quota_exceeded_detail(exc))

    try:
        new_job = ProcessingJob(
            media_item_id=media_id,
            job_type="analysis",
            status="pending",
        )
        db.add(new_job)
        await db.flush()
        job_id = new_job.id

        item.status = "uploaded"
        await db.commit()
    except Exception:
        await db.rollback()
        if reservation_id is not None:
            await _quota_service.release(db, reservation_id)
        raise

    # Enqueue background task
    if _vision_provider:
        background_tasks.add_task(
            analyze_media_item,
            job_id,
            _vision_provider,
            _file_store,
            _indexing_service,
            reservation_id,
            body.hint,
        )

    return ReanalyzeResponse(
        media_item_id=media_id,
        job_id=job_id,
        message="Re-analysis queued",
    )


@router.post("/media/reanalyze-batch", status_code=202)
async def reanalyze_batch(
    request: BatchOperationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> BatchReanalyzeResponseV2:
    """P11-001: Capability-aware batch reanalysis with explicit per-item outcomes.

    Classifies every requested item as accepted/blocked/rejected, enforces
    all-or-nothing quota across all accepted candidates, and returns a
    structured per-item report. Drive-backed reference items are admitted via
    async queueing only — no Drive fetch occurs during the request.
    """
    requested_ids: list[str] = list(request.media_ids)

    # 1. Load all owned items in one query.
    found_result = await db.execute(
        select(MediaItem).where(
            MediaItem.id.in_(requested_ids),
            MediaItem.user_id == user_id,
        )
    )
    found_items: dict[str, MediaItem] = {
        item.id: item for item in found_result.scalars().all()
    }

    # 2. Load OARs for reference-mode items in one query.
    reference_ids = [
        iid for iid, item in found_items.items() if item.storage_mode == "reference"
    ]
    oar_map: dict[str, OriginAssetRef] = {}
    if reference_ids:
        oar_result = await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id.in_(reference_ids))
        )
        for oar in oar_result.scalars().all():
            oar_map[str(oar.media_item_id)] = oar

    # 3. Check in-progress jobs for all found items in one query.
    in_progress_ids: set[str] = set()
    if found_items:
        ip_result = await db.execute(
            select(ProcessingJob.media_item_id).where(
                ProcessingJob.media_item_id.in_(list(found_items.keys())),
                ProcessingJob.status.in_(["pending", "running"]),
            )
        )
        in_progress_ids = {str(row) for row in ip_result.scalars().all()}

    # 4. Classify every requested item.
    outcome_map: dict[str, BatchReanalyzeItemOutcome] = {}
    accepted_full: list[MediaItem] = []   # full-storage eligible
    accepted_drive: list[MediaItem] = []  # Drive-backed reference eligible

    for iid in requested_ids:
        if iid not in found_items:
            outcome_map[iid] = BatchReanalyzeItemOutcome(
                media_id=iid,
                outcome="rejected",
                reason_code="media_item_not_found",
                message="Media item not found or not accessible to the caller.",
            )
            continue

        item = found_items[iid]

        if iid in in_progress_ids:
            outcome_map[iid] = BatchReanalyzeItemOutcome(
                media_id=iid,
                outcome="blocked",
                reason_code="analysis_in_progress",
                message="Analysis is already in progress for this item.",
            )
            continue

        if item.storage_mode == "reference":
            oar = oar_map.get(iid)
            if oar is None:
                outcome_map[iid] = BatchReanalyzeItemOutcome(
                    media_id=iid,
                    outcome="blocked",
                    reason_code="connector_refetch_not_available",
                    message="No connector reference found for this item; batch reanalysis is not available.",
                )
            elif oar.provider_type == "google_drive":
                accepted_drive.append(item)  # outcome filled after quota
            elif oar.provider_type == "local_folder":
                outcome_map[iid] = BatchReanalyzeItemOutcome(
                    media_id=iid,
                    outcome="blocked",
                    reason_code="local_reference_not_supported",
                    message="Local-folder reference items are not eligible for server-side batch reanalysis.",
                )
            else:
                outcome_map[iid] = BatchReanalyzeItemOutcome(
                    media_id=iid,
                    outcome="blocked",
                    reason_code="provider_batch_reanalysis_not_supported",
                    message=f"Provider '{oar.provider_type}' is not supported for batch reanalysis.",
                )
        elif item.storage_mode == "full":
            accepted_full.append(item)  # outcome filled after quota
        else:
            # preview_only or any future storage mode without batch support
            outcome_map[iid] = BatchReanalyzeItemOutcome(
                media_id=iid,
                outcome="blocked",
                reason_code="provider_batch_reanalysis_not_supported",
                message=f"storage_mode='{item.storage_mode}' is not supported for batch reanalysis.",
            )

    accepted_candidates: list[MediaItem] = accepted_full + accepted_drive

    # 5. All-or-nothing quota reservation across all accepted candidates.
    reservation_map: dict[str, str] = {}  # media_id -> reservation_id
    if _vision_provider and accepted_candidates:
        try:
            for item in accepted_candidates:
                reservation_map[item.id] = await _quota_service.reserve(db, user_id, item.id)
        except QuotaExceededError:
            # Release every reservation acquired so far in this loop.
            for rid in reservation_map.values():
                await _quota_service.release(db, rid)
            # Reclassify all candidates as blocked/quota_exhausted_batch.
            for item in accepted_candidates:
                outcome_map[item.id] = BatchReanalyzeItemOutcome(
                    media_id=item.id,
                    outcome="blocked",
                    reason_code="quota_exhausted_batch",
                    message=(
                        "This item was eligible but the batch was not queued because "
                        "the full set of eligible items exceeded remaining quota."
                    ),
                )
            final_outcomes = [outcome_map[iid] for iid in requested_ids]
            blocked_count = sum(1 for o in final_outcomes if o.outcome == "blocked")
            rejected_count = sum(1 for o in final_outcomes if o.outcome == "rejected")
            raise HTTPException(
                status_code=429,
                detail={
                    "error_code": "quota_exceeded",
                    "message": "Not enough quota to queue all eligible items in this batch.",
                    "request_count": len(requested_ids),
                    "accepted_candidate_count": len(accepted_candidates),
                    "blocked_count": blocked_count,
                    "rejected_count": rejected_count,
                    "queued_count": 0,
                    "outcomes": [o.model_dump() for o in final_outcomes],
                },
            )

    # 6. Create ProcessingJob for each accepted candidate and commit atomically.
    job_map: dict[str, str] = {}  # media_id -> job_id
    try:
        for item in accepted_candidates:
            new_job = ProcessingJob(
                media_item_id=item.id,
                job_type="analysis",
                status="pending",
            )
            db.add(new_job)
            await db.flush()
            job_map[item.id] = new_job.id
            item.status = "uploaded"
        await db.commit()
    except Exception:
        await db.rollback()
        for rid in reservation_map.values():
            await _quota_service.release(db, rid)
        raise

    # 7. Schedule background tasks and record accepted outcomes.
    for item in accepted_full:
        job_id = job_map[item.id]
        background_tasks.add_task(
            analyze_media_item,
            job_id,
            _vision_provider,
            _file_store,
            _indexing_service,
            reservation_map.get(item.id),
        )
        outcome_map[item.id] = BatchReanalyzeItemOutcome(
            media_id=item.id,
            outcome="accepted",
            reason_code="queued",
            message="Item queued for re-analysis.",
            job_id=job_id,
        )

    for item in accepted_drive:
        job_id = job_map[item.id]
        background_tasks.add_task(
            _run_drive_batch_item,
            job_id,
            item.id,
            user_id,
            None,  # hint — not in BatchOperationRequest
            reservation_map.get(item.id),
        )
        outcome_map[item.id] = BatchReanalyzeItemOutcome(
            media_id=item.id,
            outcome="accepted",
            reason_code="queued",
            message="Drive-backed reference item queued for re-analysis.",
            job_id=job_id,
        )

    # 8. Build and return the final structured response.
    final_outcomes = [outcome_map[iid] for iid in requested_ids]
    accepted_count = len(accepted_candidates)
    blocked_count = sum(1 for o in final_outcomes if o.outcome == "blocked")
    rejected_count = sum(1 for o in final_outcomes if o.outcome == "rejected")

    return BatchReanalyzeResponseV2(
        request_count=len(requested_ids),
        accepted_count=accepted_count,
        blocked_count=blocked_count,
        rejected_count=rejected_count,
        queued_count=accepted_count,
        outcomes=final_outcomes,
    )


@router.delete("/media/batch")
async def delete_batch(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> BatchDeleteResponse:
    """Delete multiple media items (max 50). Only the requesting user's items are affected.
    Also removes physical files and vector embeddings (best-effort: logs failures and continues)."""
    import logging
    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id.in_(request.media_ids),
            MediaItem.user_id == user_id,
        )
    )
    items = result.scalars().all()

    deleted_ids: list[str] = []
    for item in items:
        # Delete original file from storage (best-effort, only when present)
        if item.storage_path:
            try:
                await _file_store.delete(item.storage_path)
            except Exception:
                logger.warning("Failed to delete original file for media item %s", item.id, exc_info=True)

        # Delete thumbnail from storage (best-effort, only when present)
        if item.thumbnail_path:
            try:
                await _file_store.delete(item.thumbnail_path)
            except Exception:
                logger.warning("Failed to delete thumbnail for media item %s", item.id, exc_info=True)

        deleted_ids.append(item.id)

    if deleted_ids:
        # Delete child records first to avoid FK constraint violations
        await db.execute(sql_delete(QuotaEvent).where(QuotaEvent.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(CurationScore).where(CurationScore.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(SourceMutationHistory).where(SourceMutationHistory.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(MediaMetadata).where(MediaMetadata.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(ProcessingJob).where(ProcessingJob.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(PreviewAsset).where(PreviewAsset.media_item_id.in_(deleted_ids)))
        # WriteBackOperation has FKs on both media_item_id AND origin_asset_ref_id.
        # Delete by media_item_id first (covers both references for items being deleted).
        await db.execute(sql_delete(WriteBackOperation).where(WriteBackOperation.media_item_id.in_(deleted_ids)))
        # OriginAssetRef must be deleted before SourceObject (FK: origin_asset_refs.source_object_id → source_objects.id)
        await db.execute(sql_delete(OriginAssetRef).where(OriginAssetRef.media_item_id.in_(deleted_ids)))
        # Mark SourceObject as excluded instead of deleting it — so the next sync
        # permanently skips the file and does not reimport it from Drive/S3.
        await db.execute(
            sql_update(SourceObject)
            .where(SourceObject.last_imported_media_item_id.in_(deleted_ids))
            .values(state="excluded", last_imported_media_item_id=None)
        )
        await db.execute(sql_delete(MediaItem).where(MediaItem.id.in_(deleted_ids), MediaItem.user_id == user_id))

    await db.commit()

    # Remove vector embeddings (best-effort)
    if deleted_ids and _indexing_service is not None:
        try:
            _indexing_service.remove_items(deleted_ids)
        except Exception:
            logger.warning("Failed to remove vector embeddings for %d items", len(deleted_ids), exc_info=True)

    return BatchDeleteResponse(deleted=len(deleted_ids), message=f"{len(deleted_ids)} item(s) deleted")


@router.post("/media/tag-batch", status_code=200)
async def tag_batch(
    request: BatchTagRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> BatchTagResponse:
    """Append tags to multiple media items (max 50). Tags are merged with existing ones."""
    result = await db.execute(
        select(MediaMetadata)
        .join(MediaItem, MediaMetadata.media_item_id == MediaItem.id)
        .where(
            MediaItem.id.in_(request.media_ids),
            MediaItem.user_id == user_id,
        )
    )
    metas = result.scalars().all()

    new_tags = [t.lower() for t in request.tags]
    updated_ids: list[str] = []

    for meta in metas:
        existing: list[str] = []
        if meta.tags:
            try:
                existing = json.loads(meta.tags)
            except Exception:
                existing = []
        merged = list(dict.fromkeys(existing + [t for t in new_tags if t not in existing]))
        meta.tags = json.dumps(merged)
        updated_ids.append(meta.media_item_id)

    await db.commit()

    # Re-index updated items (best-effort)
    if updated_ids and _indexing_service is not None:
        for meta in metas:
            try:
                def _parse(val: str | None) -> list:
                    if not val:
                        return []
                    try:
                        return json.loads(val)
                    except Exception:
                        return []

                item_result = await db.execute(
                    select(MediaItem).where(MediaItem.id == meta.media_item_id)
                )
                item = item_result.scalar_one_or_none()
                if item is None:
                    continue

                metadata_result = MediaMetadataResult(
                    title=meta.title,
                    description=meta.description,
                    tags=_parse(meta.tags) or ["untagged"],
                    objects=_parse(meta.objects) or ["unknown"],
                    scenes=_parse(meta.scenes) or ["unknown"],
                    context=meta.context,
                    mood=meta.mood,
                    people=_parse(meta.people),
                    people_count=meta.people_count,
                    orientation=meta.orientation if meta.orientation in ("landscape", "portrait", "square") else "landscape",
                    colors=_parse(meta.colors) or ["unknown"],
                    location_hint=meta.location_hint,
                    quality_notes=meta.quality_notes,
                )
                _indexing_service.index_media_item(
                    meta.media_item_id,
                    user_id,
                    item.original_filename,
                    metadata_result,
                    ocr_text=meta.ocr_text or "",
                )
            except Exception:
                pass  # best-effort

    return BatchTagResponse(updated=len(updated_ids), message=f"{len(updated_ids)} item(s) updated")


@router.patch("/media/{media_id}/analysis", status_code=200)
async def update_analysis(
    media_id: str,
    body: MetadataUpdateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> AnalysisResponse:
    """Manually update analysis metadata fields for a media item."""
    # Verify ownership
    result = await db.execute(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.user_id == user_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    meta_result = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_id)
    )
    meta = meta_result.scalar_one_or_none()
    if meta is None:
        raise HTTPException(status_code=404, detail="No analysis found for this media item")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if isinstance(value, list):
            setattr(meta, key, json.dumps(value))
        else:
            setattr(meta, key, value)

    await db.commit()
    await db.refresh(meta)

    def _parse(val: str | None) -> list:
        if not val:
            return []
        try:
            return json.loads(val)
        except Exception:
            return []

    # Re-index with updated metadata (best-effort)
    if _indexing_service is not None:
        try:
            metadata_result = MediaMetadataResult(
                title=meta.title,
                description=meta.description,
                tags=_parse(meta.tags) or ["untagged"],
                objects=_parse(meta.objects) or ["unknown"],
                scenes=_parse(meta.scenes) or ["unknown"],
                context=meta.context,
                mood=meta.mood,
                people=_parse(meta.people),
                people_count=meta.people_count,
                orientation=meta.orientation if meta.orientation in ("landscape", "portrait", "square") else "landscape",
                colors=_parse(meta.colors) or ["unknown"],
                location_hint=meta.location_hint,
                quality_notes=meta.quality_notes,
            )
            _indexing_service.index_media_item(
                media_id,
                user_id,
                item.original_filename,
                metadata_result,
                ocr_text=meta.ocr_text or "",
            )
        except Exception:
            pass  # best-effort; don't fail the user's save

    # For Drive-backed reference items, re-embed the updated metadata into the source file (best-effort)
    if item.storage_mode == "reference":
        from src.analysis.drive_mutation_service import download_and_embed_drive_metadata
        background_tasks.add_task(download_and_embed_drive_metadata, media_id, user_id)

    metadata_fields = MetadataFields(
        title=meta.title,
        description=meta.description,
        tags=_parse(meta.tags),
        objects=_parse(meta.objects),
        scenes=_parse(meta.scenes),
        context=meta.context,
        mood=meta.mood,
        people=_parse(meta.people),
        people_count=meta.people_count,
        orientation=meta.orientation,
        colors=_parse(meta.colors),
        location_hint=meta.location_hint,
        quality_notes=meta.quality_notes,
        ocr_text=meta.ocr_text,
    )

    return AnalysisResponse(
        media_item_id=media_id,
        status="completed",
        metadata=metadata_fields,
        ai_provider=meta.ai_provider,
        ai_model=meta.ai_model,
        analyzed_at=meta.analyzed_at,
    )
