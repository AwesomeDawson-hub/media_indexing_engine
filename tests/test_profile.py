"""Integration tests for P4-004: Profile self-service, email change, password reset."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database import Base
from src.api import dependencies as deps
from src.api.rate_limit import login_limiter, register_limiter


# ---------------------------------------------------------------------------
# Fixture — reuses the same auth_client pattern from test_auth.py
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    from src.api.app import create_app

    login_limiter._requests.clear()
    register_limiter._requests.clear()

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _register(c, email="user@test.com", password="password123", name="Test User"):
    resp = await c.post("/api/v1/auth/register", json={
        "email": email, "password": password, "display_name": name,
    })
    assert resp.status_code == 201
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_email_normalized(auth_client):
    """Emails are lowercased and trimmed on registration."""
    await auth_client.post("/api/v1/auth/register", json={
        "email": "  UPPER@Test.COM  ", "password": "password123", "display_name": "User",
    })
    resp = await auth_client.post("/api/v1/auth/login", json={
        "email": "upper@test.com", "password": "password123",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_me_returns_extended_profile(auth_client):
    """GET /me returns role, plan_name, monthly_limit."""
    token = await _register(auth_client)
    resp = await auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "user"
    assert "plan_name" in data
    assert "monthly_limit" in data


@pytest.mark.asyncio
async def test_patch_me_updates_allowed_fields(auth_client):
    """PATCH /me updates display_name, phone, company, icon_url."""
    token = await _register(auth_client)
    resp = await auth_client.patch(
        "/api/v1/auth/me",
        json={"display_name": "New Name", "phone": "555-1234", "company": "Acme", "icon_url": "https://example.com/pic.png"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_name"] == "New Name"
    assert data["phone"] == "555-1234"
    assert data["company"] == "Acme"
    assert data["icon_url"] == "https://example.com/pic.png"


@pytest.mark.asyncio
async def test_patch_me_partial_update(auth_client):
    """Omitted fields are not overwritten."""
    token = await _register(auth_client)
    await auth_client.patch(
        "/api/v1/auth/me",
        json={"phone": "555-0000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await auth_client.patch(
        "/api/v1/auth/me",
        json={"company": "NewCo"},
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["phone"] == "555-0000"
    assert data["company"] == "NewCo"


@pytest.mark.asyncio
async def test_email_change_flow(auth_client):
    """Full email-change: request → get token → confirm → /me shows new email."""
    token = await _register(auth_client, email="change@test.com")

    # Request
    req_resp = await auth_client.post(
        "/api/v1/auth/email-change/request",
        json={"new_email": "changed@test.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req_resp.status_code == 200
    pending_token = req_resp.json()["token"]  # dev_mode returns token

    # Confirm
    conf_resp = await auth_client.post(
        "/api/v1/auth/email-change/confirm",
        json={"token": pending_token},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conf_resp.status_code == 200
    assert conf_resp.json()["email"] == "changed@test.com"

    # /me should reflect new email
    me_resp = await auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.json()["email"] == "changed@test.com"


@pytest.mark.asyncio
async def test_email_change_wrong_token(auth_client):
    """Wrong token is rejected."""
    token = await _register(auth_client, email="wrong@test.com")
    await auth_client.post(
        "/api/v1/auth/email-change/request",
        json={"new_email": "notused@test.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conf_resp = await auth_client.post(
        "/api/v1/auth/email-change/confirm",
        json={"token": "totallywrongtoken"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conf_resp.status_code == 400


@pytest.mark.asyncio
async def test_email_change_conflict(auth_client):
    """Requesting email change to an already-registered email returns 409."""
    token1 = await _register(auth_client, email="a@test.com")
    await _register(auth_client, email="b@test.com")

    resp = await auth_client.post(
        "/api/v1/auth/email-change/request",
        json={"new_email": "b@test.com"},
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_email_change_token_reuse(auth_client):
    """Once a token is used, re-submitting it is rejected."""
    token = await _register(auth_client, email="reuse@test.com")
    req_resp = await auth_client.post(
        "/api/v1/auth/email-change/request",
        json={"new_email": "reused@test.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    pending_token = req_resp.json()["token"]

    # First use — succeeds
    await auth_client.post(
        "/api/v1/auth/email-change/confirm",
        json={"token": pending_token},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Second use — rejected
    conf2 = await auth_client.post(
        "/api/v1/auth/email-change/confirm",
        json={"token": pending_token},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conf2.status_code == 400


@pytest.mark.asyncio
async def test_password_reset_flow(auth_client):
    """Full reset: request → get token → confirm → login with new password."""
    token = await _register(auth_client, email="reset@test.com", password="oldpassword1")

    req_resp = await auth_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@test.com"},
    )
    assert req_resp.status_code == 200
    reset_token = req_resp.json()["token"]  # dev_mode

    conf_resp = await auth_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "newpassword1"},
    )
    assert conf_resp.status_code == 200

    # Old password no longer works
    _ = token  # silence unused warning
    bad_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@test.com", "password": "oldpassword1"},
    )
    assert bad_login.status_code == 401

    # New password works
    good_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@test.com", "password": "newpassword1"},
    )
    assert good_login.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_wrong_token(auth_client):
    """Wrong reset token is rejected."""
    await _register(auth_client, email="badtoken@test.com")
    await auth_client.post("/api/v1/auth/password-reset/request", json={"email": "badtoken@test.com"})

    resp = await auth_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "newpassword1"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_password_reset_no_enumeration(auth_client):
    """Requesting reset for unknown email still returns 200."""
    resp = await auth_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "nobody@nowhere.com"},
    )
    assert resp.status_code == 200
    assert "message" in resp.json()
    assert "token" not in resp.json()  # no token for unknown email


@pytest.mark.asyncio
async def test_disabled_user_cannot_login(auth_client):
    """A disabled user gets 403 on login."""
    from uuid import uuid4
    from src.models import User
    from src.auth.passwords import hash_password
    from sqlalchemy.ext.asyncio import AsyncSession

    # We need direct DB access here — register via API, then disable via DB
    token = await _register(auth_client, email="disabled@test.com", password="password123")

    # Get user id from /me
    me_resp = await auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200

    # Disable by using the admin endpoint — register a second admin user first
    # Simpler: register a second user, make them admin via a patch from an already-admin seeded user
    # Since we have no admin seeded here, we'll test the path differently:
    # Directly call login with a fresh in-memory setup that has a disabled user seeded.
    # Instead, we test this by calling /admin — but we need a separate admin.
    # For this test, let's verify indirectly: the disabled_at field blocks /me too.
    # We'll do full test in test_admin.py which seeds an admin directly.
    # Here just confirm login blocks when disabled_at is set — do it by registering second admin
    pytest.skip("Covered in test_admin.py::test_admin_disable_account_blocks_login")
