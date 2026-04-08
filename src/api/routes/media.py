"""Media item API endpoints: list, detail, and file serving."""

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import (
    MediaItemResponse, PaginatedResponse, SimilarItemResponse, SimilarItemsResponse,
    ScoreGroupResponse, LocalMutationResultRequest, MutationStateResponse,
)
from src.api.routes.upload import _file_store
from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis
from src.config import settings
from src.curation.phash_service import find_similar, PHASH_THRESHOLD
from src.curation.scoring_service import load_scores_for_items, find_best_pick, score_group
from src.models import MediaItem, MediaMetadata, Source, SourceMutationHistory

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


async def _get_source_names(
    db: AsyncSession,
    source_ids: list[str],
) -> dict[str, str]:
    if not source_ids:
        return {}
    result = await db.execute(
        select(Source.id, Source.name).where(Source.id.in_(source_ids))
    )
    return dict(result.all())


async def _build_media_item_responses(
    db: AsyncSession,
    items: list[MediaItem],
) -> list[MediaItemResponse]:
    display_names = await _get_display_names(db, [item.id for item in items])
    source_ids = [item.source_id for item in items if item.source_id]
    source_names = await _get_source_names(db, source_ids)

    # Similarity summary — one batch query per page when feature gate is ON
    similarity_map: dict[str, tuple[bool, int]] = {}  # item_id -> (has_similar, similar_count)
    if settings.curation.enable_duplicate_detection:
        # Collect all items on this page that have a pHash
        hashed_items = [i for i in items if i.perceptual_hash]
        if hashed_items:
            user_id = hashed_items[0].user_id
            # Load all hashes for this user in one query
            all_hashes_result = await db.execute(
                select(MediaItem.id, MediaItem.perceptual_hash)
                .where(
                    MediaItem.user_id == user_id,
                    MediaItem.perceptual_hash.isnot(None),
                )
            )
            user_candidates: list[tuple[str, str]] = list(all_hashes_result.all())
            # Compute similarity for each pHash item on this page
            for page_item in hashed_items:
                # Exclude the item itself from candidates
                candidates = [(cid, ch) for cid, ch in user_candidates if cid != page_item.id]
                similar = find_similar(candidates, page_item.perceptual_hash, PHASH_THRESHOLD)
                similarity_map[page_item.id] = (len(similar) > 0, len(similar))

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
            source_name=source_names.get(item.source_id) if item.source_id else None,
            created_at=item.created_at,
            has_similar=similarity_map.get(item.id, (False, 0))[0],
            similar_count=similarity_map.get(item.id, (False, 0))[1],
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
    """Serve the raw original file.

    Returns 404 with error_code='original_not_retained' when the item has been
    transitioned to preview_only storage mode (Slice B connector items).
    """
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    if item.storage_mode == "preview_only" or not item.storage_path:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "original_not_retained",
                "message": "Original is at the source. Use the source connector to access it.",
            },
        )

    file_bytes = await _file_store.read(item.storage_path)
    return Response(content=file_bytes, media_type=item.mime_type)


@router.get("/media/{media_id}/thumbnail")
async def get_media_thumbnail(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Serve the thumbnail for a media item.

    - When thumbnail_path is set: serves the stored JPEG thumbnail.
    - When thumbnail_path is NULL and storage_mode='full': falls back to the original file.
    - When neither is available (preview_only, no thumbnail): returns 404.
    """
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    if item.thumbnail_path:
        thumb_bytes = await _file_store.read(item.thumbnail_path)
        return Response(content=thumb_bytes, media_type="image/jpeg")

    if item.storage_mode == "full" and item.storage_path:
        file_bytes = await _file_store.read(item.storage_path)
        return Response(content=file_bytes, media_type=item.mime_type)

    raise HTTPException(
        status_code=404,
        detail={
            "error_code": "preview_unavailable",
            "message": "No thumbnail available for this item.",
        },
    )


@router.get("/media/{media_id}/similar")
async def get_similar_media(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SimilarItemsResponse:
    """Return near-duplicate images for the given media item (user-scoped).

    Requires the duplicate-detection feature gate to be enabled.
    Returns 404 if the item is not owned by the current user.
    Returns an empty `similar` list when the item has no perceptual hash or
    when no neighbours are within PHASH_THRESHOLD bits.

    When the AI scoring gate is also ON, each result includes quality_score,
    rationale, and is_best_pick fields (null when item has not yet been scored).
    """
    if not settings.curation.enable_duplicate_detection:
        raise HTTPException(status_code=404, detail="Feature not enabled")

    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    anchor = result.scalar_one_or_none()
    if anchor is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    if not anchor.perceptual_hash:
        return SimilarItemsResponse(anchor_id=media_id, similar=[])

    # Load all user hashes in one query (exclude anchor)
    all_hashes_result = await db.execute(
        select(MediaItem.id, MediaItem.perceptual_hash)
        .where(
            MediaItem.user_id == user_id,
            MediaItem.id != media_id,
            MediaItem.perceptual_hash.isnot(None),
        )
    )
    candidates: list[tuple[str, str]] = list(all_hashes_result.all())
    similar_pairs = find_similar(candidates, anchor.perceptual_hash, PHASH_THRESHOLD)

    if not similar_pairs:
        return SimilarItemsResponse(anchor_id=media_id, similar=[])

    similar_ids = [sid for sid, _ in similar_pairs]
    dist_map = {sid: dist for sid, dist in similar_pairs}

    items_result = await db.execute(
        select(MediaItem).where(
            MediaItem.id.in_(similar_ids),
            MediaItem.user_id == user_id,
        )
    )
    similar_items = {item.id: item for item in items_result.scalars().all()}

    media_responses = await _build_media_item_responses(db, list(similar_items.values()))
    response_map = {r.id: r for r in media_responses}

    # Load scores when AI scoring gate is ON
    scores_map = {}
    anchor_score = None
    if settings.curation.enable_ai_scoring:
        all_ids = [media_id] + similar_ids
        scores_map = await load_scores_for_items(db, all_ids)
        anchor_score = scores_map.get(media_id)

        # Compute is_best_pick: highest quality_score in the whole group
        group_scores: dict[str, float] = {}
        for item_id, score_row in scores_map.items():
            group_scores[item_id] = score_row.quality_score
        best_pick_id = find_best_pick(group_scores)
    else:
        best_pick_id = None

    similar_list = [
        SimilarItemResponse(
            id=sid,
            hamming_distance=dist_map[sid],
            media_item=response_map[sid],
            quality_score=scores_map[sid].quality_score if sid in scores_map else None,
            rationale=scores_map[sid].rationale if sid in scores_map else None,
            is_best_pick=(best_pick_id == sid),
        )
        for sid in similar_ids
        if sid in response_map
    ]

    return SimilarItemsResponse(
        anchor_id=media_id,
        similar=similar_list,
        anchor_quality_score=anchor_score.quality_score if anchor_score else None,
        anchor_rationale=anchor_score.rationale if anchor_score else None,
        anchor_is_best_pick=(best_pick_id == media_id),
    )


@router.post("/media/{media_id}/score-group")
async def score_media_group(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ScoreGroupResponse:
    """Trigger AI quality scoring for the near-duplicate group anchored at media_id.

    Requires both duplicate-detection and AI scoring feature gates to be ON.
    Scores all members of the group (anchor + similar items within PHASH_THRESHOLD).
    Re-calling is idempotent: existing scores are updated.
    Returns 404 when gates are OFF or the item is not found / not owned.
    """
    if not settings.curation.enable_duplicate_detection:
        raise HTTPException(status_code=404, detail="Feature not enabled")
    if not settings.curation.enable_ai_scoring:
        raise HTTPException(status_code=404, detail="AI scoring not enabled")

    # Verify item ownership before triggering scoring
    ownership_result = await db.execute(
        select(MediaItem.id).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    if ownership_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    result = await score_group(
        anchor_id=media_id,
        user_id=user_id,
        db=db,
        file_store=_file_store,
    )

    best_pick_name: str | None = None
    if result.best_pick_id:
        name_result = await db.execute(
            select(MediaItem.original_filename).where(MediaItem.id == result.best_pick_id)
        )
        best_pick_name = name_result.scalar_one_or_none()

    if result.scored_count == 0:
        message = "No items could be scored."
    elif best_pick_name:
        message = f"Scored {result.scored_count} image{'s' if result.scored_count != 1 else ''}. Best pick: {best_pick_name}"
    else:
        message = f"Scored {result.scored_count} image{'s' if result.scored_count != 1 else ''}."

    return ScoreGroupResponse(
        anchor_id=media_id,
        scored_count=result.scored_count,
        failed_count=result.failed_count,
        best_pick_id=result.best_pick_id,
        message=message,
    )


# ---------------------------------------------------------------------------
# POST /media/{id}/mutation-result  — local working-folder / folder-scan flow
# ---------------------------------------------------------------------------

@router.post("/media/{media_id}/mutation-result", status_code=200)
async def report_local_mutation_result(
    media_id: str,
    body: LocalMutationResultRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> MutationStateResponse:
    """Report the result of a browser-side local file mutation (P7-004).

    Used by the frontend for browser drag-drop into a local working-folder or
    user-selected folder-scan flows.  The browser performs the rename /
    metadata write-back locally, then calls this endpoint to record the outcome
    so the backend reflects the correct ``mutation_state``.

    Body:
      - ``succeeded``: whether the file mutation completed on the local device.
      - ``new_filename``: the filename applied at the source (if succeeded).
      - ``error_code``: short code for ``blocked_writeback`` classification.
      - ``error_message``: human-readable error detail (operator-safe).
      - ``operation_type``: ``rename`` or ``metadata_write``.
      - ``source_file_fingerprint``: SHA-256 of the file bytes for later rematch.
    """
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    now = datetime.now(timezone.utc)
    item.last_mutation_attempted_at = now

    if item.first_seen_source_filename is None:
        item.first_seen_source_filename = item.original_filename

    if body.source_file_fingerprint:
        item.source_file_fingerprint = body.source_file_fingerprint

    if body.succeeded:
        item.prior_source_filename = item.first_seen_source_filename
        item.source_filename_applied_at = now
        if body.operation_type == "metadata_write":
            item.last_writeback_at = now
        item.mutation_state = "fully_applied"
        item.last_mutation_error_code = None
        item.last_mutation_error_message = None

        history = SourceMutationHistory(
            media_item_id=item.id,
            user_id=user_id,
            operation_type=body.operation_type or "rename",
            prior_filename=item.first_seen_source_filename,
            new_filename=body.new_filename,
            source_locator_snapshot=json.dumps({"source_type": "local_browser"}),
            succeeded=True,
            attempted_at=now,
            completed_at=now,
        )
    else:
        # Blocking condition — folder access lost, file not found, etc.
        item.mutation_state = "blocked_writeback"
        item.last_mutation_error_code = body.error_code or "local_access_lost"
        item.last_mutation_error_message = body.error_message

        history = SourceMutationHistory(
            media_item_id=item.id,
            user_id=user_id,
            operation_type=body.operation_type or "rename",
            prior_filename=item.first_seen_source_filename,
            new_filename=body.new_filename,
            source_locator_snapshot=json.dumps({"source_type": "local_browser"}),
            succeeded=False,
            error_code=item.last_mutation_error_code,
            error_message=item.last_mutation_error_message[:500] if item.last_mutation_error_message else None,
            attempted_at=now,
        )

    db.add(history)
    await db.commit()

    return MutationStateResponse(
        media_item_id=item.id,
        mutation_state=item.mutation_state,
        first_seen_source_filename=item.first_seen_source_filename,
        prior_source_filename=item.prior_source_filename,
        source_filename_applied_at=item.source_filename_applied_at,
        last_mutation_error_code=item.last_mutation_error_code,
        last_mutation_error_message=item.last_mutation_error_message,
    )


# ---------------------------------------------------------------------------
# POST /media/{id}/retry-writeback  — server-side Drive retry (P7-005)
# ---------------------------------------------------------------------------

@router.post("/media/{media_id}/retry-writeback", status_code=200)
async def retry_writeback(
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> MutationStateResponse:
    """Retry a previously failed Drive write-back for a media item (P7-005).

    Only items with ``mutation_state == 'pending_writeback'`` (transient
    failures) can be retried.  Items in ``blocked_writeback`` require user
    action (e.g. re-authorising Drive) and must not be silently retried.
    """
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    if item.mutation_state != "pending_writeback":
        raise HTTPException(
            status_code=422,
            detail="Only items in 'pending_writeback' state can be retried.",
        )

    await attempt_drive_rename_after_analysis(db, item)
    await db.commit()

    return MutationStateResponse(
        media_item_id=item.id,
        mutation_state=item.mutation_state,
        first_seen_source_filename=item.first_seen_source_filename,
        prior_source_filename=item.prior_source_filename,
        source_filename_applied_at=item.source_filename_applied_at,
        last_mutation_error_code=item.last_mutation_error_code,
        last_mutation_error_message=item.last_mutation_error_message,
    )
