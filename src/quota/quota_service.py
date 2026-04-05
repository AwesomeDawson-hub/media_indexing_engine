"""QuotaService: reserve, consume, and release analysis quota for users.

Concurrency strategy: SELECT FOR UPDATE on the users row before counting
and inserting reservation events, preventing double-spend under concurrent uploads.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import MediaItem, QuotaEvent, User

logger = logging.getLogger(__name__)


def _current_period() -> date:
    """Return the first day of the current UTC month."""
    now = datetime.now(timezone.utc)
    return date(now.year, now.month, 1)


class QuotaExceededError(Exception):
    """Raised when a user has exhausted their monthly quota."""

    def __init__(self, remaining: int, limit: int) -> None:
        self.remaining = remaining
        self.limit = limit
        super().__init__(f"Monthly quota exceeded (limit={limit}, remaining={remaining})")


def build_quota_exceeded_detail(exc: QuotaExceededError) -> dict:
    """Build a structured API payload for quota exhaustion."""
    return {
        "error_code": "QUOTA_EXCEEDED",
        "message": "Monthly quota exceeded",
        "error": "quota_exceeded",
        "remaining": exc.remaining,
        "limit": exc.limit,
    }


class QuotaService:
    """All quota operations for a single request.  Stateless — safe to instantiate per-request."""

    async def get_status(self, db: AsyncSession, user_id: str) -> dict:
        """Return quota usage dict for the current period.

        Keys: plan_name, monthly_limit, consumed, reserved, remaining, period_month.
        """
        period = _current_period()

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one()

        counts_result = await db.execute(
            select(QuotaEvent.event_type, func.count().label("n"))
            .where(
                QuotaEvent.user_id == user_id,
                QuotaEvent.period_month == period,
                QuotaEvent.event_type.in_(["reserved", "consumed"]),
            )
            .group_by(QuotaEvent.event_type)
        )
        counts = {row.event_type: row.n for row in counts_result}

        consumed = counts.get("consumed", 0)
        reserved = counts.get("reserved", 0)
        used = consumed + reserved
        remaining = max(0, user.monthly_limit - used)

        return {
            "plan_name": user.plan_name,
            "monthly_limit": user.monthly_limit,
            "consumed": consumed,
            "reserved": reserved,
            "remaining": remaining,
            "period_month": period.strftime("%Y-%m"),
        }

    async def get_history(
        self,
        db: AsyncSession,
        user_id: str,
        period_str: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> dict:
        """Return paginated quota event history for a given period.

        Returns dict with keys: items, total, page, per_page, period_month.
        """
        if period_str:
            try:
                dt = datetime.strptime(period_str, "%Y-%m")
                period = date(dt.year, dt.month, 1)
            except ValueError:
                period = _current_period()
        else:
            period = _current_period()

        offset = (page - 1) * per_page

        count_result = await db.execute(
            select(func.count())
            .select_from(QuotaEvent)
            .where(
                QuotaEvent.user_id == user_id,
                QuotaEvent.period_month == period,
            )
        )
        total = count_result.scalar_one()

        rows_result = await db.execute(
            select(
                QuotaEvent.id,
                QuotaEvent.event_type,
                QuotaEvent.media_item_id,
                QuotaEvent.created_at,
                QuotaEvent.period_month,
                MediaItem.original_filename,
            )
            .outerjoin(MediaItem, QuotaEvent.media_item_id == MediaItem.id)
            .where(
                QuotaEvent.user_id == user_id,
                QuotaEvent.period_month == period,
            )
            .order_by(QuotaEvent.created_at.desc())
            .limit(per_page)
            .offset(offset)
        )
        rows = rows_result.all()

        return {
            "items": [
                {
                    "id": str(row.id),
                    "event_type": row.event_type,
                    "media_item_id": str(row.media_item_id) if row.media_item_id else None,
                    "original_filename": row.original_filename,
                    "created_at": row.created_at,
                    "period_month": row.period_month.strftime("%Y-%m"),
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "period_month": period.strftime("%Y-%m"),
        }

    async def reserve(self, db: AsyncSession, user_id: str, media_item_id: str) -> str:
        """Reserve one quota unit for the current period.

        Acquires a row-level lock on the users row, counts current usage, and
        inserts a 'reserved' event if quota remains.  Returns the reservation ID.
        Raises QuotaExceededError if the limit is already reached.
        """
        period = _current_period()

        # Lock the user row to prevent concurrent over-reservation
        user_result = await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = user_result.scalar_one()

        # Count active (reserved + consumed) events this period
        count_result = await db.execute(
            select(func.count())
            .select_from(QuotaEvent)
            .where(
                QuotaEvent.user_id == user_id,
                QuotaEvent.period_month == period,
                QuotaEvent.event_type.in_(["reserved", "consumed"]),
            )
        )
        used = count_result.scalar_one()

        if used >= user.monthly_limit:
            raise QuotaExceededError(remaining=0, limit=user.monthly_limit)

        event = QuotaEvent(
            user_id=user_id,
            event_type="reserved",
            media_item_id=media_item_id,
            period_month=period,
        )
        db.add(event)
        await db.flush()  # materialise the ID without committing the outer transaction
        reservation_id = event.id
        await db.commit()
        logger.debug("Quota reserved: user=%s reservation=%s period=%s", user_id, reservation_id, period)
        return reservation_id

    async def consume(self, db: AsyncSession, reservation_id: str) -> None:
        """Mark a reservation as consumed (analysis succeeded)."""
        result = await db.execute(
            select(QuotaEvent).where(QuotaEvent.id == reservation_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            logger.warning("consume: quota event %s not found", reservation_id)
            return
        if event.event_type != "reserved":
            logger.warning(
                "consume: refusing invalid quota transition for %s (%s)",
                reservation_id,
                event.event_type,
            )
            return
        event.event_type = "consumed"
        await db.commit()
        logger.debug("Quota consumed: reservation=%s", reservation_id)

    async def release(self, db: AsyncSession, reservation_id: str) -> None:
        """Mark a reservation as released (analysis failed permanently)."""
        result = await db.execute(
            select(QuotaEvent).where(QuotaEvent.id == reservation_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            logger.warning("release: quota event %s not found", reservation_id)
            return
        if event.event_type != "reserved":
            logger.warning(
                "release: refusing invalid quota transition for %s (%s)",
                reservation_id,
                event.event_type,
            )
            return
        event.event_type = "released"
        await db.commit()
        logger.debug("Quota released: reservation=%s", reservation_id)
