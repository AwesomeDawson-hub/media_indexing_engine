"""Analysis processor: full pipeline from job pickup to metadata persistence.

Replaces WS-001's placeholder_processor with real AI analysis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.image_prep import prepare_image
from src.analysis.provider import VisionProvider
from src.analysis.schemas import MediaMetadataResult
from src.config import settings
from src.database import async_session
from src.models import MediaItem, MediaMetadata, ProcessingJob
from src.storage.file_store import FileStore

if TYPE_CHECKING:
    from src.search.indexing_service import IndexingService

logger = logging.getLogger(__name__)


def _serialize_metadata(result: MediaMetadataResult) -> dict:
    """Convert MediaMetadataResult fields to DB column values (JSON-serialize lists)."""
    return {
        "title": result.title,
        "description": result.description,
        "tags": json.dumps(result.tags),
        "objects": json.dumps(result.objects),
        "scenes": json.dumps(result.scenes),
        "context": result.context,
        "mood": result.mood,
        "people": json.dumps(result.people),
        "people_count": result.people_count,
        "orientation": result.orientation,
        "colors": json.dumps(result.colors),
        "location_hint": result.location_hint,
        "quality_notes": result.quality_notes,
    }


async def _upsert_metadata(
    db: AsyncSession,
    media_item_id: str,
    result: MediaMetadataResult,
    provider: str,
    model: str,
) -> MediaMetadata:
    """Insert or update the metadata record for a media item."""
    now = datetime.now(timezone.utc)
    fields = _serialize_metadata(result)

    existing = await db.execute(
        select(MediaMetadata).where(MediaMetadata.media_item_id == media_item_id)
    )
    meta = existing.scalar_one_or_none()

    if meta is not None:
        # Update existing (re-analysis)
        for key, value in fields.items():
            setattr(meta, key, value)
        meta.ai_provider = provider
        meta.ai_model = model
        meta.analyzed_at = now
    else:
        # Insert new
        meta = MediaMetadata(
            media_item_id=media_item_id,
            ai_provider=provider,
            ai_model=model,
            analyzed_at=now,
            **fields,
        )
        db.add(meta)

    return meta


async def analyze_media_item(
    job_id: str,
    vision_provider: VisionProvider,
    file_store: FileStore,
    indexing_service: IndexingService | None = None,
) -> None:
    """Background task: run AI analysis for a processing job.

    Full flow: load job → read file → prepare image → call AI → persist metadata → update statuses.
    """
    async with async_session() as db:
        # 1. Load job + media item
        result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            logger.error("Job %s not found", job_id)
            return

        result = await db.execute(
            select(MediaItem).where(MediaItem.id == job.media_item_id)
        )
        media_item = result.scalar_one_or_none()
        if media_item is None:
            logger.error("MediaItem %s not found for job %s", job.media_item_id, job_id)
            job.status = "failed"
            job.error_message = f"MediaItem {job.media_item_id} not found"
            await db.commit()
            return

        # 2. Update job: running
        now = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = now
        job.attempts += 1
        media_item.status = "processing"
        await db.commit()
        logger.info("Job %s started (attempt %d) for media %s", job_id, job.attempts, media_item.id)

        try:
            # 3. Read file from storage
            file_bytes = await file_store.read(media_item.storage_path)

            # 4. Prepare image
            image_base64, media_type = prepare_image(file_bytes, media_item.mime_type)

            # 5. Call vision provider
            metadata_result = await vision_provider.analyze_image(image_base64, media_type)

            # 6. Persist metadata (upsert)
            await _upsert_metadata(
                db, media_item.id, metadata_result,
                provider=settings.analysis.provider,
                model=settings.analysis.model,
            )

            # 6b. Index for search (non-fatal if it fails)
            if indexing_service is not None:
                try:
                    indexing_service.index_media_item(
                        media_item_id=media_item.id,
                        user_id=media_item.user_id,
                        original_filename=media_item.original_filename,
                        metadata_result=metadata_result,
                    )
                except Exception as idx_err:
                    logger.warning("Indexing failed for %s (non-fatal): %s", media_item.id, idx_err)

            # 7. Update statuses: success
            media_item.status = "completed"
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Job %s completed successfully", job_id)

        except Exception as e:
            await db.rollback()

            # Re-fetch after rollback
            result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
            job = result.scalar_one()
            result = await db.execute(select(MediaItem).where(MediaItem.id == job.media_item_id))
            media_item = result.scalar_one()

            error_msg = str(e)
            logger.warning("Job %s failed (attempt %d): %s", job_id, job.attempts, error_msg)

            if job.attempts < settings.processing.max_attempts:
                # Retry: reset to pending
                job.status = "pending"
                job.error_message = error_msg
                media_item.status = "uploaded"
                await db.commit()
                logger.info("Job %s will be retried (attempt %d/%d)", job_id, job.attempts, settings.processing.max_attempts)
            else:
                # Max attempts reached: fail permanently
                job.status = "failed"
                job.error_message = error_msg
                job.completed_at = datetime.now(timezone.utc)
                media_item.status = "error"
                await db.commit()
                logger.error("Job %s failed permanently after %d attempts", job_id, job.attempts)
