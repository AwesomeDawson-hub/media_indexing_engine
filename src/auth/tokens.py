"""JWT token creation and validation."""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from src.config import settings


class TokenError(Exception):
    """Raised when token validation fails."""
    pass


def create_access_token(user_id: str) -> str:
    """Create a signed JWT with sub and exp claims."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.auth.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.auth.secret_key, algorithm=settings.auth.algorithm)


def decode_access_token(token: str) -> str:
    """Validate a JWT and return the user_id. Raises TokenError on failure."""
    try:
        payload = jwt.decode(token, settings.auth.secret_key, algorithms=[settings.auth.algorithm])
    except JWTError as e:
        raise TokenError(f"Invalid or expired token: {e}")

    user_id = payload.get("sub")
    if user_id is None:
        raise TokenError("Token missing 'sub' claim")

    return user_id
