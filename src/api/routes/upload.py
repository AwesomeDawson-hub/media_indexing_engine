"""Upload API endpoints: single and batch file upload."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import UploadResponse, BatchUploadResponse, BatchFileResult
from src.ingestion.upload_service import UploadService
from src.analysis.processor import analyze_media_item
from src.analysis.anthropic_provider import AnthropicVisionProvider, AnalysisError
from src.storage.file_store import LocalFileStore
from src.search.embedder import Embedder
from src.search.chromadb_store import ChromaDBVectorStore
from src.search.indexing_service import IndexingService
from src.config import settings

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["upload"])

_file_store = LocalFileStore(settings.storage.local_path)
_upload_service = UploadService(_file_store)


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


@router.post("/upload", status_code=201)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    """Upload a single image file."""
    file_bytes = await file.read()
    filename = file.filename or "unnamed"

    result = await _upload_service.process_upload(db, user_id, filename, file_bytes)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # Enqueue background processing for new uploads
    if not result.is_duplicate and result.processing_job_id and _vision_provider:
        background_tasks.add_task(analyze_media_item, result.processing_job_id, _vision_provider, _file_store, _indexing_service)

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
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> BatchUploadResponse:
    """Upload multiple image files in one request."""
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

    batch_result = await _upload_service.process_batch(db, user_id, file_data)

    # Enqueue background processing for new uploads
    for r in batch_result.results:
        if r.success and not r.is_duplicate and r.processing_job_id and _vision_provider:
            background_tasks.add_task(analyze_media_item, r.processing_job_id, _vision_provider, _file_store)

    results: list[BatchFileResult] = []
    for (filename, _), r in zip(file_data, batch_result.results):
        if not r.success:
            results.append(BatchFileResult(filename=filename, status="error", error=r.error))
        elif r.is_duplicate:
            results.append(BatchFileResult(
                filename=filename, status="duplicate",
                id=r.media_item.id, content_hash=r.media_item.content_hash,
            ))
        else:
            results.append(BatchFileResult(
                filename=filename, status="created",
                id=r.media_item.id, content_hash=r.media_item.content_hash,
            ))

    return BatchUploadResponse(
        total=batch_result.total,
        successful=batch_result.successful,
        duplicates=batch_result.duplicates,
        failed=batch_result.failed,
        results=results,
    )
