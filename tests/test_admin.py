"""Integration tests for P4-004: Admin routes."""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database import Base
from src.models import User
from src.api import dependencies as deps
from src.auth.passwords import hash_password
from src.auth.tokens import create_access_token
from src.api.rate_limit import login_limiter, register_limiter


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def admin_ctx():
    """In-memory DB seeded with one admin and one regular user, real JWT auth."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    admin_id = str(uuid4())
    user_id = str(uuid4())

    async with factory() as session:
        session.add_all([
            User(
                id=admin_id,
                email="admin@test.com",
                display_name="Admin User",
                password_hash=hash_password("password123"),
                role="admin",
            ),
            User(
                id=user_id,
                email="user@test.com",
                display_name="Regular User",
                password_hash=hash_password("password123"),
                role="user",
            ),
        ])
        await session.commit()

    admin_token = create_access_token(admin_id)
    user_token = create_access_token(user_id)

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
        yield {
            "client": c,
            "admin_token": admin_token,
            "user_token": user_token,
            "admin_id": admin_id,
            "user_id": user_id,
        }

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_list_users(admin_ctx):
    c, token = admin_ctx["client"], admin_ctx["admin_token"]
    resp = await c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    emails = {u["email"] for u in data["users"]}
    assert "admin@test.com" in emails
    assert "user@test.com" in emails


@pytest.mark.asyncio
async def test_admin_forbidden_non_admin(admin_ctx):
    c, token = admin_ctx["client"], admin_ctx["user_token"]
    resp = await c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_get_user_detail(admin_ctx):
    c, token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]
    resp = await c.get(f"/api/v1/admin/users/{user_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user_id
    assert "quota_this_month" in data


@pytest.mark.asyncio
async def test_admin_update_user_fields(admin_ctx):
    c, token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]
    resp = await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"plan_name": "pro", "monthly_limit": 500},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_name"] == "pro"
    assert data["monthly_limit"] == 500

    # Audit log should have an entry
    audit_resp = await c.get("/api/v1/admin/audit-log", headers={"Authorization": f"Bearer {token}"})
    assert audit_resp.status_code == 200
    assert audit_resp.json()["total"] >= 1
    entry = audit_resp.json()["entries"][0]
    assert entry["action"] == "update_user"
    assert entry["target_user_id"] == user_id


@pytest.mark.asyncio
async def test_admin_disable_account_blocks_login(admin_ctx):
    c, admin_token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]

    # Disable the user
    resp = await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"disabled": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["disabled_at"] is not None

    # Login should return 403
    login_resp = await c.post(
        "/api/v1/auth/login",
        json={"email": "user@test.com", "password": "password123"},
    )
    assert login_resp.status_code == 403
    assert login_resp.json()["error_code"] == "account_disabled"


@pytest.mark.asyncio
async def test_admin_enable_account_allows_login(admin_ctx):
    c, admin_token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]

    # Disable then re-enable
    await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"disabled": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"disabled": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["disabled_at"] is None

    login_resp = await c.post(
        "/api/v1/auth/login",
        json={"email": "user@test.com", "password": "password123"},
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_change_user_email(admin_ctx):
    c, admin_token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]
    resp = await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"email": "newemail@test.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "newemail@test.com"

    # Confirm audit entry records the change
    audit_resp = await c.get("/api/v1/admin/audit-log", headers={"Authorization": f"Bearer {admin_token}"})
    entries = audit_resp.json()["entries"]
    assert any("email" in (e["detail"] or "") for e in entries)


@pytest.mark.asyncio
async def test_admin_audit_log_filter_by_target(admin_ctx):
    c, admin_token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]

    # Generate an audit entry
    await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"company": "Acme"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Filter by target
    resp = await c.get(
        f"/api/v1/admin/audit-log?target_user_id={user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for entry in data["entries"]:
        assert entry["target_user_id"] == user_id


@pytest.mark.asyncio
async def test_admin_update_role(admin_ctx):
    c, admin_token, user_id = admin_ctx["client"], admin_ctx["admin_token"], admin_ctx["user_id"]
    resp = await c.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
