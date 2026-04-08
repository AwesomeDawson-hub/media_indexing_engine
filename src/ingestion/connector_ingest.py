"""Zero-transient connector ingestion (P9-001 / ADR-031).

Processes connector-downloaded files through the full preparation pipeline
(validate → hash → dedup → MIME → dimensions → thumbnail → DB records → pHash)
without ever writing the full original to app storage.

The MediaItem is created with storage_mode='reference', storage_path=None.
Only the derived thumbnail is persisted to app storage.

The caller is responsible for passing file_bytes directly to the analysis
step via analyze_connector_item() in src.analysis.processor.
"""

import io
import logging

from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.curation.phash_service import PHASH_VERSION, compute_phash, phash_timestamp
from src.ingestion.dedup import check_duplicate
from src.ingestion.hashing import compute_sha256
from src.ingestion.upload_service import UploadResult, _generate_thumbnail
from src.ingestion.validation import detect_mime_type, validate_file
from src.models import MediaItem, ProcessingJob
from src.storage.file_store import FileStore

logger = logging.getLogger(__name__)


async def process_connector_import(
    db: AsyncSession,
    user_id: str,
    filename: str,
    file_bytes: bytes,
    source_id: str,
    file_store: FileStore,
) -> UploadResult:
    """Import a connector-downloaded file without ever storing the full original.

    Pipeline:
      validate → hash → dedup → MIME → dimensions → thumbnail → DB records → pHash

    The original bytes are never written to app storage.  Only the derived
    thumbnail is persisted.  MediaItem is created with:
        storage_mode = 'reference'
        storage_path = None

    Returns an UploadResult compatible with the existing upload-service contract
    so that sync_service can handle the result uniformly.
    """
    # 1. Validate
    validation = validate_file(filename, file_bytes)
    if not validation.valid:
        return UploadResult(success=False, error=validation.error)

    # 2. Content hash
    content_hash = compute_sha256(file_bytes)

    # 3. Duplicate check
    existing = await check_duplicate(db, user_id, content_hash)
    if existing is not None:
        return UploadResult(success=True, is_duplicate=True, media_item=existing)

    # 4. MIME type
    mime_type = detect_mime_type(file_bytes) or "application/octet-stream"

    # 5. Image dimensions (non-fatal)
    width: int | None = None
    height: int | None = None
    try:
        img = Image.open(io.BytesIO(file_bytes))
        width, height = img.size
    except Exception:
        pass

    # 6. Thumbnail — only derivative we persist to app storage (non-fatal)
    thumbnail_path: str | None = None
    try:
        thumb_bytes = _generate_thumbnail(file_bytes)
        thumbnail_path = await file_store.save_thumbnail(user_id, content_hash, thumb_bytes)
    except Exception as exc:
        logger.warning(
            "Thumbnail generation failed for connector import user=%s hash=%s: %s",
            user_id,
            content_hash,
            exc,
        )

    # 7. DB records — reference mode: storage_path stays NULL, no original retained
    job_id: str | None = None
    media_item: MediaItem | None = None
    try:
        media_item = MediaItem(
            user_id=user_id,
            content_hash=content_hash,
            original_filename=filename,
            file_size=len(file_bytes),
            mime_type=mime_type,
            storage_path=None,
            storage_mode="reference",
            thumbnail_path=thumbnail_path,
            status="uploaded",
            width=width,
            height=height,
            source_id=source_id,
        )
        db.add(media_item)
        await db.flush()

        processing_job = ProcessingJob(
            media_item_id=media_item.id,
            job_type="analysis",
            status="pending",
        )
        db.add(processing_job)
        await db.flush()
        job_id = processing_job.id
        await db.commit()

    except IntegrityError:
        # Race condition: another request inserted the same (user_id, content_hash).
        # Clean up thumbnail and return the winner.
        await db.rollback()
        if thumbnail_path:
            try:
                await file_store.delete(thumbnail_path)
            except Exception:
                pass
        existing = await check_duplicate(db, user_id, content_hash)
        if existing is not None:
            return UploadResult(success=True, is_duplicate=True, media_item=existing)
        raise

    except Exception:
        await db.rollback()
        if thumbnail_path:
            try:
                await file_store.delete(thumbnail_path)
            except Exception:
                pass
        raise

    # 8. Perceptual hash — non-fatal
    try:
        phash = compute_phash(file_bytes, mime_type)
        if phash is not None:
            media_item.perceptual_hash = phash
            media_item.phash_version = PHASH_VERSION
            media_item.phash_computed_at = phash_timestamp()
            await db.commit()
    except Exception as exc:
        logger.warning(
            "pHash computation failed for connector import media_item=%s: %s",
            media_item.id,
            exc,
        )

    return UploadResult(
        success=True,
        is_duplicate=False,
        media_item=media_item,
        processing_job_id=job_id,
        thumbnail_path=thumbnail_path,
    )
