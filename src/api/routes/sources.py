"""Sources API endpoints: create, list, archive, restore."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import SourceCreateRequest, SourceResponse
from src.models import MediaItem, Source

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


class _RenameRequest(BaseModel):
    name: str


@router.post("", status_code=201)
async def create_source(
    body: SourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SourceResponse:
    """Create a new source scoped to the current user."""
    # Check for name collision (case-insensitive) among this user's sources
    existing = await db.execute(
        select(Source).where(
            Source.user_id == user_id,
            func.lower(Source.name) == body.name.strip().lower(),
        )
    )
    conflict = existing.scalar_one_or_none()
    if conflict is not None:
        if conflict.archived_at is None:
            raise HTTPException(
                status_code=409,
                detail={"message": f"A source named '{conflict.name}' already exists.", "error_code": "source_name_conflict"},
            )
        else:
            raise HTTPException(
                status_code=409,
                detail={"message": f"'{conflict.name}' exists but is archived.", "error_code": "source_name_archived", "archived_source_id": conflict.id},
            )

    source = Source(
        user_id=user_id,
        name=body.name.strip(),
        source_type=body.source_type,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return SourceResponse.model_validate(source)


@router.get("")
async def list_sources(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> list[SourceResponse]:
    """List all sources for the current user. Excludes archived by default."""
    stmt = select(Source).where(Source.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Source.archived_at.is_(None))
    result = await db.execute(stmt)
    sources = result.scalars().all()

    # Fetch media counts in one query
    source_ids = [s.id for s in sources]
    counts: dict[str, int] = {}
    if source_ids:
        count_result = await db.execute(
            select(MediaItem.source_id, func.count().label("cnt"))
            .where(MediaItem.source_id.in_(source_ids))
            .group_by(MediaItem.source_id)
        )
        counts = {sid: cnt for sid, cnt in count_result.all()}

    responses = []
    for s in sources:
        r = SourceResponse.model_validate(s)
        r.media_count = counts.get(s.id, 0)
        responses.append(r)
    return responses


@router.patch("/{source_id}")
async def rename_source(
    source_id: str,
    body: _RenameRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SourceResponse:
    """Rename a source."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank")
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.name = name
    source.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(source)
    return SourceResponse.model_validate(source)


@router.post("/{source_id}/archive")
async def archive_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SourceResponse:
    """Soft-delete a source by setting archived_at. Idempotent. 404 if not owned."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.archived_at is None:
        source.archived_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(source)
    return SourceResponse.model_validate(source)


@router.post("/{source_id}/restore")
async def restore_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SourceResponse:
    """Clear archived_at on a source, making it active again. Idempotent. 404 if not owned."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.archived_at is not None:
        source.archived_at = None
        await db.commit()
        await db.refresh(source)
    return SourceResponse.model_validate(source)
