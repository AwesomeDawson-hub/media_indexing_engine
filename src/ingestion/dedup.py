"""Per-user deduplication check (ADR-001)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import MediaItem


async def check_duplicate(
    db: AsyncSession, user_id: str, content_hash: str
) -> MediaItem | None:
    """Return the existing MediaItem if (user_id, content_hash) already exists, else None."""
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.user_id == user_id,
            MediaItem.content_hash == content_hash,
        )
    )
    return result.scalar_one_or_none()
