"""P12-001: Google OAuth Production-Readiness — locked error vocabulary tests.

Validates that the five canonical identifiers introduced in P12-001 are emitted
consistently from the relevant backend endpoints. These tests are intentionally
narrow: they exercise the readiness-gate and consent-denial paths only.

Covered identifiers:
  google_oauth_unavailable       — operator config missing / connector not enabled
  google_oauth_app_not_ready     — SSO is_ready=False at callback time
  google_oauth_access_denied     — provider returned error=access_denied
  (google_drive_reconnect_required / google_drive_scope_upgrade_required are
   frontend-derived state labels; no dedicated backend endpoint change for P12-001)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api import dependencies as deps
from src.config import GoogleAuthConfig, GoogleDriveConfig, settings
from src.database import Base
from tests.conftest import DEV_USER_1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def _sso_db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def _sso_db_factory(_sso_db_engine):
    return async_sessionmaker(_sso_db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def sso_ready_client(_sso_db_factory):
    """AsyncClient with Google SSO fully enabled."""
    from src.api.app import create_app

    _config = GoogleAuthConfig(
        enabled=True,
        client_id="test-client-id",
        client_secret="test-client-secret",
        frontend_url="http://frontend",
    )

    async def override_get_db():
        async with _sso_db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db

    with patch.object(settings, "google", _config):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def drive_disabled_client(db_engine, db_session_factory, seed_users, monkeypatch):
    """Authenticated client — Drive connector explicitly disabled."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", False)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", "")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", "")
    from src.api.app import create_app

    test_session_factory = db_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    async def override_get_user():
        return DEV_USER_1

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_id] = override_get_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# SSO — /google/start (503 with structured error_code)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sso_start_disabled_returns_google_oauth_unavailable():
    """GET /google/start with SSO disabled returns 503 with error_code: google_oauth_unavailable."""
    from src.api.app import create_app

    app = create_app()
    with patch.object(settings, "google", GoogleAuthConfig(enabled=False)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/auth/google/start", follow_redirects=False)

    assert resp.status_code == 503
    body = resp.json()
    # Custom error handler flattens dict detail: error_code is a top-level key
    assert body["error_code"] == "google_oauth_unavailable"


# ---------------------------------------------------------------------------
# SSO — /google/exchange (503 with structured error_code)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sso_exchange_disabled_returns_google_oauth_unavailable():
    """POST /google/exchange with SSO disabled returns 503 with error_code: google_oauth_unavailable."""
    from src.api.app import create_app

    app = create_app()
    with patch.object(settings, "google", GoogleAuthConfig(enabled=False)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/v1/auth/google/exchange", json={"flow_id": "test-flow-id"})

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_code"] == "google_oauth_unavailable"


# ---------------------------------------------------------------------------
# SSO — /google/callback (locked redirect codes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sso_callback_not_ready_redirects_google_oauth_app_not_ready():
    """Callback hit when SSO is_ready=False redirects with google_oauth_app_not_ready."""
    from src.api.app import create_app

    # SSO enabled but client_id missing → is_ready=False
    not_ready_config = GoogleAuthConfig(enabled=True, client_id="", client_secret="")
    app = create_app()
    with patch.object(settings, "google", not_ready_config):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                "/api/v1/auth/google/callback",
                params={"code": "code", "state": "state"},
                follow_redirects=False,
            )

    assert resp.status_code == 302
    assert "error=google_oauth_app_not_ready" in resp.headers["location"]


@pytest.mark.asyncio
async def test_sso_callback_access_denied_redirects_google_oauth_access_denied(sso_ready_client):
    """Callback with error=access_denied from provider redirects with google_oauth_access_denied."""
    resp = await sso_ready_client.get(
        "/api/v1/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "error=google_oauth_access_denied" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Drive — /connector/google-drive/start (503 with structured error_code)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_start_not_ready_returns_google_oauth_unavailable(drive_disabled_client):
    """POST drive start with connector disabled returns 503 error_code: google_oauth_unavailable."""
    # Create a source first
    src_resp = await drive_disabled_client.post(
        "/api/v1/sources", json={"name": "Test Source", "source_type": "manual"}
    )
    assert src_resp.status_code == 201
    source_id = src_resp.json()["id"]

    resp = await drive_disabled_client.post(
        f"/api/v1/sources/{source_id}/connector/google-drive/start"
    )

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_code"] == "google_oauth_unavailable"


# ---------------------------------------------------------------------------
# Drive — /connectors/google-drive/quick-connect (503 with structured error_code)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_quick_connect_not_ready_returns_google_oauth_unavailable(drive_disabled_client):
    """POST quick-connect with connector disabled returns 503 error_code: google_oauth_unavailable."""
    resp = await drive_disabled_client.post(
        "/api/v1/connectors/google-drive/quick-connect",
        json={"source_name": "My Drive"},
    )

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_code"] == "google_oauth_unavailable"


# ---------------------------------------------------------------------------
# Drive — /connectors/google-drive/callback (locked redirect codes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_callback_not_ready_redirects_google_oauth_unavailable():
    """Drive callback hit when connector is_ready=False redirects with google_oauth_unavailable."""
    from src.api.app import create_app

    app = create_app()
    # Default GoogleDriveConfig has enabled=False → is_ready=False
    with patch.object(settings, "google_drive", GoogleDriveConfig(enabled=False)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                "/api/v1/connectors/google-drive/callback",
                params={"code": "code", "state": "state"},
                follow_redirects=False,
            )

    assert resp.status_code == 302
    assert "connector_result=error" in resp.headers["location"]
    assert "error_code=google_oauth_unavailable" in resp.headers["location"]
