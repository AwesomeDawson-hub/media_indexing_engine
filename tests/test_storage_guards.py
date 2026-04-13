"""Integration tests for P9-002: Source-Aware Original Access Hardening.

Coverage:
  1.  assert_original_accessible helper: raises 409 for reference-mode items
  2.  assert_original_accessible helper: raises 409 for preview_only items
  3.  assert_original_accessible helper: does NOT raise for full-mode items
  4.  original_is_accessible helper: returns correct bool for all three modes
  5.  POST /media/{id}/reanalyze: returns 409 for reference-mode item
  6.  POST /media/{id}/reanalyze: returns 409 for preview_only item
  7.  POST /media/{id}/reanalyze: succeeds (202) for full-mode item
  8.  POST /media/reanalyze-batch: silently skips reference-mode items
  9.  GET /media/{id}/download: returns 409 for reference-mode item
 10.  GET /media/{id}/download: returns 409 for preview_only item
 11.  POST /media/download-batch: skips reference-mode items (counted in skipped)
 12.  POST /media/{id}/convert-png: returns 409 for reference-mode item
 13.  DELETE /media/batch: reference-mode items deleted cleanly (no crash on None storage_path)
 14.  DELETE /media/batch: thumbnail deleted along with storage_path when both present
 15.  analyze_media_item: fails immediately for reference-mode item, releases reservation
 16.  analyze_media_item: fails immediately for preview_only item, releases reservation
 17.  score_group: skips reference-mode member, counts it in failed_count
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

import types

from src.api.storage_guards import assert_original_accessible, original_is_accessible
from src.models import MediaItem, ProcessingJob, Source
from src.storage.file_store import LocalFileStore
from tests.conftest import DEV_USER_1, JPEG_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(storage_mode: str, storage_path: str | None = None, thumbnail_path: str | None = None):
    """Build a plain namespace stub with just the fields the guards inspect."""
    return types.SimpleNamespace(
        id="stub-id",
        storage_mode=storage_mode,
        storage_path=storage_path,
        thumbnail_path=thumbnail_path,
    )


async def _upload_jpeg(client) -> str:
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _make_reference_item(db_session_factory, user_id: str, file_store: LocalFileStore) -> MediaItem:
    """Insert a reference-mode MediaItem + ProcessingJob directly into DB."""
    from src.ingestion.connector_ingest import process_connector_import
    from src.models import Source

    async with db_session_factory() as db:
        source = Source(user_id=user_id, name="test-source", source_type="s3_compatible")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        result = await process_connector_import(
            db=db,
            user_id=user_id,
            filename="ref.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
            file_store=file_store,
        )
    assert result.success
    return result.media_item


# ---------------------------------------------------------------------------
# 1–4. Storage guard helpers
# ---------------------------------------------------------------------------

def test_assert_original_accessible_raises_for_reference():
    """reference items raise HTTP 409 with original_at_source code."""
    from fastapi import HTTPException
    item = _make_item("reference", storage_path=None)
    with pytest.raises(HTTPException) as exc_info:
        assert_original_accessible(item)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "original_at_source"


def test_assert_original_accessible_raises_for_preview_only():
    """preview_only items raise HTTP 409 with original_at_source code."""
    from fastapi import HTTPException
    item = _make_item("preview_only", storage_path=None)
    with pytest.raises(HTTPException) as exc_info:
        assert_original_accessible(item)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "original_at_source"


def test_assert_original_accessible_does_not_raise_for_full():
    """full-mode items with storage_path do NOT raise."""
    item = _make_item("full", storage_path="files/user/hash/photo.jpg")
    assert_original_accessible(item)  # must not raise


def test_original_is_accessible_all_modes():
    """original_is_accessible returns correct bool for all storage modes."""
    assert original_is_accessible(_make_item("full", "path/to/file")) is True
    assert original_is_accessible(_make_item("full", None)) is False
    assert original_is_accessible(_make_item("preview_only", None)) is False
    assert original_is_accessible(_make_item("reference", None)) is False


# ---------------------------------------------------------------------------
# 5–7. POST /media/{id}/reanalyze guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reanalyze_reference_item_returns_409(
    client, db_session_factory, seed_users, tmp_storage
):
    """Reanalyze returns 409 original_at_source for reference-mode items."""
    file_store = LocalFileStore(tmp_storage)
    item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    resp = await client.post(f"/api/v1/media/{item.id}/reanalyze")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "original_at_source"


@pytest.mark.asyncio
async def test_reanalyze_preview_only_item_returns_409(client, db_session_factory, seed_users):
    """Reanalyze returns 409 original_at_source for preview_only items."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with db_session_factory() as db:
        item = MediaItem(
            user_id=DEV_USER_1,
            content_hash="previewtest01",
            original_filename="prev.jpg",
            file_size=100,
            mime_type="image/jpeg",
            storage_path=None,
            storage_mode="preview_only",
            status="completed",
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)

    resp = await client.post(f"/api/v1/media/{item.id}/reanalyze")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "original_at_source"


@pytest.mark.asyncio
async def test_reanalyze_full_item_succeeds(client):
    """Reanalyze returns 202 for a full-mode item (browser upload)."""
    item_id = await _upload_jpeg(client)
    await asyncio.sleep(0.3)

    resp = await client.post(f"/api/v1/media/{item_id}/reanalyze")
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# 8. POST /media/reanalyze-batch: silently skips non-full items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reanalyze_batch_skips_reference_items(
    client, db_session_factory, seed_users, tmp_storage
):
    """Batch reanalyze explicitly blocks reference-mode items (P11-001: no silent skip)."""
    file_store = LocalFileStore(tmp_storage)
    item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    resp = await client.post(
        "/api/v1/media/reanalyze-batch",
        json={"media_ids": [item.id]},
    )
    assert resp.status_code == 202
    body = resp.json()
    # reference items are now explicitly blocked, not silently skipped
    assert body["accepted_count"] == 0
    assert body["blocked_count"] == 1
    assert body["queued_count"] == 0
    assert body["outcomes"][0]["outcome"] == "blocked"


# ---------------------------------------------------------------------------
# 9–10. GET /media/{id}/download guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_reference_item_returns_409(
    client, db_session_factory, seed_users, tmp_storage
):
    """Download endpoint returns 409 original_at_source for reference-mode items."""
    file_store = LocalFileStore(tmp_storage)
    item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    resp = await client.get(f"/api/v1/media/{item.id}/download")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "original_at_source"


@pytest.mark.asyncio
async def test_download_preview_only_item_returns_409(client, db_session_factory, seed_users):
    """Download endpoint returns 409 original_at_source for preview_only items."""
    async with db_session_factory() as db:
        item = MediaItem(
            user_id=DEV_USER_1,
            content_hash="previewdl01",
            original_filename="prev.jpg",
            file_size=100,
            mime_type="image/jpeg",
            storage_path=None,
            storage_mode="preview_only",
            status="completed",
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)

    resp = await client.get(f"/api/v1/media/{item.id}/download")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "original_at_source"


# ---------------------------------------------------------------------------
# 11. POST /media/download-batch: skips reference-mode items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_batch_skips_reference_items(
    client, db_session_factory, seed_users, tmp_storage
):
    """Batch download skips reference-mode items; they appear in skipped count."""
    file_store = LocalFileStore(tmp_storage)
    ref_item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    resp = await client.post(
        "/api/v1/media/download-batch",
        json={"media_ids": [ref_item.id]},
    )
    # All items skipped — should return 404 (no included items)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 12. POST /media/{id}/convert-png guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_convert_png_reference_item_returns_409(
    client, db_session_factory, seed_users, tmp_storage
):
    """Convert-to-PNG returns 409 original_at_source for reference-mode items."""
    from tests.conftest import GIF_BYTES

    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source = Source(user_id=DEV_USER_1, name="gif-source", source_type="s3_compatible")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        from src.ingestion.connector_ingest import process_connector_import
        result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="anim.gif",
            file_bytes=GIF_BYTES,
            source_id=source.id,
            file_store=file_store,
        )

    resp = await client.post(f"/api/v1/media/{result.media_item.id}/convert-png")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "original_at_source"


# ---------------------------------------------------------------------------
# 13. DELETE /media/batch: reference items delete cleanly without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_batch_reference_item_no_crash(
    client, db_session_factory, seed_users, tmp_storage
):
    """Batch delete handles reference-mode items (storage_path=None) without crashing."""
    file_store = LocalFileStore(tmp_storage)
    item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    resp = await client.request(
        "DELETE",
        "/api/v1/media/batch",
        json={"media_ids": [item.id]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # Confirm DB row removed
    async with db_session_factory() as db:
        gone = (await db.execute(
            select(MediaItem).where(MediaItem.id == item.id)
        )).scalar_one_or_none()
    assert gone is None


# ---------------------------------------------------------------------------
# 14. DELETE /media/batch: thumbnail also deleted when present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_batch_removes_thumbnail(client, db_session_factory, seed_users, tmp_storage):
    """Batch delete removes the thumbnail file when thumbnail_path is set."""
    import src.api.routes.analysis as analysis_mod

    test_file_store = LocalFileStore(tmp_storage)
    original_file_store = analysis_mod._file_store
    analysis_mod._file_store = test_file_store

    try:
        item = await _make_reference_item(db_session_factory, DEV_USER_1, test_file_store)

        # Confirm thumbnail was created
        assert item.thumbnail_path is not None
        assert await test_file_store.exists(item.thumbnail_path)

        resp = await client.request(
            "DELETE",
            "/api/v1/media/batch",
            json={"media_ids": [item.id]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        # Thumbnail should be gone
        assert not await test_file_store.exists(item.thumbnail_path)
    finally:
        analysis_mod._file_store = original_file_store


# ---------------------------------------------------------------------------
# 15–16. analyze_media_item fail-fast guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_media_item_fails_immediately_for_reference(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """analyze_media_item fails the job immediately for reference-mode items without retry."""
    import src.analysis.processor as processor_mod
    from src.analysis.processor import analyze_media_item
    from src.analysis.mock_provider import MockVisionProvider

    monkeypatch.setattr(processor_mod, "async_session", db_session_factory)

    file_store = LocalFileStore(tmp_storage)
    item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    # Get the job_id that was created during import
    async with db_session_factory() as db:
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.media_item_id == item.id)
        )
        job = job_result.scalar_one()
        job_id = job.id

    await analyze_media_item(
        job_id=job_id,
        vision_provider=MockVisionProvider(),
        file_store=file_store,
    )

    async with db_session_factory() as db:
        job_result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        job = job_result.scalar_one()
        item_result = await db.execute(select(MediaItem).where(MediaItem.id == item.id))
        refreshed = item_result.scalar_one()

    assert job.status == "failed"
    assert "not in app storage" in (job.error_message or "")
    assert refreshed.status == "error"
    assert refreshed.storage_mode == "reference"  # unchanged


@pytest.mark.asyncio
async def test_analyze_media_item_fails_immediately_for_preview_only(
    db_session_factory, seed_users, monkeypatch
):
    """analyze_media_item fails the job immediately for preview_only items."""
    import src.analysis.processor as processor_mod
    from src.analysis.processor import analyze_media_item
    from src.analysis.mock_provider import MockVisionProvider

    monkeypatch.setattr(processor_mod, "async_session", db_session_factory)

    async with db_session_factory() as db:
        item = MediaItem(
            user_id=DEV_USER_1,
            content_hash="prevanalysis01",
            original_filename="prev.jpg",
            file_size=100,
            mime_type="image/jpeg",
            storage_path=None,
            storage_mode="preview_only",
            status="uploaded",
        )
        db.add(item)
        await db.flush()
        job = ProcessingJob(media_item_id=item.id, job_type="analysis", status="pending")
        db.add(job)
        await db.commit()
        job_id = job.id

    await analyze_media_item(
        job_id=job_id,
        vision_provider=MockVisionProvider(),
        file_store=LocalFileStore("/tmp"),
    )

    async with db_session_factory() as db:
        job_result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        job = job_result.scalar_one()

    assert job.status == "failed"
    assert "not in app storage" in (job.error_message or "")


# ---------------------------------------------------------------------------
# 17. score_group: reference-mode member counted as failed, not crashing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_group_skips_reference_member(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """score_group counts reference-mode group members in failed_count without crashing."""
    from src.curation.scoring_service import score_group

    file_store = LocalFileStore(tmp_storage)
    ref_item = await _make_reference_item(db_session_factory, DEV_USER_1, file_store)

    # score_group needs an anchor_id that exists for the user; use the ref item itself
    async with db_session_factory() as db:
        result = await score_group(
            anchor_id=ref_item.id,
            user_id=DEV_USER_1,
            db=db,
            file_store=file_store,
        )

    assert result.failed_count >= 1
    # No crash, scored_count for this item is 0
    assert result.scored_count == 0
