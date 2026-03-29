"""Search service: process natural language queries and return ranked, filtered results."""

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import MediaItem, MediaMetadata
from src.search.embedder import Embedder
from src.search.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class SearchFilters:
    """Optional filters applied post-vector-search."""
    has_people: bool | None = None        # True = must have people, False = no people, None = any
    orientation: str | None = None        # "landscape", "portrait", "square", or None
    mood: str | None = None               # filter by mood substring
    mime_type: str | None = None          # e.g. "image/jpeg"
    min_width: int | None = None
    min_height: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    aspect_ratio: str | None = None       # "16:9", "3:2", "4:3", "1:1", "4:5", "2:3", "9:16", "other"
    tags: list[str] = field(default_factory=list)  # must contain ALL these tags
    sort_by: str = "relevance"            # "relevance", "newest", "oldest", "largest", "smallest"


@dataclass
class SearchResultItem:
    media_item_id: str
    original_filename: str
    mime_type: str
    status: str
    created_at: str
    title: str
    description: str
    tags: list[str]
    mood: str
    score: float
    width: int | None = None
    height: int | None = None
    people_count: int | None = None
    orientation: str | None = None


@dataclass
class SearchResult:
    query: str
    total: int
    page: int
    per_page: int
    results: list[SearchResultItem]


class SearchService:
    """Processes natural language queries and returns ranked, filtered results."""

    def __init__(self, embedder: Embedder, vector_store: VectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    async def search(
        self,
        query: str,
        user_id: str,
        db: AsyncSession,
        page: int = 1,
        per_page: int = 20,
        filters: SearchFilters | None = None,
    ) -> SearchResult:
        """Embed query, search vector store, apply filters, join with DB."""
        if filters is None:
            filters = SearchFilters()

        # 1. Embed query and fetch a large pool of candidates
        query_embedding = self._embedder.embed_text(query)
        # Fetch more than needed to account for post-filtering
        fetch_count = max(100, page * per_page * 3)
        hits = self._vector_store.search(query_embedding, user_id, top_k=fetch_count)

        if not hits:
            return SearchResult(query=query, total=0, page=page, per_page=per_page, results=[])

        # 2. Load media items + metadata from DB for ALL candidates
        # Filter by user_id as a defense-in-depth measure (ChromaDB already scopes by user,
        # but DB-level enforcement ensures no cross-user data leaks if the vector store misbehaves)
        hit_ids = [h.media_item_id for h in hits]
        items_result = await db.execute(
            select(MediaItem).where(MediaItem.id.in_(hit_ids), MediaItem.user_id == user_id)
        )
        items_by_id = {item.id: item for item in items_result.scalars().all()}

        meta_result = await db.execute(
            select(MediaMetadata).where(MediaMetadata.media_item_id.in_(hit_ids))
        )
        meta_by_item = {m.media_item_id: m for m in meta_result.scalars().all()}

        # 3. Build full result list with all fields
        all_results: list[SearchResultItem] = []
        for hit in hits:
            item = items_by_id.get(hit.media_item_id)
            meta = meta_by_item.get(hit.media_item_id)
            if item is None:
                continue

            tags = json.loads(meta.tags) if meta else []
            mood = meta.mood if meta else ""
            people_count = meta.people_count if meta else None
            item_orientation = meta.orientation if meta else None

            all_results.append(SearchResultItem(
                media_item_id=item.id,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                status=item.status,
                created_at=item.created_at.isoformat(),
                title=meta.title if meta else hit.title or "",
                description=meta.description if meta else "",
                tags=tags,
                mood=mood,
                score=hit.score,
                width=item.width,
                height=item.height,
                people_count=people_count,
                orientation=item_orientation,
            ))

        # 4. Apply filters
        filtered = self._apply_filters(all_results, filters)

        # 5. Apply sorting
        filtered = self._apply_sort(filtered, filters.sort_by)

        # 6. Paginate
        total = len(filtered)
        start = (page - 1) * per_page
        page_results = filtered[start : start + per_page]

        return SearchResult(
            query=query,
            total=total,
            page=page,
            per_page=per_page,
            results=page_results,
        )

    def _apply_filters(
        self, results: list[SearchResultItem], filters: SearchFilters
    ) -> list[SearchResultItem]:
        filtered = results

        if filters.has_people is not None:
            if filters.has_people:
                filtered = [r for r in filtered if r.people_count and r.people_count > 0]
            else:
                filtered = [r for r in filtered if r.people_count is not None and r.people_count == 0]

        if filters.orientation:
            filtered = [r for r in filtered if r.orientation == filters.orientation]

        if filters.mood:
            mood_lower = filters.mood.lower()
            filtered = [r for r in filtered if mood_lower in r.mood.lower()]

        if filters.mime_type:
            filtered = [r for r in filtered if r.mime_type == filters.mime_type]

        if filters.min_width:
            filtered = [r for r in filtered if r.width and r.width >= filters.min_width]

        if filters.max_width:
            filtered = [r for r in filtered if r.width and r.width <= filters.max_width]

        if filters.min_height:
            filtered = [r for r in filtered if r.height and r.height >= filters.min_height]

        if filters.max_height:
            filtered = [r for r in filtered if r.height and r.height <= filters.max_height]

        if filters.aspect_ratio:
            filtered = self._filter_aspect_ratio(filtered, filters.aspect_ratio)

        if filters.tags:
            filter_tags = {t.lower() for t in filters.tags}
            filtered = [r for r in filtered if filter_tags.issubset({t.lower() for t in r.tags})]

        return filtered

    # Standard aspect ratios with tolerance (±10%)
    _ASPECT_RATIOS: dict[str, float] = {
        "16:9": 16 / 9,
        "3:2": 3 / 2,
        "4:3": 4 / 3,
        "1:1": 1.0,
        "4:5": 4 / 5,
        "2:3": 2 / 3,
        "9:16": 9 / 16,
    }
    _TOLERANCE = 0.10

    def _filter_aspect_ratio(
        self, results: list[SearchResultItem], ratio: str
    ) -> list[SearchResultItem]:
        if ratio == "other":
            # "other" = doesn't match any standard ratio
            return [r for r in results if r.width and r.height and not self._matches_any_standard(r.width, r.height)]

        target = self._ASPECT_RATIOS.get(ratio)
        if target is None:
            return results

        out = []
        for r in results:
            if not r.width or not r.height:
                continue
            ar = r.width / r.height
            if abs(ar - target) / target <= self._TOLERANCE:
                out.append(r)
        return out

    def _matches_any_standard(self, width: int, height: int) -> bool:
        ar = width / height
        for target in self._ASPECT_RATIOS.values():
            if abs(ar - target) / target <= self._TOLERANCE:
                return True
        return False

    def _apply_sort(
        self, results: list[SearchResultItem], sort_by: str
    ) -> list[SearchResultItem]:
        if sort_by == "newest":
            return sorted(results, key=lambda r: r.created_at, reverse=True)
        elif sort_by == "oldest":
            return sorted(results, key=lambda r: r.created_at)
        elif sort_by == "largest":
            return sorted(results, key=lambda r: (r.width or 0) * (r.height or 0), reverse=True)
        elif sort_by == "smallest":
            return sorted(results, key=lambda r: (r.width or 0) * (r.height or 0))
        # default: relevance (already sorted by score from vector search)
        return results
