"""Analysis API endpoints: get analysis status and trigger re-analysis."""

import json

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import AnalysisResponse, MetadataFields, JobInfo, ReanalyzeRequest, ReanalyzeResponse, MetadataUpdateRequest, BatchOperationRequest, BatchReanalyzeResponse, BatchDeleteResponse, BatchTagRequest, BatchTagResponse
from src.api.routes.upload import _vision_provider, _file_store, _indexing_service
from src.analysis.processor import analyze_media_item
from src.analysis.schemas import MediaMetadataResult
from src.models import MediaItem, MediaMetadata, ProcessingJob, QuotaEvent
from src.quota.quota_service import QuotaExceededError, QuotaService, build_quota_exceeded_detail

router = APIRouter(prefix="/api/v1", tags=["analysis"])

_quota_service = QuotaService()


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
) -> BatchReanalyzeResponse:
    """Trigger re-analysis for multiple media items (max 50). Only the requesting user's items are affected."""
    import logging
    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id.in_(request.media_ids),
            MediaItem.user_id == user_id,
        )
    )
    items = result.scalars().all()

    eligible_items: list[MediaItem] = []
    for item in items:
        # Skip items with in-progress analysis
        active_result = await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_item_id == item.id,
                ProcessingJob.status.in_(["pending", "running"]),
            )
        )
        if active_result.scalar_one_or_none() is not None:
            logger.info("Skipping %s — analysis already in progress", item.id)
            continue

        eligible_items.append(item)

    reservation_map: dict[str, str] = {}
    if _vision_provider:
        try:
            for item in eligible_items:
                reservation_map[item.id] = await _quota_service.reserve(db, user_id, item.id)
        except QuotaExceededError as exc:
            for reservation_id in reservation_map.values():
                await _quota_service.release(db, reservation_id)
            raise HTTPException(status_code=429, detail=build_quota_exceeded_detail(exc))

    queued = 0
    try:
        for item in eligible_items:
            new_job = ProcessingJob(
                media_item_id=item.id,
                job_type="analysis",
                status="pending",
            )
            db.add(new_job)
            await db.flush()
            job_id = new_job.id

            item.status = "uploaded"

            if _vision_provider:
                background_tasks.add_task(
                    analyze_media_item,
                    job_id,
                    _vision_provider,
                    _file_store,
                    _indexing_service,
                    reservation_map.get(item.id),
                )

            queued += 1

        await db.commit()
    except Exception:
        await db.rollback()
        for reservation_id in reservation_map.values():
            await _quota_service.release(db, reservation_id)
        raise

    return BatchReanalyzeResponse(queued=queued, message=f"{queued} item(s) queued for re-analysis")


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
        # Delete physical file (best-effort)
        try:
            await _file_store.delete(item.storage_path)
        except Exception:
            logger.warning("Failed to delete file for media item %s", item.id, exc_info=True)

        deleted_ids.append(item.id)

    if deleted_ids:
        # Delete child records first to avoid FK constraint violations
        await db.execute(sql_delete(QuotaEvent).where(QuotaEvent.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(MediaMetadata).where(MediaMetadata.media_item_id.in_(deleted_ids)))
        await db.execute(sql_delete(ProcessingJob).where(ProcessingJob.media_item_id.in_(deleted_ids)))
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
async def update_analysis(
    media_id: str,
    body: MetadataUpdateRequest,
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
