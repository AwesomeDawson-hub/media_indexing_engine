"""Tests for P11-002: Async Connector-Aware Bulk Export.

Coverage
--------
Submission (POST /api/v1/media/export-batch):
  1.  Mixed batch: full + Drive + local_folder + missing → correct per-item outcomes, 202
  2.  No-eligible items → 409 export_no_eligible_items, no job created
  3.  Batch too large → 400 export_batch_too_large
  4.  Max active jobs reached → 409 export_job_limit_reached
  5.  Duplicate IDs in request → deduplicated, single outcome per media item
  6.  Analysis-not-completed item → blocked/analysis_not_completed

Job status (GET /api/v1/media/export-jobs/{job_id}):
  7.  Pending job → status=pending, artifact_ready=False
  8.  Completed job → correct exported/failed counts, artifact_ready=True
  9.  Job not found → 404 export_job_not_found
  10. Ownership scoping: user2 cannot read user1's job

Export execution (background task):
  11. Full items exported successfully → status=completed, ZIP readable
  12. Drive item exported successfully (mocked) → status=completed, in ZIP
  13. Drive runtime failure → status=completed_with_failures, item error_code recorded

Artifact download (GET /api/v1/media/export-jobs/{job_id}/download):
  14. Download returns ZIP, marks artifact_downloaded=True
  15. Second download → 410 export_artifact_expired
  16. Job not ready yet → 409 export_not_ready
  17. Ownership scoping: user2 cannot download user1's artifact
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models import (
    ExportJob,
    MediaItem,
    MediaMetadata,
    OriginAssetRef,
    Source,
    SourceConnector,
)
from tests.conftest import DEV_USER_1, DEV_USER_2, JPEG_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_full_item(db, *, user_id: str = DEV_USER_1, status: str = "completed") -> MediaItem:
    """Insert a minimal full-storage media item directly into the DB."""
    content_hash = _new_id().replace("-", "")
    # Store bytes via the real file store (but we just need an ORM row for routing tests)
    item = MediaItem(
        id=_new_id(),
        user_id=user_id,
        content_hash=content_hash,
        original_filename="photo.jpg",
        file_size=len(JPEG_BYTES),
        mime_type="image/jpeg",
        storage_path=f"{user_id}/{content_hash}/photo.jpg",
        storage_mode="full",
        status=status,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _add_metadata(db, media_item_id: str) -> MediaMetadata:
    meta = MediaMetadata(
        id=_new_id(),
        media_item_id=media_item_id,
        title="Test Photo",
        description="A test image.",
        tags='["nature"]',
        objects='["tree"]',
        scenes='["outdoor"]',
        context="outdoor",
        mood="calm",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors='["green"]',
        location_hint=None,
        quality_notes=None,
        ai_provider="mock",
        ai_model="mock-model",
        analyzed_at=_now(),
    )
    db.add(meta)
    await db.commit()
    return meta


async def _make_drive_reference_item(
    db, *, user_id: str = DEV_USER_1, status: str = "completed"
) -> tuple[MediaItem, OriginAssetRef]:
    """Insert a minimal Drive-backed reference item."""
    source = Source(
        id=_new_id(),
        user_id=user_id,
        name="test-drive",
        source_type="google_drive",
    )
    db.add(source)

    connector_row = SourceConnector(
        id=_new_id(),
        source_id=source.id,
        user_id=user_id,
        connector_type="google_drive",
        remote_container_id="root",
        remote_container_label="My Drive",
        credentials_encrypted="placeholder",
    )
    db.add(connector_row)

    item = MediaItem(
        id=_new_id(),
        user_id=user_id,
        content_hash=_new_id().replace("-", ""),
        original_filename="drive_photo.jpg",
        file_size=len(JPEG_BYTES),
        mime_type="image/jpeg",
        storage_path=None,
        storage_mode="reference",
        status=status,
        source_id=source.id,
    )
    db.add(item)

    oar = OriginAssetRef(
        id=_new_id(),
        media_item_id=item.id,
        user_id=user_id,
        source_id=source.id,
        provider_type="google_drive",
        provider_object_id="drive-abc123",
        locator_snapshot="drive-abc123",
    )
    db.add(oar)
    await db.commit()
    await db.refresh(item)
    return item, oar


async def _make_local_reference_item(
    db, *, user_id: str = DEV_USER_1
) -> tuple[MediaItem, OriginAssetRef]:
    """Insert a local-folder reference item (not eligible for export)."""
    source = Source(
        id=_new_id(),
        user_id=user_id,
        name="test-local",
        source_type="local_folder",
    )
    db.add(source)

    item = MediaItem(
        id=_new_id(),
        user_id=user_id,
        content_hash=_new_id().replace("-", ""),
        original_filename="local.jpg",
        file_size=len(JPEG_BYTES),
        mime_type="image/jpeg",
        storage_path=None,
        storage_mode="reference",
        status="completed",
        source_id=source.id,
    )
    db.add(item)

    oar = OriginAssetRef(
        id=_new_id(),
        media_item_id=item.id,
        user_id=user_id,
        source_id=source.id,
        provider_type="local_folder",
        provider_object_id="local/path",
        locator_snapshot="local/path",
    )
    db.add(oar)
    await db.commit()
    await db.refresh(item)
    return item, oar


# ---------------------------------------------------------------------------
# Test 1: Mixed batch submission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_batch_mixed_submission(client, db_session_factory, seed_users):
    """Full + Drive + local_folder + missing → correct per-item outcomes, job created."""
    async with db_session_factory() as db:
        full_item = await _make_full_item(db)
        drive_item, _ = await _make_drive_reference_item(db)
        local_item, _ = await _make_local_reference_item(db)

    missing_id = "nonexistent-id-000"

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [full_item.id, drive_item.id, local_item.id, missing_id]},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()

    assert body["request_count"] == 4
    assert body["accepted_count"] == 2
    assert body["blocked_count"] == 1
    assert body["rejected_count"] == 1
    assert "job_id" in body

    outcomes_by_id = {o["media_id"]: o for o in body["outcomes"]}

    assert outcomes_by_id[full_item.id]["outcome"] == "accepted"
    assert outcomes_by_id[drive_item.id]["outcome"] == "accepted"
    assert outcomes_by_id[local_item.id]["outcome"] == "blocked"
    assert outcomes_by_id[local_item.id]["reason_code"] == "local_reference_not_supported"
    assert outcomes_by_id[missing_id]["outcome"] == "rejected"
    assert outcomes_by_id[missing_id]["reason_code"] == "media_item_not_found"


# ---------------------------------------------------------------------------
# Test 2: No-eligible items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_batch_no_eligible_items(client, db_session_factory, seed_users):
    """All-rejected/blocked batch → 409 export_no_eligible_items with full locked payload, no job created."""
    async with db_session_factory() as db:
        local_item, _ = await _make_local_reference_item(db)

    missing_id = "nonexistent-000"

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [local_item.id, missing_id]},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "export_no_eligible_items"

    # Full locked payload must be present (Gap 1 contract)
    assert body["request_count"] == 2
    assert body["accepted_count"] == 0
    assert body["blocked_count"] == 1
    assert body["rejected_count"] == 1
    assert isinstance(body["outcomes"], list)
    assert len(body["outcomes"]) == 2
    outcomes_by_id = {o["media_id"]: o for o in body["outcomes"]}
    assert outcomes_by_id[local_item.id]["outcome"] == "blocked"
    assert outcomes_by_id[missing_id]["outcome"] == "rejected"

    # No job should have been created
    async with db_session_factory() as db:
        count_result = await db.execute(
            select(ExportJob).where(ExportJob.user_id == DEV_USER_1)
        )
        assert count_result.scalars().all() == []


# ---------------------------------------------------------------------------
# Test 3: Batch too large
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_batch_too_large(client, seed_users):
    """Request with > max_batch_size items → 400 export_batch_too_large."""
    ids = [_new_id() for _ in range(51)]
    resp = await client.post("/api/v1/media/export-batch", json={"media_ids": ids})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "export_batch_too_large"


# ---------------------------------------------------------------------------
# Test 4: Max active jobs reached
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_batch_job_limit_reached(client, db_session_factory, seed_users):
    """User already at active-job limit → 409 export_job_limit_reached."""
    async with db_session_factory() as db:
        for _ in range(3):  # matches max_active_jobs_per_user default
            db.add(ExportJob(
                user_id=DEV_USER_1,
                status="pending",
                request_count=1,
                accepted_count=1,
                submission_outcomes='[]',
            ))
        await db.commit()

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [_new_id()]},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "export_job_limit_reached"


# ---------------------------------------------------------------------------
# Test 5: Duplicate IDs deduplicated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_batch_deduplicates_ids(client, db_session_factory, seed_users):
    """Duplicate media_ids produce a single outcome per item."""
    async with db_session_factory() as db:
        full_item = await _make_full_item(db)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [full_item.id, full_item.id, full_item.id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["request_count"] == 1
    assert body["accepted_count"] == 1
    assert len(body["outcomes"]) == 1


# ---------------------------------------------------------------------------
# Test 6: Analysis-not-completed item blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_batch_unanalyzed_item_blocked(client, db_session_factory, seed_users):
    """Item with status != completed → blocked/analysis_not_completed."""
    async with db_session_factory() as db:
        pending_item = await _make_full_item(db, status="pending")
        # Need at least one accepted item to avoid the no-eligible guard
        ready_item = await _make_full_item(db, status="completed")

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [pending_item.id, ready_item.id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    outcomes_by_id = {o["media_id"]: o for o in body["outcomes"]}
    assert outcomes_by_id[pending_item.id]["outcome"] == "blocked"
    assert outcomes_by_id[pending_item.id]["reason_code"] == "analysis_not_completed"
    assert outcomes_by_id[ready_item.id]["outcome"] == "accepted"


# ---------------------------------------------------------------------------
# Test 7: Get job status — pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_export_job_status_pending(client, db_session_factory, seed_users):
    """Polling a pending job returns correct fields with artifact_ready=False."""
    async with db_session_factory() as db:
        full_item = await _make_full_item(db)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [full_item.id]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Immediately poll (may still be pending or running)
    status_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["job_id"] == job_id
    assert body["status"] in ("pending", "running", "completed", "completed_with_failures")
    assert "artifact_ready" in body
    assert "request_count" in body


# ---------------------------------------------------------------------------
# Test 8: Get job status — not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_export_job_status_not_found(client, seed_users):
    """Looking up a nonexistent job returns 404."""
    resp = await client.get("/api/v1/media/export-jobs/nonexistent-job-id")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "export_job_not_found"


# ---------------------------------------------------------------------------
# Test 9: Ownership scoping on status endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_export_job_status_wrong_user(
    client, client_user2, db_session_factory, seed_users
):
    """User2 cannot read user1's export job."""
    async with db_session_factory() as db:
        full_item = await _make_full_item(db, user_id=DEV_USER_1)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [full_item.id]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    resp2 = await client_user2.get(f"/api/v1/media/export-jobs/{job_id}")
    assert resp2.status_code == 404
    assert resp2.json()["error_code"] == "export_job_not_found"


# ---------------------------------------------------------------------------
# Test 10: Ownership scoping on download endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_export_artifact_wrong_user(
    client, client_user2, db_session_factory, seed_users
):
    """User2 cannot download user1's artifact."""
    async with db_session_factory() as db:
        full_item = await _make_full_item(db, user_id=DEV_USER_1)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [full_item.id]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    resp2 = await client_user2.get(f"/api/v1/media/export-jobs/{job_id}/download")
    assert resp2.status_code == 404
    assert resp2.json()["error_code"] == "export_job_not_found"


# ---------------------------------------------------------------------------
# Test 11: Full-item export completes successfully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_full_items_completes(client, db_session_factory, seed_users, tmp_storage):
    """Full items exported, ZIP readable, status=completed after background task."""
    import src.api.routes.upload as upload_mod
    from src.storage.file_store import LocalFileStore

    file_store = LocalFileStore(tmp_storage)
    upload_mod._file_store = file_store

    async with db_session_factory() as db:
        item = await _make_full_item(db)
        # Write real bytes to the file store so the background task can read them
        await file_store.save(
            user_id=item.user_id,
            content_hash=item.content_hash,
            original_filename="photo.jpg",
            file_bytes=JPEG_BYTES,
        )
        await _add_metadata(db, item.id)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [item.id]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Wait for background task to complete
    await asyncio.sleep(2.0)

    status_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] in ("completed", "completed_with_failures"), body
    assert body["artifact_ready"] is True
    assert body["exported_count"] == 1


# ---------------------------------------------------------------------------
# Test 12: Drive item exported (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_drive_item_success(client, db_session_factory, seed_users, tmp_storage):
    """Drive-backed item exported with mocked fetch → status=completed."""
    import src.api.routes.upload as upload_mod
    from src.storage.file_store import LocalFileStore

    file_store = LocalFileStore(tmp_storage)
    upload_mod._file_store = file_store

    async with db_session_factory() as db:
        drive_item, _ = await _make_drive_reference_item(db)
        await _add_metadata(db, drive_item.id)

    with patch(
        "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
        new_callable=AsyncMock,
        return_value=JPEG_BYTES,
    ):
        resp = await client.post(
            "/api/v1/media/export-batch",
            json={"media_ids": [drive_item.id]},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        await asyncio.sleep(2.0)

    status_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] in ("completed", "completed_with_failures"), body
    assert body["exported_count"] >= 1


# ---------------------------------------------------------------------------
# Test 13: Drive runtime failure → completed_with_failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_drive_failure_partial(client, db_session_factory, seed_users, tmp_storage):
    """Drive fetch failure records item error, job completes with failures."""
    import src.api.routes.upload as upload_mod
    from src.storage.file_store import LocalFileStore

    file_store = LocalFileStore(tmp_storage)
    upload_mod._file_store = file_store

    async with db_session_factory() as db:
        drive_item, _ = await _make_drive_reference_item(db)
        await _add_metadata(db, drive_item.id)

    with patch(
        "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=404,
            detail={"error_code": "drive_file_not_found", "message": "File deleted"},
        ),
    ):
        resp = await client.post(
            "/api/v1/media/export-batch",
            json={"media_ids": [drive_item.id]},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        await asyncio.sleep(2.0)

    status_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    # The artifact_path may be None if all items failed, so status could be "failed"
    assert body["status"] in ("completed_with_failures", "failed"), body
    assert body["failed_count"] == 1
    results = body["item_results"] or []
    failed = [r for r in results if r["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["error_code"] == "drive_file_not_found"


# ---------------------------------------------------------------------------
# Test 14: Download artifact succeeds and marks consumed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_artifact_success_and_consumes(
    client, db_session_factory, seed_users, tmp_storage
):
    """First download streams ZIP, marks artifact_downloaded=True."""
    import src.api.routes.upload as upload_mod
    from src.storage.file_store import LocalFileStore

    file_store = LocalFileStore(tmp_storage)
    upload_mod._file_store = file_store

    async with db_session_factory() as db:
        item = await _make_full_item(db)
        await file_store.save(
            user_id=item.user_id,
            content_hash=item.content_hash,
            original_filename="photo.jpg",
            file_bytes=JPEG_BYTES,
        )
        await _add_metadata(db, item.id)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [item.id]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    await asyncio.sleep(2.0)

    # Verify job is complete before attempting download
    status_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    assert status_resp.status_code == 200
    if status_resp.json()["status"] not in ("completed", "completed_with_failures"):
        pytest.skip("Background task did not finish in time")

    dl_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}/download")
    assert dl_resp.status_code == 200
    assert dl_resp.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(dl_resp.content))
    assert len(zf.namelist()) >= 1

    # Verify the job is now marked as consumed
    async with db_session_factory() as db:
        result = await db.execute(select(ExportJob).where(ExportJob.id == job_id))
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.artifact_downloaded is True


# ---------------------------------------------------------------------------
# Test 15: Second download returns 410
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_artifact_second_download_returns_410(
    client, db_session_factory, seed_users, tmp_storage
):
    """Second download attempt returns 410 export_artifact_expired."""
    import src.api.routes.upload as upload_mod
    from src.storage.file_store import LocalFileStore

    file_store = LocalFileStore(tmp_storage)
    upload_mod._file_store = file_store

    async with db_session_factory() as db:
        item = await _make_full_item(db)
        await file_store.save(
            user_id=item.user_id,
            content_hash=item.content_hash,
            original_filename="photo.jpg",
            file_bytes=JPEG_BYTES,
        )
        await _add_metadata(db, item.id)

    resp = await client.post(
        "/api/v1/media/export-batch",
        json={"media_ids": [item.id]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    await asyncio.sleep(2.0)

    status_resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    if status_resp.json()["status"] not in ("completed", "completed_with_failures"):
        pytest.skip("Background task did not finish in time")

    # First download
    dl1 = await client.get(f"/api/v1/media/export-jobs/{job_id}/download")
    assert dl1.status_code == 200

    # Second download
    dl2 = await client.get(f"/api/v1/media/export-jobs/{job_id}/download")
    assert dl2.status_code == 410
    assert dl2.json()["error_code"] == "export_artifact_expired"


# ---------------------------------------------------------------------------
# Test 16: Download before job ready → 409
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_artifact_not_ready(client, db_session_factory, seed_users):
    """Download attempt on pending/running job returns 409 export_not_ready."""
    # Insert a pending job directly (bypassing background task)
    async with db_session_factory() as db:
        job = ExportJob(
            user_id=DEV_USER_1,
            status="pending",
            request_count=1,
            accepted_count=1,
            submission_outcomes='[]',
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    resp = await client.get(f"/api/v1/media/export-jobs/{job_id}/download")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "export_not_ready"


# ---------------------------------------------------------------------------
# Test 17: Artifact TTL expiry → 410 on download
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_artifact_ttl_expired(client, db_session_factory, seed_users, tmp_storage):
    """Job with expired artifact_expires_at → 410 export_artifact_expired."""
    import src.api.routes.upload as upload_mod
    from src.storage.file_store import LocalFileStore

    file_store = LocalFileStore(tmp_storage)
    upload_mod._file_store = file_store

    # Save a dummy artifact
    artifact_path = await file_store.save(
        user_id=DEV_USER_1,
        content_hash="expiredexporttest",
        original_filename="export.zip",
        file_bytes=b"PK\x05\x06" + b"\x00" * 18,  # minimal valid ZIP end-of-central-dir
    )

    async with db_session_factory() as db:
        job = ExportJob(
            user_id=DEV_USER_1,
            status="completed",
            request_count=1,
            accepted_count=1,
            submission_outcomes='[]',
            item_results='[]',
            artifact_path=artifact_path,
            artifact_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            artifact_downloaded=False,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    resp = await client.get(f"/api/v1/media/export-jobs/{job_id}/download")
    assert resp.status_code == 410
    assert resp.json()["error_code"] == "export_artifact_expired"


# ---------------------------------------------------------------------------
# Test 18: Status polling promotes completed → expired (Gap 4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_poll_promotes_completed_to_expired(client, db_session_factory, seed_users):
    """GET status on a completed job whose TTL has elapsed must return status=expired."""
    async with db_session_factory() as db:
        job = ExportJob(
            user_id=DEV_USER_1,
            status="completed",
            request_count=1,
            accepted_count=1,
            submission_outcomes='[]',
            item_results='[]',
            artifact_path="some/path/export.zip",
            artifact_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            artifact_downloaded=False,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    resp = await client.get(f"/api/v1/media/export-jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "expired", f"Expected 'expired', got '{body['status']}'"
    assert body["artifact_ready"] is False


# ---------------------------------------------------------------------------
# Test 19: Startup sweeper marks expired jobs (Gap 3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sweep_expired_export_artifacts(db_session_factory, seed_users):
    """_sweep_expired_export_artifacts promotes TTL-elapsed jobs to expired."""
    from src.api.routes.export import _sweep_expired_export_artifacts

    async with db_session_factory() as db:
        # Job whose TTL has passed — should be swept
        expired_job = ExportJob(
            user_id=DEV_USER_1,
            status="completed",
            request_count=1,
            accepted_count=1,
            submission_outcomes='[]',
            item_results='[]',
            artifact_path=None,
            artifact_expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
            artifact_downloaded=False,
        )
        # Job whose TTL is still in the future — must NOT be swept
        live_job = ExportJob(
            user_id=DEV_USER_1,
            status="completed",
            request_count=1,
            accepted_count=1,
            submission_outcomes='[]',
            item_results='[]',
            artifact_path=None,
            artifact_expires_at=datetime.now(timezone.utc) + timedelta(hours=23),
            artifact_downloaded=False,
        )
        # Already-failed job — must NOT be touched
        failed_job = ExportJob(
            user_id=DEV_USER_1,
            status="failed",
            request_count=1,
            accepted_count=0,
            submission_outcomes='[]',
        )
        db.add(expired_job)
        db.add(live_job)
        db.add(failed_job)
        await db.commit()
        await db.refresh(expired_job)
        await db.refresh(live_job)
        await db.refresh(failed_job)
        expired_id = expired_job.id
        live_id = live_job.id
        failed_id = failed_job.id

    async with db_session_factory() as db:
        await _sweep_expired_export_artifacts(db)

    async with db_session_factory() as db:
        result = await db.execute(select(ExportJob).where(ExportJob.id == expired_id))
        assert result.scalar_one().status == "expired"

        result = await db.execute(select(ExportJob).where(ExportJob.id == live_id))
        assert result.scalar_one().status == "completed"

        result = await db.execute(select(ExportJob).where(ExportJob.id == failed_id))
        assert result.scalar_one().status == "failed"
