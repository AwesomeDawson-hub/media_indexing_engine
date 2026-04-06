"""Upload API endpoints: single and batch file upload."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import UploadResponse, BatchUploadResponse, BatchFileResult
from src.ingestion.upload_service import UploadService
from src.analysis.processor import analyze_media_item
from src.analysis.anthropic_provider import AnthropicVisionProvider, AnalysisError
from src.quota.quota_service import QuotaService, QuotaExceededError, build_quota_exceeded_detail
from src.storage.file_store import get_file_store
from src.search.embedder import Embedder
from src.search.chromadb_store import ChromaDBVectorStore
from src.search.indexing_service import IndexingService
from src.config import settings
from src.models import MediaItem, ProcessingJob, Source

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["upload"])

_file_store = get_file_store(settings.storage)
_upload_service = UploadService(_file_store)
_quota_service = QuotaService()


def _get_vision_provider():
    """Get the vision provider, or None if not configured (e.g., no API key)."""
    try:
        return AnthropicVisionProvider()
    except AnalysisError:
        logger.warning("Vision provider not available (missing API key). Uploads will not be auto-analyzed.")
        return None


def _get_indexing_service():
    """Get the indexing service for search integration."""
    try:
        embedder = Embedder()
        vector_store = ChromaDBVectorStore()
        return IndexingService(embedder, vector_store)
    except Exception:
        logger.warning("Indexing service not available. Search indexing will be skipped.")
        return None


_vision_provider = _get_vision_provider()
_indexing_service = _get_indexing_service()


async def _cleanup_unqueued_upload(db: AsyncSession, media_item_id: str, storage_path: str) -> None:
    """Delete a freshly created upload when analysis cannot be queued."""
    await db.execute(sql_delete(ProcessingJob).where(ProcessingJob.media_item_id == media_item_id))
    await db.execute(sql_delete(MediaItem).where(MediaItem.id == media_item_id))
    await db.commit()

    try:
        await _file_store.delete(storage_path)
    except Exception:
        logger.warning("Failed to delete quota-rejected upload file %s", storage_path, exc_info=True)


_UPLOADS_SOURCE_NAME = "__uploads__"


async def _resolve_source_id(
    db: AsyncSession,
    user_id: str,
    source_id: str | None,
) -> str:
    """Return a source_id scoped to this user.

    If source_id is provided, validates ownership and returns it.
    If source_id is None, returns (creating if necessary) the per-user
    system upload source named '__uploads__'.
    """
    if source_id is None:
        result = await db.execute(
            select(Source).where(
                Source.user_id == user_id,
                Source.name == _UPLOADS_SOURCE_NAME,
                Source.archived_at.is_(None),
            )
        )
        system_source = result.scalar_one_or_none()
        if system_source is None:
            system_source = Source(user_id=user_id, name=_UPLOADS_SOURCE_NAME, source_type="manual")
            db.add(system_source)
            await db.flush()
        return system_source.id

    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.user_id != user_id:
        raise HTTPException(status_code=403, detail="Source does not belong to you")
    return source_id


@router.post("/upload", status_code=201)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    """Upload a single image file."""
    resolved_source_id = await _resolve_source_id(db, user_id, source_id)
    file_bytes = await file.read()
    filename = file.filename or "unnamed"

    result = await _upload_service.process_upload(db, user_id, filename, file_bytes, source_id=resolved_source_id)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # Enqueue background processing for new uploads
    if not result.is_duplicate and result.processing_job_id and _vision_provider:
        try:
            reservation_id = await _quota_service.reserve(db, user_id, result.media_item.id)
        except QuotaExceededError as exc:
            await _cleanup_unqueued_upload(db, result.media_item.id, result.media_item.storage_path)
            raise HTTPException(
                status_code=429,
                detail=build_quota_exceeded_detail(exc),
            )
        background_tasks.add_task(
            analyze_media_item,
            result.processing_job_id,
            _vision_provider,
            _file_store,
            _indexing_service,
            reservation_id,
        )

    item = result.media_item
    if result.is_duplicate:
        return UploadResponse(
            id=item.id,
            content_hash=item.content_hash,
            original_filename=item.original_filename,
            file_size=item.file_size,
            mime_type=item.mime_type,
            status=item.status,
            is_duplicate=True,
            message="File already exists in your library",
            created_at=item.created_at,
        )

    return UploadResponse(
        id=item.id,
        content_hash=item.content_hash,
        original_filename=item.original_filename,
        file_size=item.file_size,
        mime_type=item.mime_type,
        status=item.status,
        is_duplicate=False,
        created_at=item.created_at,
    )


@router.post("/upload/batch")
async def upload_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    source_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> BatchUploadResponse:
    """Upload multiple image files in one request."""
    resolved_source_id = await _resolve_source_id(db, user_id, source_id)
    max_batch = settings.upload.max_batch_size
    if len(files) > max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds maximum of {max_batch} files",
        )

    file_data: list[tuple[str, bytes]] = []
    for f in files:
        file_bytes = await f.read()
        file_data.append((f.filename or "unnamed", file_bytes))

    batch_result = await _upload_service.process_batch(db, user_id, file_data, source_id=resolved_source_id)

    results: list[BatchFileResult] = []
    successful = 0
    duplicates = 0
    failed = 0
    for (filename, _), r in zip(file_data, batch_result.results):
        if not r.success:
            results.append(BatchFileResult(filename=filename, status="error", error=r.error))
            failed += 1
        elif r.is_duplicate:
            results.append(BatchFileResult(
                filename=filename, status="duplicate",
                id=r.media_item.id, content_hash=r.media_item.content_hash,
            ))
            duplicates += 1
        else:
            if r.processing_job_id and _vision_provider:
                try:
                    reservation_id = await _quota_service.reserve(db, user_id, r.media_item.id)
                except QuotaExceededError:
                    await _cleanup_unqueued_upload(db, r.media_item.id, r.media_item.storage_path)
                    results.append(BatchFileResult(
                        filename=filename,
                        status="error",
                        error="Monthly quota exceeded",
                    ))
                    failed += 1
                    continue

                background_tasks.add_task(
                    analyze_media_item,
                    r.processing_job_id,
                    _vision_provider,
                    _file_store,
                    _indexing_service,
                    reservation_id,
                )

            results.append(BatchFileResult(
                filename=filename, status="created",
                id=r.media_item.id, content_hash=r.media_item.content_hash,
            ))
            successful += 1

    return BatchUploadResponse(
        total=batch_result.total,
        successful=successful,
        duplicates=duplicates,
        failed=failed,
        results=results,
    )
