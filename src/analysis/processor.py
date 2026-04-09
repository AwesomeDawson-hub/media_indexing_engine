"""Analysis processor: full pipeline from job pickup to metadata persistence.

Replaces WS-001's placeholder_processor with real AI analysis.
"""

from __future__ import annotations

import asyncio
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
from src.models import MediaItem, MediaMetadata, ProcessingJob, Source, SourceConnector, SourceObject
from src.ocr.ocr_service import extract_text as ocr_extract_text
from src.quota.quota_service import QuotaService
from src.storage.file_store import FileStore
from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

if TYPE_CHECKING:
    from src.search.indexing_service import IndexingService

logger = logging.getLogger(__name__)
_analysis_semaphore = asyncio.Semaphore(max(1, settings.analysis.max_concurrent))
_quota_service = QuotaService()

# Source classification constants (P8-002)
_UPLOADS_SOURCE_NAME = "__uploads__"
SOURCE_TYPE_LOCAL_FOLDER = "local_folder"


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
    ocr_text: str = "",
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
        meta.ocr_text = ocr_text or None
    else:
        # Insert new
        meta = MediaMetadata(
            media_item_id=media_item_id,
            ai_provider=provider,
            ai_model=model,
            analyzed_at=now,
            ocr_text=ocr_text or None,
            **fields,
        )
        db.add(meta)

    return meta


async def _attempt_preview_pivot(
    db: AsyncSession,
    media_item: MediaItem,
    file_store: FileStore,
) -> None:
    """Post-success pivot: delete retained original and transition to preview_only.

    Eligibility is derived entirely from persisted DB state so this function is
    replay-safe across process restarts.  Deletion failure is non-fatal — the item
    stays in a consistent `full` state.

    Eligible sources (P8-002 Decision 5):
    - Connector-backed sources where a SourceObject already links this media_item.
    - Local working-folder sources (source_type='local_folder') where
      source_file_fingerprint is persisted (the re-match anchor).

    Never eligible:
    - The automatic __uploads__ system source for binary browser uploads.
    - Any source not covered by the two cases above.
    """
    # Guard: already pivoted or nothing to delete
    if media_item.storage_mode != "full":
        return
    if not media_item.storage_path:
        return
    if not media_item.thumbnail_path:
        logger.debug(
            "Preview pivot skipped for media_item=%s: no thumbnail_path", media_item.id
        )
        return
    if not media_item.source_id:
        return  # no source — not eligible

    # Load source
    source_result = await db.execute(
        select(Source).where(Source.id == media_item.source_id)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        return

    # __uploads__ system source is never eligible (Decision 1)
    if source.name == _UPLOADS_SOURCE_NAME:
        return

    # Determine eligibility from persisted source contract
    # Connector items: require a committed SourceObject pointing to this media_item (Decision 9)
    connector_result = await db.execute(
        select(SourceConnector).where(SourceConnector.source_id == source.id)
    )
    has_connector = connector_result.scalar_one_or_none() is not None

    if has_connector:
        so_result = await db.execute(
            select(SourceObject).where(
                SourceObject.last_imported_media_item_id == media_item.id,
                SourceObject.source_id == media_item.source_id,
            )
        )
        if so_result.scalar_one_or_none() is None:
            logger.debug(
                "Preview pivot skipped for media_item=%s: no SourceObject found for source=%s",
                media_item.id,
                media_item.source_id,
            )
            return
    elif source.source_type == SOURCE_TYPE_LOCAL_FOLDER:
        # Local working-folder: source_file_fingerprint is the durable re-match anchor
        if not media_item.source_file_fingerprint:
            logger.debug(
                "Preview pivot skipped for media_item=%s: no source_file_fingerprint",
                media_item.id,
            )
            return
    else:
        # Unknown source type or plain manual source — not eligible
        return

    # Attempt deletion (non-fatal on failure per Decision 8)
    try:
        await file_store.delete(media_item.storage_path)
    except Exception as exc:
        logger.warning(
            "Preview pivot: original deletion failed for media_item=%s, staying full: %s",
            media_item.id,
            exc,
        )
        return

    media_item.storage_path = None
    media_item.storage_mode = "preview_only"
    await db.commit()
    logger.info(
        "Preview pivot complete: media_item=%s is now preview_only (source=%s)",
        media_item.id,
        media_item.source_id,
    )


async def analyze_media_item(
    job_id: str,
    vision_provider: VisionProvider,
    file_store: FileStore,
    indexing_service: IndexingService | None = None,
    reservation_id: str | None = None,
    hint: str | None = None,
) -> None:
    """Background task: run AI analysis for a processing job.

    Full flow: load job → read file → prepare image → call AI → persist metadata → update statuses.
    If reservation_id is provided, marks the quota event consumed on success or released on permanent failure.
    """
    max_attempts = settings.processing.max_attempts

    while True:
        retry_delay = 0.0

        async with async_session() as db:
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

            if job.status == "completed":
                return

            # P9-002: fail-fast guard — analyze_media_item requires a retained original.
            # reference and preview_only items must not reach this path; they have no
            # storage_path and cannot be re-analysed from app storage.
            if media_item.storage_mode != "full" or not media_item.storage_path:
                logger.error(
                    "Job %s: analyze_media_item called for non-full item %s "
                    "(storage_mode=%r, storage_path=%r) — failing immediately",
                    job_id,
                    media_item.id,
                    media_item.storage_mode,
                    media_item.storage_path,
                )
                job.status = "failed"
                job.error_message = (
                    f"Original not in app storage (storage_mode={media_item.storage_mode!r}). "
                    "Use analyze_connector_item for reference-mode items."
                )
                job.completed_at = datetime.now(timezone.utc)
                media_item.status = "error"
                await db.commit()
                if reservation_id:
                    async with async_session() as quota_db:
                        await _quota_service.release(quota_db, reservation_id)
                return

            now = datetime.now(timezone.utc)
            job.status = "running"
            job.started_at = now
            job.attempts += 1
            media_item.status = "processing"
            await db.commit()
            logger.info("Job %s started (attempt %d) for media %s", job_id, job.attempts, media_item.id)

            try:
                file_bytes = await file_store.read(media_item.storage_path)
                image_base64, media_type = prepare_image(file_bytes, media_item.mime_type)

                async with _analysis_semaphore:
                    metadata_result = await vision_provider.analyze_image(image_base64, media_type, hint=hint)

                ocr_text = ocr_extract_text(file_bytes, media_item.mime_type)
                if ocr_text:
                    logger.info("OCR extracted %d chars for media %s", len(ocr_text), media_item.id)

                await _upsert_metadata(
                    db, media_item.id, metadata_result,
                    provider=settings.analysis.provider,
                    model=settings.analysis.model,
                    ocr_text=ocr_text,
                )

                if indexing_service is not None:
                    try:
                        indexing_service.index_media_item(
                            media_item_id=media_item.id,
                            user_id=media_item.user_id,
                            original_filename=media_item.original_filename,
                            metadata_result=metadata_result,
                            ocr_text=ocr_text,
                        )
                    except Exception as idx_err:
                        logger.warning("Indexing failed for %s (non-fatal): %s", media_item.id, idx_err)

                # Attempt Drive source mutation (rename) immediately after analysis (P7-004).
                # This is non-fatal: if it fails the item is marked blocked/pending, but analysis
                # is still recorded as successful.
                try:
                    await attempt_drive_rename_after_analysis(db, media_item)
                except Exception as mut_err:
                    logger.warning(
                        "Drive mutation step raised unexpectedly for %s (non-fatal): %s",
                        media_item.id, mut_err,
                    )

                media_item.status = "completed"
                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("Job %s completed successfully", job_id)

                if reservation_id:
                    async with async_session() as quota_db:
                        await _quota_service.consume(quota_db, reservation_id)

                # P8-002: attempt preview-only pivot from persisted source state.
                await _attempt_preview_pivot(db, media_item, file_store)

                return

            except Exception as e:
                await db.rollback()

                result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
                job = result.scalar_one()
                result = await db.execute(select(MediaItem).where(MediaItem.id == job.media_item_id))
                media_item = result.scalar_one()

                error_msg = str(e)
                logger.warning("Job %s failed (attempt %d): %s", job_id, job.attempts, error_msg)

                if job.attempts < max_attempts:
                    job.status = "pending"
                    job.error_message = error_msg
                    media_item.status = "uploaded"
                    await db.commit()
                    retry_delay = min(2 ** (job.attempts - 1), 30)
                    logger.info(
                        "Job %s will be retried in %.1fs (attempt %d/%d)",
                        job_id,
                        retry_delay,
                        job.attempts,
                        max_attempts,
                    )
                else:
                    job.status = "failed"
                    job.error_message = error_msg
                    job.completed_at = datetime.now(timezone.utc)
                    media_item.status = "error"
                    await db.commit()
                    logger.error("Job %s failed permanently after %d attempts", job_id, job.attempts)

                    if reservation_id:
                        async with async_session() as quota_db:
                            await _quota_service.release(quota_db, reservation_id)

                    return

        if retry_delay <= 0:
            return

        await asyncio.sleep(retry_delay)


async def analyze_connector_item(
    job_id: str,
    file_bytes: bytes,
    vision_provider: VisionProvider,
    file_store: FileStore,
    indexing_service: "IndexingService | None" = None,
    reservation_id: str | None = None,
    hint: str | None = None,
) -> None:
    """Synchronous single-attempt analysis for connector-ingested reference-mode items.

    Uses caller-provided bytes directly — no file_store.read() and no storage_path
    dependency.  Does not call _attempt_preview_pivot because the item was created
    in storage_mode='reference' and no original was ever stored.

    No retry loop (ADR-031: first zero-transient slice; long-term retry contract is
    source re-fetch from the connector, not app-retained originals).
    """
    async with async_session() as db:
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if job is None:
            logger.error("analyze_connector_item: job %s not found", job_id)
            return

        item_result = await db.execute(
            select(MediaItem).where(MediaItem.id == job.media_item_id)
        )
        media_item = item_result.scalar_one_or_none()
        if media_item is None:
            logger.error(
                "analyze_connector_item: MediaItem %s not found for job %s",
                job.media_item_id,
                job_id,
            )
            job.status = "failed"
            job.error_message = f"MediaItem {job.media_item_id} not found"
            await db.commit()
            return

        if job.status == "completed":
            return

        now = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = now
        job.attempts += 1
        media_item.status = "processing"
        await db.commit()
        logger.info(
            "analyze_connector_item: job %s started for reference item %s",
            job_id,
            media_item.id,
        )

        try:
            image_base64, media_type = prepare_image(file_bytes, media_item.mime_type)

            async with _analysis_semaphore:
                metadata_result = await vision_provider.analyze_image(
                    image_base64, media_type, hint=hint
                )

            ocr_text = ocr_extract_text(file_bytes, media_item.mime_type)
            if ocr_text:
                logger.info(
                    "OCR extracted %d chars for connector item %s",
                    len(ocr_text),
                    media_item.id,
                )

            await _upsert_metadata(
                db,
                media_item.id,
                metadata_result,
                provider=settings.analysis.provider,
                model=settings.analysis.model,
                ocr_text=ocr_text,
            )

            if indexing_service is not None:
                try:
                    indexing_service.index_media_item(
                        media_item_id=media_item.id,
                        user_id=media_item.user_id,
                        original_filename=media_item.original_filename,
                        metadata_result=metadata_result,
                        ocr_text=ocr_text,
                    )
                except Exception as idx_err:
                    logger.warning(
                        "Indexing failed for connector item %s (non-fatal): %s",
                        media_item.id,
                        idx_err,
                    )

            try:
                await attempt_drive_rename_after_analysis(db, media_item)
            except Exception as mut_err:
                logger.warning(
                    "Drive mutation raised unexpectedly for connector item %s (non-fatal): %s",
                    media_item.id,
                    mut_err,
                )

            media_item.status = "completed"
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "analyze_connector_item: job %s completed for reference item %s",
                job_id,
                media_item.id,
            )

            if reservation_id:
                async with async_session() as quota_db:
                    await _quota_service.consume(quota_db, reservation_id)

            # No _attempt_preview_pivot: item is storage_mode='reference',
            # the original was never stored in app storage.

        except Exception as exc:
            await db.rollback()
            logger.warning(
                "analyze_connector_item: job %s failed (non-retryable per ADR-031): %s",
                job_id,
                exc,
            )
            # Re-query after rollback to get fresh DB state
            job_r = await db.execute(
                select(ProcessingJob).where(ProcessingJob.id == job_id)
            )
            job = job_r.scalar_one()
            item_r = await db.execute(
                select(MediaItem).where(MediaItem.id == job.media_item_id)
            )
            media_item = item_r.scalar_one()

            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            media_item.status = "error"
            await db.commit()

            if reservation_id:
                async with async_session() as quota_db:
                    await _quota_service.release(quota_db, reservation_id)
