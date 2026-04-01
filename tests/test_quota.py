"""Integration tests for P4-002: quota status endpoint, reservation lifecycle."""

import asyncio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import QuotaEvent, User
from tests.conftest import JPEG_BYTES, PNG_BYTES, DEV_USER_1


# ---------------------------------------------------------------------------
# GET /api/v1/quota/status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quota_status_default(client):
    """Unauthenticated representation still returns 200 (dev mode) with correct defaults."""
    resp = await client.get("/api/v1/quota/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_name"] == "basic"
    assert body["monthly_limit"] == 500
    assert body["consumed"] == 0
    assert body["reserved"] == 0
    assert body["remaining"] == 500
    # period_month is "YYYY-MM"
    import re
    assert re.match(r"^\d{4}-\d{2}$", body["period_month"])


@pytest.mark.asyncio
async def test_quota_status_reflects_consumption(client, db_engine):
    """After upload + analysis completes, consumed count increments and remaining decrements."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201

    # Wait for background analysis to complete
    await asyncio.sleep(0.6)

    resp = await client.get("/api/v1/quota/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["consumed"] == 1
    assert body["reserved"] == 0
    assert body["remaining"] == 499


@pytest.mark.asyncio
async def test_quota_status_is_user_scoped(client, client_user2, db_engine):
    """quota/status counts only events for the requesting user."""
    # User 1 uploads 2 files
    await client.post(
        "/api/v1/upload",
        files={"file": ("u1a.jpg", JPEG_BYTES, "image/jpeg")},
    )
    await client.post(
        "/api/v1/upload",
        files={"file": ("u1b.png", PNG_BYTES, "image/png")},
    )
    await asyncio.sleep(0.6)

    # User 2 uploads 1 file
    await client_user2.post(
        "/api/v1/upload",
        files={"file": ("u2a.jpg", JPEG_BYTES, "image/jpeg")},
    )
    await asyncio.sleep(0.4)

    # User 1 should see 2 consumed
    resp1 = await client.get("/api/v1/quota/status")
    assert resp1.status_code == 200
    assert resp1.json()["consumed"] == 2
    assert resp1.json()["remaining"] == 498

    # User 2 should see 1 consumed
    resp2 = await client_user2.get("/api/v1/quota/status")
    assert resp2.status_code == 200
    assert resp2.json()["consumed"] == 1
    assert resp2.json()["remaining"] == 499


# ---------------------------------------------------------------------------
# Reservation lifecycle: reserve -> consumed / released
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_success_transitions_reserved_to_consumed(client, db_engine):
    """Upload + completed analysis produces exactly one consumed quota event."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201

    await asyncio.sleep(0.6)

    # After analysis completes: exactly one consumed event, nothing else
    async with factory() as db:
        events = (await db.execute(select(QuotaEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "consumed", (
            "Reservation should transition to consumed after successful analysis"
        )


# ---------------------------------------------------------------------------
# Duplicate upload does not consume quota
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_upload_does_not_create_quota_event(client, db_engine):
    """A duplicate upload (same content hash) does not enqueue analysis and creates no quota event."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    resp1 = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp1.status_code == 201
    assert resp1.json()["is_duplicate"] is False

    await asyncio.sleep(0.6)

    # Duplicate upload
    resp2 = await client.post(
        "/api/v1/upload",
        files={"file": ("photo_again.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp2.status_code == 201
    assert resp2.json()["is_duplicate"] is True

    await asyncio.sleep(0.2)

    # Still only 1 quota event from the original upload
    async with factory() as db:
        events = (await db.execute(select(QuotaEvent))).scalars().all()
        assert len(events) == 1, "Duplicate uploads must not create additional quota events"
        assert events[0].event_type == "consumed"
