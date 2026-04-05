"""Integration tests for Google SSO endpoints (P6-001)."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api import dependencies as deps
from src.auth.google_oauth import GoogleClaims
from src.config import GoogleAuthConfig, settings
from src.database import Base
from src.models import GoogleCompletionRecord, OAuthAccount, User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOOGLE_CONFIG_READY = GoogleAuthConfig(
    enabled=True,
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="http://test/api/v1/auth/google/callback",
    frontend_url="http://frontend",
)

SAMPLE_CLAIMS = GoogleClaims(
    sub="google-sub-001",
    email="ssouser@example.com",
    email_verified=True,
    name="SSO User",
    picture="https://example.com/pic.jpg",
)


@pytest_asyncio.fixture
async def sso_db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sso_db_factory(sso_db_engine):
    return async_sessionmaker(sso_db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def sso_client(sso_db_factory) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient backed by test DB with Google SSO enabled via settings patch."""
    from src.api.app import create_app

    async def override_get_db():
        async with sso_db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db
    # Note: Google routes don't use get_current_user_id — no auth override needed

    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def sso_db(sso_db_factory) -> AsyncGenerator[AsyncSession, None]:
    async with sso_db_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _do_start_and_get_cookies(sso_client: AsyncClient) -> dict[str, str]:
    """Perform /google/start and extract state+nonce cookies."""
    resp = await sso_client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert resp.status_code == 302
    cookies: dict[str, str] = {}
    for header_val in resp.headers.get_list("set-cookie"):
        if "google_oauth_state=" in header_val:
            cookies["google_oauth_state"] = header_val.split("google_oauth_state=")[1].split(";")[0]
        if "google_oauth_nonce=" in header_val:
            cookies["google_oauth_nonce"] = header_val.split("google_oauth_nonce=")[1].split(";")[0]
    return cookies


# ---------------------------------------------------------------------------
# /api/v1/auth/config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_config_google_enabled(sso_client):
    resp = await sso_client.get("/api/v1/auth/config")
    assert resp.status_code == 200
    assert resp.json()["google_sso_enabled"] is True


@pytest.mark.asyncio
async def test_config_google_disabled():
    from src.api.app import create_app
    app = create_app()
    with patch.object(settings, "google", GoogleAuthConfig(enabled=False)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/auth/config")
    assert resp.status_code == 200
    assert resp.json()["google_sso_enabled"] is False


# ---------------------------------------------------------------------------
# GET /google/start
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_redirects_to_google(sso_client):
    resp = await sso_client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["location"]


@pytest.mark.asyncio
async def test_start_sets_state_and_nonce_cookies(sso_client):
    cookies = await _do_start_and_get_cookies(sso_client)
    assert "google_oauth_state" in cookies
    assert "google_oauth_nonce" in cookies
    assert len(cookies["google_oauth_state"]) > 10
    assert len(cookies["google_oauth_nonce"]) > 10


@pytest.mark.asyncio
async def test_start_disabled_returns_503():
    from src.api.app import create_app
    app = create_app()
    with patch.object(settings, "google", GoogleAuthConfig(enabled=False)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/auth/google/start", follow_redirects=False)
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /google/callback — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_happy_path_new_user(sso_client, sso_db):
    """Full flow: start → callback → check completion record created."""
    # Step 1: start — get signed state and cookies
    start_resp = await sso_client.get("/api/v1/auth/google/start", follow_redirects=False)
    location = start_resp.headers["location"]
    # Extract signed state from redirect URL
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(location)
    qs = parse_qs(parsed.query)
    signed_state = qs["state"][0]
    # Get raw state from cookie
    raw_cookies: dict[str, str] = {}
    for hv in start_resp.headers.get_list("set-cookie"):
        if "google_oauth_state=" in hv:
            raw_cookies["google_oauth_state"] = hv.split("google_oauth_state=")[1].split(";")[0]
        if "google_oauth_nonce=" in hv:
            raw_cookies["google_oauth_nonce"] = hv.split("google_oauth_nonce=")[1].split(";")[0]

    # Step 2: callback with mocked exchange
    with patch(
        "src.api.routes.google_auth.exchange_code_and_validate",
        new=AsyncMock(return_value=SAMPLE_CLAIMS),
    ):
        with patch.object(settings, "google", GOOGLE_CONFIG_READY):
            resp = await sso_client.get(
                "/api/v1/auth/google/callback",
                params={"code": "test-code", "state": signed_state},
                cookies=raw_cookies,
                follow_redirects=False,
            )
    assert resp.status_code == 302
    redirect_loc = resp.headers["location"]
    assert "flow_id=" in redirect_loc
    assert "error" not in redirect_loc


@pytest.mark.asyncio
async def test_callback_error_param_redirects_to_frontend(sso_client):
    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.get(
            "/api/v1/auth/google/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=oauth_error" in resp.headers["location"]


@pytest.mark.asyncio
async def test_callback_missing_cookies_redirects(sso_client):
    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "test-code", "state": "some-state"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=missing_cookies" in resp.headers["location"]


@pytest.mark.asyncio
async def test_callback_invalid_state_redirects(sso_client):
    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        with patch("src.api.routes.google_auth.verify_state", return_value=False):
            resp = await sso_client.get(
                "/api/v1/auth/google/callback",
                params={"code": "test-code", "state": "bad-state"},
                cookies={"google_oauth_state": "stale", "google_oauth_nonce": "nonce"},
                follow_redirects=False,
            )
    assert resp.status_code == 302
    assert "error=invalid_state" in resp.headers["location"]


@pytest.mark.asyncio
async def test_callback_exchange_failure_redirects(sso_client):
    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        with patch("src.api.routes.google_auth.verify_state", return_value=True):
            with patch(
                "src.api.routes.google_auth.exchange_code_and_validate",
                new=AsyncMock(side_effect=ValueError("id_token_invalid")),
            ):
                resp = await sso_client.get(
                    "/api/v1/auth/google/callback",
                    params={"code": "bad-code", "state": "signed-state"},
                    cookies={"google_oauth_state": "raw", "google_oauth_nonce": "nonce"},
                    follow_redirects=False,
                )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# POST /google/exchange — happy path & failure modes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_happy_path(sso_client, sso_db):
    """Seed a valid completion record and confirm exchange returns AuthResponse."""
    # Create user + completion record directly in DB
    user = User(email="exchange@example.com", display_name="Exchange User", password_hash=None)
    sso_db.add(user)
    await sso_db.flush()

    completion_id = secrets.token_urlsafe(32)
    flow_id = secrets.token_urlsafe(16)
    now = _utcnow()
    record = GoogleCompletionRecord(
        flow_id=flow_id,
        completion_id_hash=hashlib.sha256(completion_id.encode()).hexdigest(),
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sso_db.add(record)
    await sso_db.commit()

    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.post(
            "/api/v1/auth/google/exchange",
            json={"flow_id": flow_id},
            cookies={"google_completion": completion_id},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "exchange@example.com"


@pytest.mark.asyncio
async def test_exchange_missing_cookie_returns_400(sso_client):
    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.post(
            "/api/v1/auth/google/exchange",
            json={"flow_id": "some-flow"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_exchange_wrong_completion_id_returns_400(sso_client, sso_db):
    user = User(email="wrong@example.com", display_name="Wrong", password_hash=None)
    sso_db.add(user)
    await sso_db.flush()

    flow_id = secrets.token_urlsafe(16)
    now = _utcnow()
    record = GoogleCompletionRecord(
        flow_id=flow_id,
        completion_id_hash=hashlib.sha256(b"correct-secret").hexdigest(),
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sso_db.add(record)
    await sso_db.commit()

    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.post(
            "/api/v1/auth/google/exchange",
            json={"flow_id": flow_id},
            cookies={"google_completion": "wrong-secret"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_exchange_expired_record_returns_400(sso_client, sso_db):
    user = User(email="expired@example.com", display_name="Expired", password_hash=None)
    sso_db.add(user)
    await sso_db.flush()

    completion_id = secrets.token_urlsafe(32)
    flow_id = secrets.token_urlsafe(16)
    now = _utcnow()
    record = GoogleCompletionRecord(
        flow_id=flow_id,
        completion_id_hash=hashlib.sha256(completion_id.encode()).hexdigest(),
        user_id=user.id,
        created_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),  # already expired
    )
    sso_db.add(record)
    await sso_db.commit()

    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.post(
            "/api/v1/auth/google/exchange",
            json={"flow_id": flow_id},
            cookies={"google_completion": completion_id},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_exchange_consumed_record_returns_400(sso_client, sso_db):
    """Single-use: a consumed record must be rejected."""
    user = User(email="consumed@example.com", display_name="Consumed", password_hash=None)
    sso_db.add(user)
    await sso_db.flush()

    completion_id = secrets.token_urlsafe(32)
    flow_id = secrets.token_urlsafe(16)
    now = _utcnow()
    record = GoogleCompletionRecord(
        flow_id=flow_id,
        completion_id_hash=hashlib.sha256(completion_id.encode()).hexdigest(),
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        consumed_at=now,  # already consumed
    )
    sso_db.add(record)
    await sso_db.commit()

    with patch.object(settings, "google", GOOGLE_CONFIG_READY):
        resp = await sso_client.post(
            "/api/v1/auth/google/exchange",
            json={"flow_id": flow_id},
            cookies={"google_completion": completion_id},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Account resolution (_resolve_or_create_user)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_creates_new_user(sso_db):
    from src.api.routes.google_auth import _resolve_or_create_user
    user = await _resolve_or_create_user(sso_db, SAMPLE_CLAIMS)
    assert user.email == SAMPLE_CLAIMS.email
    assert user.password_hash is None


@pytest.mark.asyncio
async def test_resolve_links_existing_email_user(sso_db):
    """Email-matched user without any Google link gets auto-linked."""
    from src.api.routes.google_auth import _resolve_or_create_user
    existing = User(email=SAMPLE_CLAIMS.email, display_name="Existing", password_hash="hashed")
    sso_db.add(existing)
    await sso_db.commit()

    user = await _resolve_or_create_user(sso_db, SAMPLE_CLAIMS)
    assert user.id == existing.id


@pytest.mark.asyncio
async def test_resolve_uses_existing_provider_link(sso_db):
    """Sub-matched user via provider link is returned directly."""
    from src.api.routes.google_auth import _resolve_or_create_user
    existing = User(email=SAMPLE_CLAIMS.email, display_name="Linked", password_hash=None)
    sso_db.add(existing)
    await sso_db.flush()
    link = OAuthAccount(
        user_id=existing.id,
        provider="google",
        provider_user_id=SAMPLE_CLAIMS.sub,
        provider_email=SAMPLE_CLAIMS.email,
        provider_email_verified=True,
    )
    sso_db.add(link)
    await sso_db.commit()

    user = await _resolve_or_create_user(sso_db, SAMPLE_CLAIMS)
    assert user.id == existing.id


@pytest.mark.asyncio
async def test_resolve_link_conflict_raises(sso_db):
    """Email matches a user already linked to a different Google sub → LinkConflict."""
    from src.api.routes.google_auth import _resolve_or_create_user, _LinkConflictError
    existing = User(email=SAMPLE_CLAIMS.email, display_name="Conflicted", password_hash=None)
    sso_db.add(existing)
    await sso_db.flush()
    link = OAuthAccount(
        user_id=existing.id,
        provider="google",
        provider_user_id="different-sub-999",
        provider_email=SAMPLE_CLAIMS.email,
        provider_email_verified=True,
    )
    sso_db.add(link)
    await sso_db.commit()

    with pytest.raises(_LinkConflictError):
        await _resolve_or_create_user(sso_db, SAMPLE_CLAIMS)


@pytest.mark.asyncio
async def test_resolve_disabled_user_raises(sso_db):
    from src.api.routes.google_auth import _resolve_or_create_user, _AccountDisabledError
    disabled = User(
        email=SAMPLE_CLAIMS.email,
        display_name="Disabled",
        password_hash=None,
        disabled_at=_utcnow(),
    )
    sso_db.add(disabled)
    await sso_db.commit()

    with pytest.raises(_AccountDisabledError):
        await _resolve_or_create_user(sso_db, SAMPLE_CLAIMS)
