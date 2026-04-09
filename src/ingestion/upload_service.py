"""Upload service: orchestrates validate → hash → dedup → store → DB records."""

import io
import logging
from dataclasses import dataclass, field

from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.curation.phash_service import compute_phash, PHASH_VERSION, phash_timestamp
from src.ingestion.validation import validate_file, detect_mime_type
from src.ingestion.hashing import compute_sha256
from src.ingestion.dedup import check_duplicate
from src.models import MediaItem, OriginAssetRef, PreviewAsset, ProcessingJob
from src.storage.file_store import FileStore

logger = logging.getLogger(__name__)

# Thumbnail generation constants (ADR-028 / P8-001)
_THUMB_MAX_PX = 800
_THUMB_QUALITY = 85


def _generate_thumbnail(file_bytes: bytes) -> bytes:
    """Generate an 800px max-dimension JPEG thumbnail and return the bytes.

    Raises on unsupported image types or corrupted input.
    """
    img = Image.open(io.BytesIO(file_bytes))
    img = img.convert("RGB")
    img.thumbnail((_THUMB_MAX_PX, _THUMB_MAX_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_THUMB_QUALITY)
    return buf.getvalue()


@dataclass
class UploadResult:
    success: bool
    is_duplicate: bool = False
    media_item: MediaItem | None = None
    processing_job_id: str | None = None
    thumbnail_path: str | None = None
    error: str | None = None


@dataclass
class BatchUploadResult:
    total: int
    successful: int
    duplicates: int
    failed: int
    results: list[UploadResult]


class UploadService:
    def __init__(self, file_store: FileStore) -> None:
        self._file_store = file_store

    async def process_upload(
        self,
        db: AsyncSession,
        user_id: str,
        filename: str,
        file_bytes: bytes,
        source_id: str | None = None,
    ) -> UploadResult:
        """Process a single file upload through the full pipeline."""
        # 1. Validate
        validation = validate_file(filename, file_bytes)
        if not validation.valid:
            return UploadResult(success=False, error=validation.error)

        # 2. Hash
        content_hash = compute_sha256(file_bytes)

        # 3. Dedup check
        existing = await check_duplicate(db, user_id, content_hash)
        if existing is not None:
            return UploadResult(success=True, is_duplicate=True, media_item=existing)

        # 4. Detect MIME type
        mime_type = detect_mime_type(file_bytes) or "application/octet-stream"

        # 5. Extract image dimensions + generate thumbnail
        width, height = None, None
        thumbnail_path: str | None = None
        try:
            img = Image.open(io.BytesIO(file_bytes))
            width, height = img.size
        except Exception:
            pass  # Non-image or corrupted — dimensions stay None

        try:
            thumb_bytes = _generate_thumbnail(file_bytes)
            thumbnail_path = await self._file_store.save_thumbnail(user_id, content_hash, thumb_bytes)
        except Exception as exc:
            logger.warning(
                "Thumbnail generation failed for user=%s hash=%s: %s",
                user_id,
                content_hash,
                exc,
            )
            thumbnail_path = None

        # 6. Store file
        storage_path = await self._file_store.save(user_id, content_hash, filename, file_bytes)

        # 7. Create DB records (media_item + processing_job) in one transaction
        try:
            media_item = MediaItem(
                user_id=user_id,
                content_hash=content_hash,
                original_filename=filename,
                file_size=len(file_bytes),
                mime_type=mime_type,
                storage_path=storage_path,
                storage_mode="full",
                thumbnail_path=thumbnail_path,
                status="uploaded",
                width=width,
                height=height,
                source_id=source_id,
            )
            db.add(media_item)
            await db.flush()  # Get the generated ID

            processing_job = ProcessingJob(
                media_item_id=media_item.id,
                job_type="analysis",
                status="pending",
            )
            db.add(processing_job)
            await db.flush()
            job_id = processing_job.id
            db.add(OriginAssetRef(
                media_item_id=media_item.id,
                user_id=user_id,
                source_id=source_id,
                source_object_id=None,
                provider_type="app_upload",
                provider_object_id=None,
                locator_snapshot=None,
                revision_marker=None,
                app_storage_path=storage_path,
                local_file_fingerprint=None,
            ))
            if thumbnail_path:
                db.add(PreviewAsset(
                    media_item_id=media_item.id,
                    user_id=user_id,
                    variant_type="thumbnail",
                    storage_path=thumbnail_path,
                    mime_type="image/jpeg",
                ))
            await db.commit()
        except IntegrityError:
            # Concurrent upload of identical content beat us to the commit.
            # Roll back, clean up the stored file (and thumbnail), then re-query for the winner.
            await db.rollback()
            await self._file_store.delete(storage_path)
            if thumbnail_path:
                await self._file_store.delete(thumbnail_path)
            existing = await check_duplicate(db, user_id, content_hash)
            if existing is not None:
                return UploadResult(success=True, is_duplicate=True, media_item=existing)
            # Should not happen; re-raise if we still can't find the item.
            raise
        except Exception:
            await db.rollback()
            # Clean up stored file (and thumbnail) on DB failure
            await self._file_store.delete(storage_path)
            if thumbnail_path:
                await self._file_store.delete(thumbnail_path)
            raise

        # 8. Compute perceptual hash — non-fatal; failure leaves phash columns NULL
        try:
            phash = compute_phash(file_bytes, mime_type)
            if phash is not None:
                media_item.perceptual_hash = phash
                media_item.phash_version = PHASH_VERSION
                media_item.phash_computed_at = phash_timestamp()
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "pHash computation failed for media_item=%s (mime=%s): %s",
                media_item.id,
                mime_type,
                exc,
            )

        return UploadResult(
            success=True,
            is_duplicate=False,
            media_item=media_item,
            processing_job_id=job_id,
            thumbnail_path=thumbnail_path,
        )

    async def process_batch(
        self,
        db: AsyncSession,
        user_id: str,
        files: list[tuple[str, bytes]],
        source_id: str | None = None,
    ) -> BatchUploadResult:
        """Process multiple files sequentially. Each file is independent.

        Args:
            files: List of (filename, file_bytes) tuples.
        """
        results: list[UploadResult] = []
        successful = 0
        duplicates = 0
        failed = 0

        for filename, file_bytes in files:
            result = await self.process_upload(db, user_id, filename, file_bytes, source_id=source_id)
            results.append(result)

            if not result.success:
                failed += 1
            elif result.is_duplicate:
                duplicates += 1
            else:
                successful += 1

        return BatchUploadResult(
            total=len(files),
            successful=successful,
            duplicates=duplicates,
            failed=failed,
            results=results,
        )
