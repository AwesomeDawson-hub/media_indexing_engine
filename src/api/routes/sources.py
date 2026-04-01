"""Sources API endpoints: create, list, archive, restore."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import SourceCreateRequest, SourceResponse
from src.models import Source

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.post("", status_code=201)
async def create_source(
    body: SourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SourceResponse:
    """Create a new source scoped to the current user."""
    source = Source(
        user_id=user_id,
        name=body.name,
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
    return [SourceResponse.model_validate(s) for s in sources]


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
