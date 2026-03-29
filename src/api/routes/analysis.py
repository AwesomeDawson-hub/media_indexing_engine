"""Analysis API endpoints: get analysis status and trigger re-analysis."""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import AnalysisResponse, MetadataFields, JobInfo, ReanalyzeResponse, BatchOperationRequest, BatchReanalyzeResponse, BatchDeleteResponse
from src.api.routes.upload import _vision_provider, _file_store, _indexing_service
from src.analysis.processor import analyze_media_item
from src.models import MediaItem, MediaMetadata, ProcessingJob

router = APIRouter(prefix="/api/v1", tags=["analysis"])


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

    # Create new processing job
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

    # Enqueue background task
    if _vision_provider:
        background_tasks.add_task(analyze_media_item, job_id, _vision_provider, _file_store, _indexing_service)

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

    queued = 0
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
            background_tasks.add_task(analyze_media_item, job_id, _vision_provider, _file_store, _indexing_service)

        queued += 1

    await db.commit()

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
