"""Quota API endpoints: GET /api/v1/quota/status and GET /api/v1/quota/history."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import QuotaDailyUsageResponse, QuotaHistoryResponse, QuotaStatusResponse
from src.quota.quota_service import QuotaService

router = APIRouter(prefix="/api/v1/quota", tags=["quota"])

_quota_service = QuotaService()


@router.get("/status")
async def get_quota_status(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> QuotaStatusResponse:
    """Return current user's quota usage for the active billing period."""
    status = await _quota_service.get_status(db, user_id)
    return QuotaStatusResponse(**status)


@router.get("/history")
async def get_quota_history(
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> QuotaHistoryResponse:
    """Return paginated quota event history for the current user."""
    result = await _quota_service.get_history(db, user_id, period, page, per_page)
    return QuotaHistoryResponse(**result)


@router.get("/daily")
async def get_daily_usage(
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> QuotaDailyUsageResponse:
    """Return per-day consumed analysis counts for a billing period."""
    result = await _quota_service.get_daily_usage(db, user_id, period)
    return QuotaDailyUsageResponse(**result)
