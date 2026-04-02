"""Authentication endpoints: register, login, profile, email-change, password-reset."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user, get_current_user_id
from src.api.schemas import (
    AuthResponse,
    EmailChangeConfirmRequest,
    EmailChangeRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserProfile,
)
from src.api.rate_limit import login_limiter, register_limiter
from src.auth.passwords import hash_password, verify_password
from src.auth.tokens import create_access_token
from src.config import settings
from src.email_service import send_password_reset
from src.models import PendingToken, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/register", status_code=201, dependencies=[Depends(register_limiter)])
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Register a new user with email and password."""
    # Normalize email
    email = body.email.lower().strip()

    # Validate email format
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Validate password length
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Validate display name
    if not body.display_name.strip():
        raise HTTPException(status_code=400, detail="Display name is required")

    # Check email uniqueness (case-insensitive by convention — stored lowercase)
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create user
    user = User(
        email=email,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()

    # Generate token
    token = create_access_token(user.id)

    return AuthResponse(
        access_token=token,
        user=UserProfile.model_validate(user),
    )


@router.post("/login", dependencies=[Depends(login_limiter)])
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Login with email and password."""
    email = body.email.lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.disabled_at is not None:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "account_disabled", "message": "Your account has been disabled. Contact support."},
        )

    token = create_access_token(user.id)

    return AuthResponse(
        access_token=token,
        user=UserProfile.model_validate(user),
    )


@router.get("/me")
async def get_profile(
    user: User = Depends(get_current_user),
) -> UserProfile:
    """Get current user profile."""
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="Account disabled")
    return UserProfile.model_validate(user)


@router.patch("/me")
async def update_profile(
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Update allowed self-service profile fields."""
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="Account disabled")

    if body.display_name is not None:
        user.display_name = body.display_name
    if body.phone is not None:
        user.phone = body.phone
    if body.company is not None:
        user.company = body.company
    if body.icon_url is not None:
        user.icon_url = body.icon_url

    await db.commit()
    await db.refresh(user)
    return UserProfile.model_validate(user)


# --- Email-change flow ---

@router.post("/email-change/request")
async def request_email_change(
    body: EmailChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request a verified email change. Returns token in dev_mode."""
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="Account disabled")

    new_email = body.new_email.lower().strip()
    if not _EMAIL_RE.match(new_email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Check uniqueness
    existing = await db.execute(select(User).where(User.email == new_email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already in use")

    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_password(plaintext)

    db.add(PendingToken(
        user_id=user.id,
        token_type="email_change",
        token_hash=token_hash,
        new_value=new_email,
        expires_at=_utcnow() + timedelta(minutes=30),
    ))
    await db.commit()

    if settings.auth.dev_mode:
        return {"token": plaintext, "message": "Use this token to confirm the email change."}
    return {"message": "Check your email for a confirmation link."}


@router.post("/email-change/confirm")
async def confirm_email_change(
    body: EmailChangeConfirmRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Confirm an email change using the token from the request step."""
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Find valid, unused, unexpired token for this user
    result = await db.execute(
        select(PendingToken).where(
            PendingToken.user_id == user.id,
            PendingToken.token_type == "email_change",
            PendingToken.used_at.is_(None),
            PendingToken.expires_at > _utcnow(),
        ).order_by(PendingToken.expires_at.desc()).limit(1)
    )
    pending = result.scalar_one_or_none()

    if pending is None or not verify_password(body.token, pending.token_hash):
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    new_email = pending.new_value
    # Re-check uniqueness at confirm time
    existing = await db.execute(select(User).where(User.email == new_email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already in use")

    user.email = new_email
    pending.used_at = _utcnow()
    await db.commit()
    await db.refresh(user)
    return UserProfile.model_validate(user)


# --- Password-reset flow ---

@router.post("/password-reset/request")
async def request_password_reset(
    body: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request a password reset. Always returns 200 (no email enumeration)."""
    email = body.email.lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is not None and user.disabled_at is None:
        plaintext = secrets.token_urlsafe(32)
        token_hash = hash_password(plaintext)
        db.add(PendingToken(
            user_id=user.id,
            token_type="password_reset",
            token_hash=token_hash,
            expires_at=_utcnow() + timedelta(hours=2),
        ))
        await db.commit()

        if settings.auth.dev_mode:
            return {"token": plaintext, "message": "Use this token to reset your password."}

        send_password_reset(user.email, plaintext)

    return {"message": "If that email is registered, you will receive reset instructions."}


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    body: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply a new password using a valid reset token."""
    # Find all non-expired, unused password_reset tokens and check them
    result = await db.execute(
        select(PendingToken).where(
            PendingToken.token_type == "password_reset",
            PendingToken.used_at.is_(None),
            PendingToken.expires_at > _utcnow(),
        )
    )
    candidates = result.scalars().all()

    matched: PendingToken | None = None
    for candidate in candidates:
        if verify_password(body.token, candidate.token_hash):
            matched = candidate
            break

    if matched is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user_result = await db.execute(select(User).where(User.id == matched.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password_hash = hash_password(body.new_password)
    matched.used_at = _utcnow()
    await db.commit()

    return {"message": "Password updated successfully."}
