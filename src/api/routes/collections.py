"""Collections API endpoints (P7-001).

Endpoints:
  POST   /api/v1/collections                        — create collection
  GET    /api/v1/collections                        — list user collections
  GET    /api/v1/collections/{id}                   — collection detail + items
  PATCH  /api/v1/collections/{id}                   — rename / update description
  DELETE /api/v1/collections/{id}                   — delete collection
  POST   /api/v1/collections/{id}/items             — add items (batch)
  DELETE /api/v1/collections/{id}/items             — remove items (batch)

Collections do not re-analyse or re-index media. Deleting a collection never
deletes the underlying media items.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import (
    CollectionCreateRequest,
    CollectionDetailResponse,
    CollectionItemsModifiedResponse,
    CollectionItemsRequest,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdateRequest,
    MediaItemResponse,
)
from src.models import Collection, CollectionItem, MediaItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/collections", tags=["collections"])

MAX_COLLECTIONS_PER_USER = 100
MAX_ITEMS_PER_COLLECTION = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _require_owned_collection(
    collection_id: str, user_id: str, db: AsyncSession
) -> Collection:
    """Return the Collection or raise 404. Never returns another user's collection."""
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.user_id == user_id,
        )
    )
    coll = result.scalar_one_or_none()
    if coll is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return coll


def _media_item_to_response(item: MediaItem) -> MediaItemResponse:
    return MediaItemResponse(
        id=item.id,
        content_hash=item.content_hash,
        original_filename=item.original_filename,
        display_name=item.display_name,
        file_size=item.file_size,
        mime_type=item.mime_type,
        status=item.status,
        width=item.width,
        height=item.height,
        source_id=item.source_id,
        created_at=item.created_at,
    )


async def _build_collection_response(
    coll: Collection, db: AsyncSession
) -> CollectionResponse:
    """Build CollectionResponse including item_count and cover_url."""
    count_result = await db.execute(
        select(func.count()).where(CollectionItem.collection_id == coll.id)
    )
    item_count = count_result.scalar_one()

    # Cover = file URL of the earliest-added item
    cover_url: str | None = None
    if item_count > 0:
        first = await db.execute(
            select(CollectionItem)
            .where(CollectionItem.collection_id == coll.id)
            .order_by(CollectionItem.added_at.asc())
            .limit(1)
        )
        first_item = first.scalar_one_or_none()
        if first_item:
            cover_url = f"/api/v1/media/{first_item.media_item_id}/file"

    return CollectionResponse(
        id=coll.id,
        name=coll.name,
        description=coll.description,
        item_count=item_count,
        cover_url=cover_url,
        created_at=coll.created_at.isoformat(),
        updated_at=coll.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_collection(
    body: CollectionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> CollectionResponse:
    """Create a new collection for the current user."""
    # Enforce per-user limit
    count_result = await db.execute(
        select(func.count()).where(Collection.user_id == user_id)
    )
    if count_result.scalar_one() >= MAX_COLLECTIONS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_COLLECTIONS_PER_USER} collections per account reached.",
        )

    coll = Collection(
        user_id=user_id,
        name=body.name.strip(),
        description=body.description,
    )
    db.add(coll)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A collection named '{body.name}' already exists.",
        )
    await db.refresh(coll)
    return await _build_collection_response(coll, db)


@router.get("")
async def list_collections(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> CollectionListResponse:
    """List all collections for the current user."""
    result = await db.execute(
        select(Collection)
        .where(Collection.user_id == user_id)
        .order_by(Collection.created_at.desc())
    )
    colls = result.scalars().all()

    responses = []
    for coll in colls:
        responses.append(await _build_collection_response(coll, db))

    return CollectionListResponse(collections=responses, total=len(responses))


@router.get("/{collection_id}")
async def get_collection(
    collection_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> CollectionDetailResponse:
    """Get a collection with its full item list."""
    coll = await _require_owned_collection(collection_id, user_id, db)

    # Load items ordered by added_at
    items_result = await db.execute(
        select(CollectionItem)
        .where(CollectionItem.collection_id == collection_id)
        .options(selectinload(CollectionItem.media_item))
        .order_by(CollectionItem.added_at.asc())
    )
    collection_items = items_result.scalars().all()
    media_responses = [
        _media_item_to_response(ci.media_item) for ci in collection_items
    ]

    return CollectionDetailResponse(
        id=coll.id,
        name=coll.name,
        description=coll.description,
        item_count=len(media_responses),
        created_at=coll.created_at.isoformat(),
        updated_at=coll.updated_at.isoformat(),
        items=media_responses,
    )


@router.patch("/{collection_id}")
async def update_collection(
    collection_id: str,
    body: CollectionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> CollectionResponse:
    """Rename or update description of a collection."""
    coll = await _require_owned_collection(collection_id, user_id, db)

    if body.name is not None:
        coll.name = body.name.strip()
    if body.description is not None:
        coll.description = body.description

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A collection named '{body.name}' already exists.",
        )
    await db.refresh(coll)
    return await _build_collection_response(coll, db)


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Delete a collection. Does NOT delete the media items."""
    coll = await _require_owned_collection(collection_id, user_id, db)
    await db.delete(coll)
    await db.commit()


@router.post("/{collection_id}/items", status_code=200)
async def add_items(
    collection_id: str,
    body: CollectionItemsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> CollectionItemsModifiedResponse:
    """Add media items to a collection."""
    coll = await _require_owned_collection(collection_id, user_id, db)

    # Current item count
    count_result = await db.execute(
        select(func.count()).where(CollectionItem.collection_id == coll.id)
    )
    current_count = count_result.scalar_one()

    # Verify media items belong to this user
    owned_result = await db.execute(
        select(MediaItem.id).where(
            MediaItem.id.in_(body.media_item_ids),
            MediaItem.user_id == user_id,
        )
    )
    owned_ids = {row[0] for row in owned_result.all()}

    # Already-in-collection items
    existing_result = await db.execute(
        select(CollectionItem.media_item_id).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.media_item_id.in_(owned_ids),
        )
    )
    existing_ids = {row[0] for row in existing_result.all()}

    to_add = owned_ids - existing_ids
    skipped = len(body.media_item_ids) - len(to_add)

    if current_count + len(to_add) > MAX_ITEMS_PER_COLLECTION:
        raise HTTPException(
            status_code=400,
            detail=f"Adding these items would exceed the {MAX_ITEMS_PER_COLLECTION} item limit.",
        )

    now = _utcnow()
    for media_id in to_add:
        db.add(CollectionItem(collection_id=collection_id, media_item_id=media_id, added_at=now))

    await db.commit()
    return CollectionItemsModifiedResponse(added=len(to_add), skipped=skipped)


@router.delete("/{collection_id}/items", status_code=200)
async def remove_items(
    collection_id: str,
    body: CollectionItemsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> CollectionItemsModifiedResponse:
    """Remove media items from a collection."""
    await _require_owned_collection(collection_id, user_id, db)

    result = await db.execute(
        select(CollectionItem).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.media_item_id.in_(body.media_item_ids),
        )
    )
    items_to_remove = result.scalars().all()

    for item in items_to_remove:
        await db.delete(item)
    await db.commit()

    return CollectionItemsModifiedResponse(removed=len(items_to_remove))
