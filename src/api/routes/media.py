"""Media item API endpoints: list, detail, and file serving."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import MediaItemResponse, PaginatedResponse
from src.api.routes.upload import _file_store
from src.models import MediaItem, MediaMetadata

router = APIRouter(prefix="/api/v1", tags=["media"])

# Standard aspect ratios with ±10% tolerance
_ASPECT_RATIOS: dict[str, float] = {
    "16:9": 16 / 9,
    "3:2": 3 / 2,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "4:5": 4 / 5,
    "2:3": 2 / 3,
    "9:16": 9 / 16,
}
_ASPECT_TOLERANCE = 0.10


async def _get_display_names(
    db: AsyncSession,
    item_ids: list[str],
) -> dict[str, str]:
    if not item_ids:
        return {}
    result = await db.execute(
        select(MediaMetadata.media_item_id, MediaMetadata.title)
        .where(MediaMetadata.media_item_id.in_(item_ids))
    )
    return {
        media_item_id: title
        for media_item_id, title in result.all()
        if title
    }


async def _build_media_item_responses(
    db: AsyncSession,
    items: list[MediaItem],
) -> list[MediaItemResponse]:
    display_names = await _get_display_names(db, [item.id for item in items])
    return [
        MediaItemResponse(
            id=item.id,
            content_hash=item.content_hash,
            original_filename=item.original_filename,
            display_name=display_names.get(item.id, item.original_filename),
            file_size=item.file_size,
            mime_type=item.mime_type,
            status=item.status,
            width=item.width,
            height=item.height,
            source_id=item.source_id,
            created_at=item.created_at,
        )
        for item in items
    ]


def _matches_aspect_ratio(item: MediaItem, ratio: str) -> bool:
    if not item.width or not item.height:
        return False
    actual = item.width / item.height
    if ratio == "other":
        return not any(
            abs(actual - t) / max(t, 1e-9) <= _ASPECT_TOLERANCE
            for t in _ASPECT_RATIOS.values()
        )
    target = _ASPECT_RATIOS.get(ratio)
    if target is None:
        return False
    return abs(actual - target) / max(target, 1e-9) <= _ASPECT_TOLERANCE


@router.get("/media")
async def list_media(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    has_people: bool | None = Query(None),
    orientation: str | None = Query(None),
    mood: str | None = Query(None),
    source_id: str | None = Query(None),
    mime_type: str | None = Query(None),
    min_width: int | None = Query(None, ge=1),
    max_width: int | None = Query(None, ge=1),
    min_height: int | None = Query(None, ge=1),
    max_height: int | None = Query(None, ge=1),
    aspect_ratio: str | None = Query(None),
    tags: str | None = Query(None),
    sort_by: str = Query("newest"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> PaginatedResponse:
    """List media items for the current user with optional filters and sort."""
    base_query = select(MediaItem).where(MediaItem.user_id == user_id)

    if status:
        base_query = base_query.where(MediaItem.status == status)
    if source_id is not None:
        base_query = base_query.where(MediaItem.source_id == source_id)

    # MediaItem-level filters (no join needed)
    if mime_type:
        base_query = base_query.where(MediaItem.mime_type == mime_type)
    if min_width is not None:
        base_query = base_query.where(MediaItem.width >= min_width)
    if max_width is not None:
        base_query = base_query.where(MediaItem.width <= max_width)
    if min_height is not None:
        base_query = base_query.where(MediaItem.height >= min_height)
    if max_height is not None:
        base_query = base_query.where(MediaItem.height <= max_height)

    # Metadata-level filters (require join)
    needs_meta_join = any([
        has_people is not None,
        orientation,
        mood,
        tags,
    ])
    if needs_meta_join:
        base_query = base_query.join(
            MediaMetadata, MediaMetadata.media_item_id == MediaItem.id
        )
        if has_people is True:
            base_query = base_query.where(MediaMetadata.people_count > 0)
        elif has_people is False:
            base_query = base_query.where(MediaMetadata.people_count == 0)
        if orientation:
            base_query = base_query.where(MediaMetadata.orientation == orientation)
        if mood:
            base_query = base_query.where(MediaMetadata.mood.ilike(f"%{mood}%"))
        if tags:
            for tag in [t.strip() for t in tags.split(",") if t.strip()]:
                base_query = base_query.where(MediaMetadata.tags.ilike(f'%"{tag}"%'))

    # Sort
    if sort_by == "oldest":
        base_query = base_query.order_by(MediaItem.created_at.asc())
    elif sort_by == "largest":
        base_query = base_query.order_by(
            (MediaItem.width * MediaItem.height).desc()
        )
    elif sort_by == "smallest":
        base_query = base_query.order_by(
            (MediaItem.width * MediaItem.height).asc()
        )
    else:  # "newest" (default)
        base_query = base_query.order_by(MediaItem.created_at.desc())

    # Aspect ratio requires post-query Python filtering (no aspect_ratio column)
    if aspect_ratio:
        # Fetch all matching items, filter in Python, then paginate manually
        items_result = await db.execute(base_query)
        all_items = [i for i in items_result.scalars().all() if _matches_aspect_ratio(i, aspect_ratio)]
        total = len(all_items)
        items = all_items[(page - 1) * per_page : page * per_page]
    else:
        # Normal SQL count + paginated fetch
        count_result = await db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()
        items_result = await db.execute(
            base_query.offset((page - 1) * per_page).limit(per_page)
        )
        items = items_result.scalars().all()

    return PaginatedResponse(
        items=await _build_media_item_responses(db, list(items)),
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/media/{media_id}")
async def get_media(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> MediaItemResponse:
    """Get a single media item by ID."""
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    response = (await _build_media_item_responses(db, [item]))[0]
    return response


@router.get("/media/{media_id}/file")
async def get_media_file(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Serve the raw image file for display."""
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    file_bytes = await _file_store.read(item.storage_path)
    return Response(content=file_bytes, media_type=item.mime_type)
