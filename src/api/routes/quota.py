"""Quota API endpoint: GET /api/v1/quota/status."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import QuotaStatusResponse
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
