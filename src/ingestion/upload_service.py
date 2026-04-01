"""Upload service: orchestrates validate → hash → dedup → store → DB records."""

import io
from dataclasses import dataclass

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.validation import validate_file, detect_mime_type
from src.ingestion.hashing import compute_sha256
from src.ingestion.dedup import check_duplicate
from src.models import MediaItem, ProcessingJob
from src.storage.file_store import FileStore


@dataclass
class UploadResult:
    success: bool
    is_duplicate: bool = False
    media_item: MediaItem | None = None
    processing_job_id: str | None = None
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

        # 5. Extract image dimensions
        width, height = None, None
        try:
            img = Image.open(io.BytesIO(file_bytes))
            width, height = img.size
        except Exception:
            pass  # Non-image or corrupted — dimensions stay None

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
            await db.commit()
        except Exception:
            await db.rollback()
            # Clean up stored file on DB failure
            await self._file_store.delete(storage_path)
            raise

        return UploadResult(success=True, is_duplicate=False, media_item=media_item, processing_job_id=job_id)

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
