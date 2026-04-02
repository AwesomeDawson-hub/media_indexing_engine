"""Admin-only API routes for user management and audit log."""

import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_admin
from src.api.schemas import (
    AdminUpdateUserRequest,
    AdminUserDetailResponse,
    AdminUserSummary,
    AdminUsersListResponse,
    AuditLogEntry,
    AuditLogListResponse,
)
from src.models import AdminAuditLog, QuotaEvent, User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _write_audit(
    db: AsyncSession,
    acting_admin_id: str,
    target_user_id: str | None,
    action: str,
    detail: dict | None = None,
) -> None:
    """Insert an admin audit log entry (within the current session)."""
    entry = AdminAuditLog(
        acting_admin_id=acting_admin_id,
        target_user_id=target_user_id,
        action=action,
        detail=json.dumps(detail) if detail else None,
    )
    db.add(entry)


@router.get("/users", response_model=AdminUsersListResponse)
async def list_users(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUsersListResponse:
    """List all users with optional search on email/display_name."""
    query = select(User)
    if search:
        pattern = f"%{search}%"
        query = query.where(User.email.ilike(pattern) | User.display_name.ilike(pattern))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    return AdminUsersListResponse(
        users=[AdminUserSummary.model_validate(u) for u in users],
        total=total,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserDetailResponse:
    """Get full detail for a single user including this month's quota consumption."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Count consumed quota events for the current calendar month
    from datetime import date
    period = date.today().replace(day=1)
    consumed_result = await db.execute(
        select(func.count()).where(
            QuotaEvent.user_id == user_id,
            QuotaEvent.event_type == "consumed",
            QuotaEvent.period_month == period,
        )
    )
    quota_this_month = consumed_result.scalar_one()

    detail = AdminUserDetailResponse.model_validate(user)
    detail.quota_this_month = quota_this_month
    return detail


@router.patch("/users/{user_id}", response_model=AdminUserSummary)
async def update_user(
    user_id: str,
    body: AdminUpdateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserSummary:
    """Update user fields. Writes an audit entry for each changed field."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    changes: dict = {}

    if body.email is not None and body.email != user.email:
        if not _EMAIL_RE.match(body.email):
            raise HTTPException(status_code=400, detail="Invalid email format")
        # Check uniqueness
        existing = await db.execute(select(User).where(User.email == body.email.lower().strip(), User.id != user_id))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Email already in use")
        changes["email"] = {"from": user.email, "to": body.email.lower().strip()}
        user.email = body.email.lower().strip()

    if body.display_name is not None and body.display_name != user.display_name:
        changes["display_name"] = {"from": user.display_name, "to": body.display_name}
        user.display_name = body.display_name

    if body.phone is not None and body.phone != user.phone:
        changes["phone"] = {"from": user.phone, "to": body.phone}
        user.phone = body.phone

    if body.company is not None and body.company != user.company:
        changes["company"] = {"from": user.company, "to": body.company}
        user.company = body.company

    if body.icon_url is not None and body.icon_url != user.icon_url:
        changes["icon_url"] = {"from": user.icon_url, "to": body.icon_url}
        user.icon_url = body.icon_url

    if body.plan_name is not None and body.plan_name != user.plan_name:
        changes["plan_name"] = {"from": user.plan_name, "to": body.plan_name}
        user.plan_name = body.plan_name

    if body.monthly_limit is not None and body.monthly_limit != user.monthly_limit:
        changes["monthly_limit"] = {"from": user.monthly_limit, "to": body.monthly_limit}
        user.monthly_limit = body.monthly_limit

    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")
        if body.role != user.role:
            changes["role"] = {"from": user.role, "to": body.role}
            user.role = body.role

    if body.disabled is not None:
        currently_disabled = user.disabled_at is not None
        if body.disabled and not currently_disabled:
            changes["disabled"] = {"from": False, "to": True}
            user.disabled_at = _utcnow()
        elif not body.disabled and currently_disabled:
            changes["disabled"] = {"from": True, "to": False}
            user.disabled_at = None

    if body.billing_status is not None and body.billing_status != user.billing_status:
        _VALID_BILLING_STATUSES = {"none", "active", "trialing", "past_due", "canceled", "unpaid"}
        if body.billing_status not in _VALID_BILLING_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid billing_status")
        changes["billing_status"] = {"from": user.billing_status, "to": body.billing_status}
        user.billing_status = body.billing_status

    if changes:
        await _write_audit(db, admin.id, user_id, "update_user", changes)

    await db.commit()
    await db.refresh(user)
    return AdminUserSummary.model_validate(user)


@router.get("/audit-log", response_model=AuditLogListResponse)
async def get_audit_log(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    target_user_id: str | None = Query(default=None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """List admin audit log entries, most recent first."""
    query = select(AdminAuditLog)
    if target_user_id:
        query = query.where(AdminAuditLog.target_user_id == target_user_id)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(AdminAuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    entries = result.scalars().all()

    return AuditLogListResponse(
        entries=[AuditLogEntry.model_validate(e) for e in entries],
        total=total,
    )
