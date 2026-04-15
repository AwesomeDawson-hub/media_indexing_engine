"""Google SSO endpoints — start / callback / exchange (P6-001).

Flow:
  1. GET  /api/v1/auth/google/start     → redirect browser to Google
  2. GET  /api/v1/auth/google/callback  → validate, resolve user, create completion record,
                                          redirect browser to frontend callback page
  3. POST /api/v1/auth/google/exchange  → consume completion record, return AuthResponse
  4. GET  /api/v1/auth/config           → public feature-flag state for auth providers
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas import AuthResponse, GoogleExchangeRequest, UserProfile
from src.auth.google_oauth import (
    GoogleClaims,
    build_auth_url,
    exchange_code_and_validate,
    generate_nonce,
    generate_state,
    sign_state,
    verify_state,
)
from src.auth.tokens import create_access_token
from src.config import settings
from src.models import GoogleCompletionRecord, OAuthAccount, User

router = APIRouter(prefix="/api/v1/auth", tags=["google-sso"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_redirect_uri(request: Request) -> str:
    """Compute backend callback URL, preferring the explicit config value."""
    if settings.google.redirect_uri:
        return settings.google.redirect_uri
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/auth/google/callback"


def _get_frontend_base() -> str:
    """Return the frontend base URL for post-callback redirects."""
    url = settings.google.frontend_url or settings.email.app_url
    return url.rstrip("/")


def _set_auth_cookie(
    response: Response,
    name: str,
    value: str,
    max_age: int,
    path: str,
) -> None:
    """Set a short-lived HTTP-only SameSite=Lax cookie; adds Secure in production."""
    is_secure = not settings.auth.dev_mode
    response.set_cookie(
        key=name,
        value=value,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        max_age=max_age,
        path=path,
    )


# ---------------------------------------------------------------------------
# Public config endpoint
# ---------------------------------------------------------------------------

@router.get("/config")
async def auth_config() -> dict:
    """Return public auth feature-flag state (used by frontend to show/hide Google button)."""
    return {"google_sso_enabled": settings.google.is_ready}


# ---------------------------------------------------------------------------
# Step 1: start
# ---------------------------------------------------------------------------

@router.get("/google/start")
async def google_start(request: Request) -> RedirectResponse:
    """Initiate Google OAuth2 flow — redirects the browser to Google's auth endpoint."""
    if not settings.google.is_ready:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "google_oauth_unavailable", "message": "Google SSO is not configured for this environment."},
        )

    raw_state = generate_state()
    nonce = generate_nonce()
    signed_state = sign_state(raw_state, settings.auth.secret_key)

    redirect_uri = _get_redirect_uri(request)
    auth_url = build_auth_url(
        client_id=settings.google.client_id,
        redirect_uri=redirect_uri,
        state=signed_state,
        nonce=nonce,
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    # HTTP-only cookies scoped to the callback path only
    _set_auth_cookie(
        response, "google_oauth_state", raw_state,
        max_age=600, path="/api/v1/auth/google/callback",
    )
    _set_auth_cookie(
        response, "google_oauth_nonce", nonce,
        max_age=600, path="/api/v1/auth/google/callback",
    )
    return response


# ---------------------------------------------------------------------------
# Step 2: callback
# ---------------------------------------------------------------------------

@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Receive Google OAuth2 callback, validate, resolve user, create completion record."""
    frontend_base = _get_frontend_base()
    err_base = f"{frontend_base}/auth/google/callback?error="

    if not settings.google.is_ready:
        return RedirectResponse(url=f"{err_base}google_oauth_app_not_ready", status_code=302)

    # Provider-level error (user cancelled, etc.)
    if error:
        return RedirectResponse(url=f"{err_base}google_oauth_access_denied", status_code=302)

    if not code or not state:
        return RedirectResponse(url=f"{err_base}invalid_request", status_code=302)

    # --- Validate state ---
    cookie_state = request.cookies.get("google_oauth_state")
    cookie_nonce = request.cookies.get("google_oauth_nonce")

    if not cookie_state or not cookie_nonce:
        return RedirectResponse(url=f"{err_base}missing_cookies", status_code=302)

    if not verify_state(state, cookie_state, settings.auth.secret_key):
        return RedirectResponse(url=f"{err_base}invalid_state", status_code=302)

    # --- Exchange code and validate identity claims ---
    try:
        redirect_uri = _get_redirect_uri(request)
        claims = await exchange_code_and_validate(
            code=code,
            redirect_uri=redirect_uri,
            nonce=cookie_nonce,
            client_id=settings.google.client_id,
            client_secret=settings.google.client_secret,
        )
    except ValueError as exc:
        err_msg = str(exc)
        if "nonce" in err_msg:
            return RedirectResponse(url=f"{err_base}invalid_nonce", status_code=302)
        if "unverified_email" in err_msg or "missing_email" in err_msg:
            return RedirectResponse(url=f"{err_base}unverified_email", status_code=302)
        return RedirectResponse(url=f"{err_base}identity_error", status_code=302)
    except Exception:
        return RedirectResponse(url=f"{err_base}exchange_failed", status_code=302)

    # --- Resolve or create local user under the locked linking rules ---
    try:
        user = await _resolve_or_create_user(db, claims)
    except _AccountDisabledError:
        return RedirectResponse(url=f"{err_base}account_disabled", status_code=302)
    except _LinkConflictError:
        return RedirectResponse(url=f"{err_base}link_conflict", status_code=302)

    # --- Create one-time completion record ---
    flow_id = secrets.token_urlsafe(16)        # public — safe in URL
    completion_id = secrets.token_urlsafe(32)  # secret — HTTP-only cookie only
    completion_id_hash = hashlib.sha256(completion_id.encode()).hexdigest()

    now = _utcnow()
    db.add(GoogleCompletionRecord(
        flow_id=flow_id,
        completion_id_hash=completion_id_hash,
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    ))
    await db.commit()

    # Redirect browser to frontend completion page with the non-secret flow_id
    response = RedirectResponse(
        url=f"{frontend_base}/auth/google/callback?flow_id={flow_id}",
        status_code=302,
    )
    # Completion cookie: secret, HTTP-only, scoped to exchange endpoint only
    _set_auth_cookie(
        response, "google_completion", completion_id,
        max_age=300, path="/api/v1/auth/google/exchange",
    )
    # Clear state/nonce cookies — single-use
    response.delete_cookie("google_oauth_state", path="/api/v1/auth/google/callback")
    response.delete_cookie("google_oauth_nonce", path="/api/v1/auth/google/callback")
    return response


# ---------------------------------------------------------------------------
# Step 3: exchange
# ---------------------------------------------------------------------------

@router.post("/google/exchange")
async def google_exchange(
    request: Request,
    response: Response,
    body: GoogleExchangeRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Consume one-time completion record and return the standard AuthResponse JWT."""
    if not settings.google.is_ready:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "google_oauth_unavailable", "message": "Google SSO is not configured for this environment."},
        )

    completion_id = request.cookies.get("google_completion")
    if not completion_id:
        raise HTTPException(status_code=400, detail="Missing completion cookie")

    now = _utcnow()
    result = await db.execute(
        select(GoogleCompletionRecord).where(
            GoogleCompletionRecord.flow_id == body.flow_id,
            GoogleCompletionRecord.consumed_at.is_(None),
            GoogleCompletionRecord.expires_at > now,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=400, detail="Invalid or expired completion state")

    # Constant-time comparison — validates browser cookie ownership
    expected_hash = hashlib.sha256(completion_id.encode()).hexdigest()
    if not hmac.compare_digest(expected_hash, record.completion_id_hash):
        raise HTTPException(status_code=400, detail="Completion authentication failed")

    # Single-use: mark consumed immediately
    record.consumed_at = now
    await db.commit()

    # Re-check user at exchange time (disabled check must apply here too)
    user_result = await db.execute(select(User).where(User.id == record.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.disabled_at is not None:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "account_disabled",
                    "message": "Your account has been disabled. Contact support."},
        )

    token = create_access_token(user.id)

    # Clear completion cookie after successful exchange
    response.delete_cookie("google_completion", path="/api/v1/auth/google/exchange")

    return AuthResponse(
        access_token=token,
        user=UserProfile.model_validate(user),
    )


# ---------------------------------------------------------------------------
# Account resolution helpers — implement locked linking precedence rules
# ---------------------------------------------------------------------------

class _AccountDisabledError(Exception):
    pass


class _LinkConflictError(Exception):
    pass


async def _resolve_or_create_user(db: AsyncSession, claims: GoogleClaims) -> User:
    """Return the local User for this Google identity, creating or linking as required.

    Precedence (locked by architecture):
      1. Provider-link lookup: oauth_accounts(provider=google, provider_user_id=sub)
         → use only that linked user; no email fallback on this path.
      2. Email fallback (only when no provider link exists for this sub):
         - Disabled email-matched user → fail.
         - Email already linked to a different Google sub → link-conflict fail.
         - Email match with no Google link → create oauth_accounts link.
      3. No match anywhere → create new user (password_hash=None) + oauth_accounts.

    Raises:
        _AccountDisabledError: disabled user on any path.
        _LinkConflictError: email matches a user already linked to a different Google sub.
    """
    # Step 1 — provider-link-first lookup
    link_result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google",
            OAuthAccount.provider_user_id == claims.sub,
        )
    )
    link = link_result.scalar_one_or_none()
    if link is not None:
        user_result = await db.execute(select(User).where(User.id == link.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or user.disabled_at is not None:
            raise _AccountDisabledError()
        link.last_login_at = _utcnow()
        await db.commit()
        await db.refresh(user)
        return user

    # Step 2 — email fallback (no provider link for this sub)
    email_result = await db.execute(select(User).where(User.email == claims.email))
    existing_user = email_result.scalar_one_or_none()
    if existing_user is not None:
        if existing_user.disabled_at is not None:
            raise _AccountDisabledError()
        # Check whether this user already has a Google link to a DIFFERENT sub
        conflict_result = await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == existing_user.id,
                OAuthAccount.provider == "google",
            )
        )
        existing_link = conflict_result.scalar_one_or_none()
        if existing_link is not None:
            # Different sub — fail with link-conflict (not the path that reaches step 1)
            raise _LinkConflictError()
        # Auto-link: attach Google identity to this existing user
        db.add(OAuthAccount(
            user_id=existing_user.id,
            provider="google",
            provider_user_id=claims.sub,
            provider_email=claims.email,
            provider_email_verified=claims.email_verified,
            last_login_at=_utcnow(),
        ))
        await db.commit()
        await db.refresh(existing_user)
        return existing_user

    # Step 3 — no match; create new local user + link
    new_user = User(
        email=claims.email,
        display_name=claims.name or claims.email.split("@")[0],
        password_hash=None,  # Google-only account — no password set
    )
    db.add(new_user)
    await db.flush()  # populate new_user.id before inserting OAuthAccount
    db.add(OAuthAccount(
        user_id=new_user.id,
        provider="google",
        provider_user_id=claims.sub,
        provider_email=claims.email,
        provider_email_verified=claims.email_verified,
        last_login_at=_utcnow(),
    ))
    await db.commit()
    await db.refresh(new_user)
    return new_user
