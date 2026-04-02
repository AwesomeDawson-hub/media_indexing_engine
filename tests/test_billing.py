"""Integration tests for P4-005: Billing routes and service."""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import stripe

from src.database import Base
from src.models import StripeEvent, User
from src.api import dependencies as deps
from src.auth.passwords import hash_password
from src.auth.tokens import create_access_token
from src.billing.billing_service import apply_subscription_event


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def billing_ctx():
    """In-memory DB with an admin and a regular user, both with JWTs."""
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
                display_name="Admin",
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
    from src.api.rate_limit import login_limiter, register_limiter
    login_limiter._requests.clear()
    register_limiter._requests.clear()

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield {
            "client": c,
            "factory": factory,
            "admin_token": admin_token,
            "user_token": user_token,
            "admin_id": admin_id,
            "user_id": user_id,
        }

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _make_subscription_event(
    event_id: str,
    event_type: str,
    customer_id: str,
    subscription_id: str,
    status: str = "active",
    price_id: str = "price_advanced",
    meta_user_id: str | None = None,
) -> stripe.Event:
    """Build a minimal synthetic Stripe Event object."""
    data = {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": subscription_id,
                "object": "subscription",
                "customer": customer_id,
                "status": status,
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": price_id,
                            }
                        }
                    ]
                },
                "metadata": {"user_id": meta_user_id or ""},
            }
        },
    }
    return stripe.Event.construct_from(data, "sk_test_placeholder")


# ---------------------------------------------------------------------------
# GET /api/v1/billing/status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_billing_status_unauthenticated(billing_ctx):
    client = billing_ctx["client"]
    r = await client.get("/api/v1/billing/status")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_billing_status_defaults(billing_ctx):
    client = billing_ctx["client"]
    token = billing_ctx["user_token"]
    r = await client.get(
        "/api/v1/billing/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["billing_status"] == "none"
    assert body["plan_name"] == "basic"
    assert body["monthly_limit"] == 500
    assert body["stripe_customer_id"] is None
    assert body["stripe_subscription_id"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/billing/create-checkout-session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_checkout_session_no_stripe_key(billing_ctx):
    """When Stripe is unconfigured (empty key), returns placeholder URL."""
    client = billing_ctx["client"]
    token = billing_ctx["user_token"]
    r = await client.post(
        "/api/v1/billing/create-checkout-session",
        json={"price_id": "price_advanced"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "checkout_url" in body
    assert "stripe.com" in body["checkout_url"]


@pytest.mark.asyncio
async def test_create_checkout_session_invalid_price(billing_ctx):
    """When configured price IDs are set, an unknown price_id returns 400."""
    client = billing_ctx["client"]
    token = billing_ctx["user_token"]
    from src.config import settings
    with patch.object(settings.stripe, "price_id_advanced", "price_real_advanced"), \
         patch.object(settings.stripe, "price_id_premium", "price_real_premium"):
        r = await client.post(
            "/api/v1/billing/create-checkout-session",
            json={"price_id": "price_wrong"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/billing/create-portal-session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_portal_session_no_customer(billing_ctx):
    client = billing_ctx["client"]
    token = billing_ctx["user_token"]
    r = await client.post(
        "/api/v1/billing/create-portal-session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_portal_session_with_customer(billing_ctx):
    factory = billing_ctx["factory"]
    user_id = billing_ctx["user_id"]
    # Give the user a stripe_customer_id
    async with factory() as session:
        user = await session.get(User, user_id)
        user.stripe_customer_id = "cus_test_123"
        await session.commit()

    client = billing_ctx["client"]
    token = billing_ctx["user_token"]
    r = await client.post(
        "/api/v1/billing/create-portal-session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "portal_url" in body
    assert "stripe.com" in body["portal_url"]


# ---------------------------------------------------------------------------
# POST /api/v1/billing/webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_subscription_created(billing_ctx):
    """Webhook with subscription.created updates user's plan and billing_status."""
    factory = billing_ctx["factory"]
    user_id = billing_ctx["user_id"]
    client = billing_ctx["client"]

    # Set the user's stripe customer id first
    async with factory() as session:
        user = await session.get(User, user_id)
        user.stripe_customer_id = "cus_webhook_test"
        await session.commit()

    event_payload = {
        "id": "evt_001",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_001",
                "object": "subscription",
                "customer": "cus_webhook_test",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_advanced"}}]},
                "metadata": {},
            }
        },
    }

    r = await client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.billing_status == "active"
        assert user.stripe_subscription_id == "sub_001"


@pytest.mark.asyncio
async def test_webhook_idempotency(billing_ctx):
    """Sending the same event twice does not create duplicate StripeEvent rows."""
    factory = billing_ctx["factory"]
    user_id = billing_ctx["user_id"]
    client = billing_ctx["client"]

    async with factory() as session:
        user = await session.get(User, user_id)
        user.stripe_customer_id = "cus_idempotency"
        await session.commit()

    event_payload = {
        "id": "evt_idempotent_001",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_idem",
                "object": "subscription",
                "customer": "cus_idempotency",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_premium"}}]},
                "metadata": {},
            }
        },
    }

    r1 = await client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    r2 = await client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    from sqlalchemy import select
    async with factory() as session:
        result = await session.execute(
            select(StripeEvent).where(StripeEvent.stripe_event_id == "evt_idempotent_001")
        )
        rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_webhook_subscription_deleted(billing_ctx):
    """subscription.deleted reverts user to basic plan."""
    factory = billing_ctx["factory"]
    user_id = billing_ctx["user_id"]
    client = billing_ctx["client"]

    async with factory() as session:
        user = await session.get(User, user_id)
        user.stripe_customer_id = "cus_deletion_test"
        user.plan_name = "premium"
        user.monthly_limit = 5000
        user.billing_status = "active"
        user.stripe_subscription_id = "sub_del"
        await session.commit()

    event_payload = {
        "id": "evt_del_001",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_del",
                "object": "subscription",
                "customer": "cus_deletion_test",
                "status": "canceled",
                "items": {"data": [{"price": {"id": "price_premium"}}]},
                "metadata": {},
            }
        },
    }

    r = await client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.plan_name == "basic"
        assert user.billing_status == "canceled"
        assert user.stripe_subscription_id is None
        assert user.monthly_limit == 500


@pytest.mark.asyncio
async def test_webhook_invalid_signature(billing_ctx):
    """When webhook_secret is set, a bad Stripe-Signature header returns 400."""
    client = billing_ctx["client"]
    from src.config import settings
    with patch.object(settings.stripe, "webhook_secret", "whsec_real_secret"):
        r = await client.post(
            "/api/v1/billing/webhook",
            content=b'{"id":"evt_bad","type":"test"}',
            headers={
                "Content-Type": "application/json",
                "stripe-signature": "t=bad,v1=badvalue",
            },
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Admin billing_status override
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_can_override_billing_status(billing_ctx):
    """PATCH /admin/users/{id} with billing_status updates the field and audits it."""
    client = billing_ctx["client"]
    admin_token = billing_ctx["admin_token"]
    user_id = billing_ctx["user_id"]
    factory = billing_ctx["factory"]

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"billing_status": "active"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["billing_status"] == "active"

    # Verify it persisted
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.billing_status == "active"


@pytest.mark.asyncio
async def test_admin_rejects_invalid_billing_status(billing_ctx):
    """PATCH with an invalid billing_status value returns 400."""
    client = billing_ctx["client"]
    admin_token = billing_ctx["admin_token"]
    user_id = billing_ctx["user_id"]

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"billing_status": "bogus_status"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400
