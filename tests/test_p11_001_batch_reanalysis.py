"""Tests for P11-001: Capability-Aware Batch Reanalysis.

Covers the locked API contract for POST /api/v1/media/reanalyze-batch:

  - full-storage item batch success
  - Drive-backed reference item queue admission (no request-time fetch)
  - mixed full + Drive selection
  - blocked local_folder reference item (local_reference_not_supported)
  - blocked unsupported-provider reference item (provider_batch_reanalysis_not_supported)
  - rejected not-found / not-owned item (media_item_not_found)
  - blocked in-progress item (analysis_in_progress)
  - quota exhaustion → 429, queued_count=0, all candidates reclassified
  - mixed all types → correct per-item outcomes
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import MediaItem, OriginAssetRef, ProcessingJob, User
from tests.conftest import DEV_USER_1, JPEG_BYTES, PNG_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _upload_full(client, content=None, name="photo.jpg", mime="image/jpeg") -> str:
    """Upload a file via the API and return the media item ID."""
    if content is None:
        content = JPEG_BYTES
    resp = await client.post(
        "/api/v1/upload",
        files={"file": (name, content, mime)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_reference_item(db: AsyncSession, user_id: str, provider_type: str = "google_drive") -> str:
    """Insert a reference-mode MediaItem + OriginAssetRef directly and return the item ID."""
    item_id = str(uuid.uuid4())
    item = MediaItem(
        id=item_id,
        user_id=user_id,
        original_filename="ref.jpg",
        content_hash="refhash-" + item_id[:8],
        file_size=1024,
        mime_type="image/jpeg",
        storage_mode="reference",
        status="ready",
    )
    db.add(item)
    await db.flush()
    oar = OriginAssetRef(
        media_item_id=item_id,
        user_id=user_id,
        provider_type=provider_type,
        provider_object_id="test-object-id-" + item_id[:8],
    )
    db.add(oar)
    await db.commit()
    return item_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_item_batch_success(client, db_engine):
    """Full-storage items are accepted, job created, and per-item outcome returned."""
    item_id = await _upload_full(client, name="test_full.jpg")

    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [item_id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["request_count"] == 1
    assert body["accepted_count"] == 1
    assert body["blocked_count"] == 0
    assert body["rejected_count"] == 0
    assert body["queued_count"] == 1
    assert len(body["outcomes"]) == 1

    outcome = body["outcomes"][0]
    assert outcome["media_id"] == item_id
    assert outcome["outcome"] == "accepted"
    assert outcome["reason_code"] == "queued"
    assert outcome["job_id"] is not None

    # Verify a ProcessingJob was committed (may be pending or failed
    # after execution in the test environment).
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        jobs = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.media_item_id == item_id,
                )
            )
        ).scalars().all()
        assert len(jobs) >= 1


@pytest.mark.asyncio
async def test_drive_backed_reference_item_admission(client, db):
    """Drive-backed reference items are admitted with queued outcome.

    The key assertion: fetch_drive_reference_bytes must NOT be called during
    the HTTP request — Drive fetch only happens in the background task.
    """
    item_id = await _make_reference_item(db, DEV_USER_1, "google_drive")

    with patch("src.api.routes.analysis.fetch_drive_reference_bytes") as mock_fetch:
        with patch(
            "src.api.routes.analysis._run_drive_batch_item",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                "/api/v1/media/reanalyze-batch",
                json={"media_ids": [item_id]},
            )

    assert resp.status_code == 202
    mock_fetch.assert_not_called()  # no Drive fetch in request thread

    body = resp.json()
    assert body["accepted_count"] == 1
    assert body["queued_count"] == 1
    outcome = body["outcomes"][0]
    assert outcome["media_id"] == item_id
    assert outcome["outcome"] == "accepted"
    assert outcome["reason_code"] == "queued"
    assert outcome["job_id"] is not None


@pytest.mark.asyncio
async def test_mixed_full_and_drive(client, db):
    """Mixed selection: full item + Drive-backed item → both accepted."""
    full_id = await _upload_full(client, name="full_mixed.jpg")
    drive_id = await _make_reference_item(db, DEV_USER_1, "google_drive")

    with patch(
        "src.api.routes.analysis._run_drive_batch_item",
        new_callable=AsyncMock,
    ):
        resp = await client.post(
            "/api/v1/media/reanalyze-batch",
            json={"media_ids": [full_id, drive_id]},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["request_count"] == 2
    assert body["accepted_count"] == 2
    assert body["blocked_count"] == 0
    assert body["rejected_count"] == 0

    by_id = {o["media_id"]: o for o in body["outcomes"]}
    assert by_id[full_id]["outcome"] == "accepted"
    assert by_id[drive_id]["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_blocked_local_folder_reference_item(client, db):
    """local_folder reference items are explicitly blocked with local_reference_not_supported."""
    local_id = await _make_reference_item(db, DEV_USER_1, "local_folder")

    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [local_id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted_count"] == 0
    assert body["blocked_count"] == 1
    assert body["rejected_count"] == 0

    outcome = body["outcomes"][0]
    assert outcome["media_id"] == local_id
    assert outcome["outcome"] == "blocked"
    assert outcome["reason_code"] == "local_reference_not_supported"
    assert outcome["job_id"] is None


@pytest.mark.asyncio
async def test_blocked_unsupported_provider_reference_item(client, db):
    """Unsupported reference providers are blocked with provider_batch_reanalysis_not_supported."""
    ref_id = await _make_reference_item(db, DEV_USER_1, "dropbox")

    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [ref_id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["blocked_count"] == 1
    assert body["accepted_count"] == 0

    outcome = body["outcomes"][0]
    assert outcome["outcome"] == "blocked"
    assert outcome["reason_code"] == "provider_batch_reanalysis_not_supported"
    assert outcome["job_id"] is None


@pytest.mark.asyncio
async def test_rejected_not_found_item(client):
    """Items not found or not owned are rejected with media_item_not_found."""
    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": ["00000000-0000-0000-0000-nonexistent"]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["request_count"] == 1
    assert body["rejected_count"] == 1
    assert body["accepted_count"] == 0

    outcome = body["outcomes"][0]
    assert outcome["outcome"] == "rejected"
    assert outcome["reason_code"] == "media_item_not_found"
    assert outcome["job_id"] is None


@pytest.mark.asyncio
async def test_in_progress_item_blocked(client, db_engine):
    """Items with an in-progress analysis job are blocked with analysis_in_progress."""
    item_id = await _upload_full(client, name="inprogress.jpg")

    # Inject a synthetic running job.
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        job = ProcessingJob(
            media_item_id=item_id,
            job_type="analysis",
            status="running",
        )
        db.add(job)
        await db.commit()

    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [item_id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["blocked_count"] == 1
    assert body["accepted_count"] == 0

    outcome = body["outcomes"][0]
    assert outcome["outcome"] == "blocked"
    assert outcome["reason_code"] == "analysis_in_progress"
    assert outcome["job_id"] is None


@pytest.mark.asyncio
async def test_quota_exhaustion_returns_429_no_partial_queue(client, db_engine):
    """Quota exhaustion: 429 returned, no items queued, all candidates reclassified."""
    from src.analysis.mock_provider import MockVisionProvider

    id1 = await _upload_full(client, name="quota_a.jpg")
    id2 = await _upload_full(client, content=PNG_BYTES, name="quota_b.png", mime="image/png")

    # Capture pre-existing job count before the batch call.
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        pre_count = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.media_item_id.in_([id1, id2]),
                )
            )
        ).scalars()
        pre_count = len(list(pre_count))

    # Set quota to zero so the first reserve attempt fails immediately.
    async with factory() as db:
        user = (
            await db.execute(select(User).where(User.id == DEV_USER_1))
        ).scalar_one()
        user.monthly_limit = 0
        await db.commit()

    # Ensure the analysis module sees a vision provider so the quota path executes.
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
    assert body["request_count"] == 2

    outcomes_by_id = {o["media_id"]: o for o in body["outcomes"]}
    assert outcomes_by_id[id1]["outcome"] == "blocked"
    assert outcomes_by_id[id1]["reason_code"] == "quota_exhausted_batch"
    assert outcomes_by_id[id1]["job_id"] is None
    assert outcomes_by_id[id2]["outcome"] == "blocked"
    assert outcomes_by_id[id2]["reason_code"] == "quota_exhausted_batch"

    # Verify no NEW ProcessingJob was committed for these items.
    async with factory() as db:
        post_jobs = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.media_item_id.in_([id1, id2]),
                )
            )
        ).scalars().all()
        assert len(post_jobs) == pre_count


@pytest.mark.asyncio
async def test_mixed_all_types_correct_per_item_outcomes(client, db):
    """Mixed batch: full + Drive + local_folder + not_found → exact per-item outcomes."""
    full_id = await _upload_full(client, name="mix_full.jpg")
    drive_id = await _make_reference_item(db, DEV_USER_1, "google_drive")
    local_id = await _make_reference_item(db, DEV_USER_1, "local_folder")
    missing_id = "00000000-0000-0000-0000-000000missing"

    with patch(
        "src.api.routes.analysis._run_drive_batch_item",
        new_callable=AsyncMock,
    ):
        resp = await client.post(
            "/api/v1/media/reanalyze-batch",
            json={"media_ids": [full_id, drive_id, local_id, missing_id]},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["request_count"] == 4
    assert body["accepted_count"] == 2
    assert body["blocked_count"] == 1
    assert body["rejected_count"] == 1
    assert body["queued_count"] == 2

    by_id = {o["media_id"]: o for o in body["outcomes"]}

    assert by_id[full_id]["outcome"] == "accepted"
    assert by_id[full_id]["job_id"] is not None

    assert by_id[drive_id]["outcome"] == "accepted"
    assert by_id[drive_id]["job_id"] is not None

    assert by_id[local_id]["outcome"] == "blocked"
    assert by_id[local_id]["reason_code"] == "local_reference_not_supported"
    assert by_id[local_id]["job_id"] is None

    assert by_id[missing_id]["outcome"] == "rejected"
    assert by_id[missing_id]["reason_code"] == "media_item_not_found"
    assert by_id[missing_id]["job_id"] is None

    # Ordering is preserved (outcomes list matches requested order).
    ids_in_order = [o["media_id"] for o in body["outcomes"]]
    assert ids_in_order == [full_id, drive_id, local_id, missing_id]
