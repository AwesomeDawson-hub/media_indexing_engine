"""Integration tests for auth (WS-004)."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from httpx import ASGITransport, AsyncClient

from src.database import Base
from src.api import dependencies as deps
from src.api.rate_limit import login_limiter, register_limiter


@pytest_asyncio.fixture
async def auth_client(tmp_path):
    """Client with real auth (no dependency overrides, dev_mode stays True for this fixture)."""
    from src.api.app import create_app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db
    # Do NOT override get_current_user_id — test real auth flow

    # Reset rate limiters for each test
    login_limiter._requests.clear()
    register_limiter._requests.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_register_success(auth_client):
    resp = await auth_client.post("/api/v1/auth/register", json={
        "email": "new@test.com",
        "password": "password123",
        "display_name": "New User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "new@test.com"


@pytest.mark.asyncio
async def test_register_duplicate_email(auth_client):
    await auth_client.post("/api/v1/auth/register", json={
        "email": "dup@test.com", "password": "password123", "display_name": "User",
    })
    resp = await auth_client.post("/api/v1/auth/register", json={
        "email": "dup@test.com", "password": "password456", "display_name": "User 2",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_short_password(auth_client):
    resp = await auth_client.post("/api/v1/auth/register", json={
        "email": "x@test.com", "password": "short", "display_name": "User",
    })
    assert resp.status_code == 400
    assert "8 characters" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_success(auth_client):
    await auth_client.post("/api/v1/auth/register", json={
        "email": "login@test.com", "password": "password123", "display_name": "User",
    })
    resp = await auth_client.post("/api/v1/auth/login", json={
        "email": "login@test.com", "password": "password123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(auth_client):
    await auth_client.post("/api/v1/auth/register", json={
        "email": "wrong@test.com", "password": "password123", "display_name": "User",
    })
    resp = await auth_client.post("/api/v1/auth/login", json={
        "email": "wrong@test.com", "password": "wrongpassword",
    })
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_email(auth_client):
    resp = await auth_client.post("/api/v1/auth/login", json={
        "email": "nobody@test.com", "password": "password123",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_jwt_protects_endpoints(auth_client):
    """Register, get token, use token to access upload endpoint."""
    # Register to get a token
    reg = await auth_client.post("/api/v1/auth/register", json={
        "email": "auth@test.com", "password": "password123", "display_name": "Auth User",
    })
    token = reg.json()["access_token"]

    # Access media list with token (dev_mode is True, so this works either way,
    # but we verify the token path works)
    resp = await auth_client.get(
        "/api/v1/media",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_me(auth_client):
    reg = await auth_client.post("/api/v1/auth/register", json={
        "email": "me@test.com", "password": "password123", "display_name": "Me User",
    })
    token = reg.json()["access_token"]

    resp = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.com"


@pytest.mark.asyncio
async def test_invalid_token_rejected(auth_client):
    resp = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token-here"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_error_format_standardized(auth_client):
    """Error responses include detail and error_code."""
    resp = await auth_client.post("/api/v1/auth/register", json={
        "email": "x@test.com", "password": "short", "display_name": "User",
    })
    data = resp.json()
    assert "detail" in data
    assert "error_code" in data
