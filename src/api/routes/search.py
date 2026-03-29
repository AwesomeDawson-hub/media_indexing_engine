"""Search API endpoint: natural language media search with filters."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import (
    SearchResponse, SearchResultItemResponse, SearchMediaItem, SearchMetadataSubset,
)
from src.api.routes.upload import _indexing_service
from src.search.search_service import SearchService, SearchFilters

router = APIRouter(prefix="/api/v1", tags=["search"])

# Build search service from the same embedder/store as the indexing service
_search_service: SearchService | None = None
if _indexing_service is not None:
    _search_service = SearchService(
        embedder=_indexing_service._embedder,
        vector_store=_indexing_service._vector_store,
    )


@router.get("/search")
async def search_media(
    q: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    # Filters
    has_people: bool | None = Query(None, description="true=with people, false=no people"),
    orientation: str | None = Query(None, description="landscape, portrait, or square"),
    mood: str | None = Query(None, description="Filter by mood (substring match)"),
    mime_type: str | None = Query(None, description="e.g. image/jpeg, image/webp"),
    min_width: int | None = Query(None, ge=1),
    max_width: int | None = Query(None, ge=1),
    min_height: int | None = Query(None, ge=1),
    max_height: int | None = Query(None, ge=1),
    aspect_ratio: str | None = Query(None, description="wide, tall, or square"),
    tags: str | None = Query(None, description="Comma-separated required tags"),
    sort_by: str = Query("relevance", description="relevance, newest, oldest, largest, smallest"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SearchResponse:
    """Search media items using natural language with optional filters."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    if _search_service is None:
        raise HTTPException(status_code=503, detail="Search service not available")

    filters = SearchFilters(
        has_people=has_people,
        orientation=orientation,
        mood=mood,
        mime_type=mime_type,
        min_width=min_width,
        max_width=max_width,
        min_height=min_height,
        max_height=max_height,
        aspect_ratio=aspect_ratio,
        tags=[t.strip() for t in tags.split(",") if t.strip()] if tags else [],
        sort_by=sort_by,
    )

    result = await _search_service.search(q.strip(), user_id, db, page, per_page, filters)

    return SearchResponse(
        query=result.query,
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        results=[
            SearchResultItemResponse(
                media_item=SearchMediaItem(
                    id=r.media_item_id,
                    original_filename=r.original_filename,
                    mime_type=r.mime_type,
                    status=r.status,
                    width=r.width,
                    height=r.height,
                    created_at=r.created_at,
                ),
                metadata=SearchMetadataSubset(
                    title=r.title,
                    description=r.description,
                    tags=r.tags,
                    mood=r.mood,
                ),
                score=r.score,
            )
            for r in result.results
        ],
    )
