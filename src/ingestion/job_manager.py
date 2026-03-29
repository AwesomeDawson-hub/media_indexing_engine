"""Processing job management.

Job creation happens in upload_service.py.
Job execution happens in analysis/processor.py (replaced WS-001's placeholder in WS-002).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session
from src.models import ProcessingJob

logger = logging.getLogger(__name__)


async def get_pending_jobs(
    db: AsyncSession,
    limit: int = 10,
    statuses: tuple[str, ...] = ("pending",),
) -> list[ProcessingJob]:
    """Fetch resumable jobs ordered by creation time."""
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.status.in_(statuses))
        .order_by(ProcessingJob.created_at)
        .limit(limit)
    )
    return list(result.scalars().all())
