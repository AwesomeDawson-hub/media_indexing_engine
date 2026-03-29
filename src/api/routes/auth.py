"""Authentication endpoints: register, login, profile."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user_id
from src.api.schemas import RegisterRequest, LoginRequest, AuthResponse, UserProfile
from src.api.rate_limit import login_limiter, register_limiter
from src.auth.passwords import hash_password, verify_password
from src.auth.tokens import create_access_token
from src.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/register", status_code=201, dependencies=[Depends(register_limiter)])
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Register a new user with email and password."""
    # Validate email format
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Validate password length
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Validate display name
    if not body.display_name.strip():
        raise HTTPException(status_code=400, detail="Display name is required")

    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create user
    user = User(
        email=body.email,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()

    # Generate token
    token = create_access_token(user.id)

    return AuthResponse(
        access_token=token,
        user=UserProfile(id=user.id, email=user.email, display_name=user.display_name),
    )


@router.post("/login", dependencies=[Depends(login_limiter)])
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Login with email and password."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user.id)

    return AuthResponse(
        access_token=token,
        user=UserProfile(id=user.id, email=user.email, display_name=user.display_name),
    )


@router.get("/me")
async def get_profile(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Get current user profile."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return UserProfile(id=user.id, email=user.email, display_name=user.display_name)
