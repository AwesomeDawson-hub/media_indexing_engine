"""Integration tests for P3-003: Bulk Operations (reanalyze-batch and delete-batch)."""

import asyncio
from unittest.mock import patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import MediaItem, ProcessingJob, QuotaEvent, User
from src.storage.file_store import LocalFileStore
from tests.conftest import JPEG_BYTES, PNG_BYTES, DEV_USER_1, DEV_USER_2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _upload(client, content: bytes, name: str, mime: str) -> str:
    """Upload a file and return the media item ID."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": (name, content, mime)},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _upload_jpeg(client, name: str = "photo.jpg") -> str:
    """Upload a JPEG and return the media item ID."""
    return await _upload(client, JPEG_BYTES, name, "image/jpeg")


async def _upload_png(client, name: str = "photo.png") -> str:
    """Upload a PNG and return the media item ID."""
    return await _upload(client, PNG_BYTES, name, "image/png")


# ---------------------------------------------------------------------------
# POST /api/v1/media/reanalyze-batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reanalyze_batch_success(client, db_engine):
    """Batch re-analyze queues processing jobs for owned items (P11-001 response shape)."""
    # Upload two distinct items (different formats to avoid content-hash dedup)
    id1 = await _upload_jpeg(client, "img1.jpg")
    id2 = await _upload_png(client, "img2.png")

    # Wait briefly so any upload-triggered jobs settle
    await asyncio.sleep(0.2)

    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [id1, id2]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted_count"] >= 1
    assert body["queued_count"] >= 1
    assert body["request_count"] == 2
    assert len(body["outcomes"]) == 2
    accepted = [o for o in body["outcomes"] if o["outcome"] == "accepted"]
    assert len(accepted) >= 1

    # Verify at least one new pending job exists
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        pending = (await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.media_item_id.in_([id1, id2]),
            )
        )).scalars().all()
        assert len(pending) >= 1


@pytest.mark.asyncio
async def test_reanalyze_batch_empty_body(client):
    """Empty media_ids list returns 422 validation error."""
    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reanalyze_batch_unauthorized_ids(client, client_user2, db_engine):
    """User cannot re-analyze items belonging to another user; they are rejected."""
    # Upload item as user1
    id1 = await _upload_jpeg(client, "user1_photo.jpg")

    # User2 tries to re-analyze user1's item
    resp = await client_user2.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [id1]},
    )
    assert resp.status_code == 202
    body = resp.json()
    # Item is not owned by user2 — returned as rejected/media_item_not_found
    assert body["accepted_count"] == 0
    assert body["queued_count"] == 0
    assert body["rejected_count"] == 1
    assert body["outcomes"][0]["outcome"] == "rejected"
    assert body["outcomes"][0]["reason_code"] == "media_item_not_found"


@pytest.mark.asyncio
async def test_reanalyze_batch_cap_exceeded(client):
    """Sending more than 50 media_ids returns a validation error."""
    ids = [f"fake-id-{i}" for i in range(51)]
    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": ids},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reanalyze_batch_over_limit_returns_structured_429(client, db_engine):
    """Batch re-analysis: P11-001 all-or-nothing quota failure returns 429 with full outcomes."""
    from src.analysis.mock_provider import MockVisionProvider

    id1 = await _upload_jpeg(client, "img1.jpg")
    id2 = await _upload_png(client, "img2.png")
    await asyncio.sleep(0.2)

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # Capture existing jobs before the batch call.
    async with factory() as db:
        pre_jobs = (await db.execute(
            select(ProcessingJob).where(ProcessingJob.media_item_id.in_([id1, id2]))
        )).scalars().all()
        pre_count = len(pre_jobs)

    async with factory() as db:
        user = (await db.execute(select(User).where(User.id == DEV_USER_1))).scalar_one()
        user.monthly_limit = 0
        await db.commit()

    with patch("src.api.routes.analysis._vision_provider", MockVisionProvider()):
        resp = await client.post(
            "/api/v1/media/reanalyze-batch",
            json={"media_ids": [id1, id2]},
        )

    assert resp.status_code == 429
    body = resp.json()
    assert body["error_code"] == "quota_exceeded"
    assert body["queued_count"] == 0
    assert body["accepted_candidate_count"] == 2

    outcomes_by_id = {o["media_id"]: o for o in body["outcomes"]}
    assert outcomes_by_id[id1]["reason_code"] == "quota_exhausted_batch"
    assert outcomes_by_id[id2]["reason_code"] == "quota_exhausted_batch"

    # Verify no NEW job was created.
    async with factory() as db:
        post_jobs = (await db.execute(
            select(ProcessingJob).where(ProcessingJob.media_item_id.in_([id1, id2]))
        )).scalars().all()
        assert len(post_jobs) == pre_count


# ---------------------------------------------------------------------------
# DELETE /api/v1/media/batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_batch_success(client, db_engine):
    """Batch delete removes DB rows for owned items."""
    id1 = await _upload_jpeg(client, "to_delete1.jpg")
    id2 = await _upload_png(client, "to_delete2.png")

    resp = await client.request(
        "DELETE",
        "/api/v1/media/batch",
        json={"media_ids": [id1, id2]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 2
    assert "deleted" in body["message"]

    # Verify items are gone from DB
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        remaining = (await db.execute(
            select(MediaItem).where(MediaItem.id.in_([id1, id2]))
        )).scalars().all()
        assert len(remaining) == 0


@pytest.mark.asyncio
async def test_delete_batch_unauthorized_ids(client, client_user2, db_engine):
    """User cannot delete items belonging to another user; they are silently skipped."""
    id1 = await _upload_jpeg(client, "user1_secret.jpg")

    # User2 tries to delete user1's item
    resp = await client_user2.request(
        "DELETE",
        "/api/v1/media/batch",
        json={"media_ids": [id1]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 0

    # Verify item still exists
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        item = (await db.execute(
            select(MediaItem).where(MediaItem.id == id1)
        )).scalar_one_or_none()
        assert item is not None


@pytest.mark.asyncio
async def test_delete_batch_cleans_up_files(client, db_engine, tmp_storage):
    """Physical file is removed after batch delete."""
    import src.api.routes.analysis as analysis_mod

    # Patch analysis module's file store to use test temp dir
    test_file_store = LocalFileStore(tmp_storage)
    original_file_store = analysis_mod._file_store
    analysis_mod._file_store = test_file_store

    try:
        id1 = await _upload_jpeg(client, "cleanup_test.jpg")

        # Retrieve the storage path before deletion
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            item = (await db.execute(
                select(MediaItem).where(MediaItem.id == id1)
            )).scalar_one()
            storage_path = item.storage_path

        # Confirm file exists before delete
        assert await test_file_store.exists(storage_path), "File should exist before delete"

        resp = await client.request(
            "DELETE",
            "/api/v1/media/batch",
            json={"media_ids": [id1]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        # File should be gone
        assert not await test_file_store.exists(storage_path), "File should be removed after delete"
    finally:
        analysis_mod._file_store = original_file_store


@pytest.mark.asyncio
async def test_delete_batch_empty_body(client):
    """Empty media_ids list returns 422 validation error."""
    resp = await client.request(
        "DELETE",
        "/api/v1/media/batch",
        json={"media_ids": []},
    )
    assert resp.status_code == 422
