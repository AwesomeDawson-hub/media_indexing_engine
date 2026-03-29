"""Analysis API endpoints: get analysis status and trigger re-analysis."""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import AnalysisResponse, MetadataFields, JobInfo, ReanalyzeResponse
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
