"""FastAPI dependency providers for DB sessions and current user."""

from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session
from src.models import User
from src.auth.tokens import decode_access_token, TokenError

# Dev user ID — used as fallback in dev_mode
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user_id(
    authorization: str | None = Header(None),
) -> str:
    """Extract user ID from JWT token, or fall back to dev user in dev mode.

    - If Authorization header present: decode JWT, return user_id from 'sub' claim
    - If missing + dev_mode: return DEV_USER_ID
    - If missing + not dev_mode: raise 401
    """
    if authorization is not None:
        # Extract token from "Bearer <token>"
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization header format")

        token = parts[1]
        try:
            user_id = decode_access_token(token)
        except TokenError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return user_id

    # No token provided
    if settings.auth.dev_mode:
        return DEV_USER_ID

    raise HTTPException(status_code=401, detail="Authentication required")


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Fetch the full User row for the current request."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require the current user to be an admin. Raises 403 otherwise."""
    if user.role != "admin" or user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
