"""Integration tests for P8-001 Reference-Mode Storage Pivot (Slice A + Slice B)."""

import pytest
from sqlalchemy import select

from src.models import MediaItem
from tests.conftest import JPEG_BYTES, PNG_BYTES


# ---------------------------------------------------------------------------
# Upload: Slice A — thumbnail generation on ingest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_thumbnail_path_set_for_jpeg(client, db_session_factory):
    """Uploading a JPEG sets thumbnail_path in the DB."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()

    assert item.storage_mode == "full"
    assert item.thumbnail_path is not None
    assert item.thumbnail_path.startswith("thumbnails/")
    assert item.thumbnail_path.endswith("/thumb.jpg")


@pytest.mark.asyncio
async def test_upload_storage_mode_is_full_for_browser_upload(client, db_session_factory):
    """Browser uploads always get storage_mode='full'."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()

    assert item.storage_mode == "full"
    assert item.storage_path is not None


@pytest.mark.asyncio
async def test_upload_thumbnail_failure_is_nonfatal(client, db_session_factory):
    """Upload succeeds with thumbnail_path=null when thumbnail generation fails (non-image bytes)."""
    # Create bytes that PIL cannot open as an image but pass JPEG magic-byte check in validation
    # Use valid JPEG magic bytes followed by garbage so it passes validation but fails thumbnail gen
    bad_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 50  # JPEG magic + garbage, not a complete image

    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("bad.jpg", bad_bytes, "image/jpeg")},
    )
    # Upload should succeed (not 500 or 400 due to thumbnail failure)
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()

    assert item.storage_mode == "full"
    assert item.storage_path is not None  # original is stored
    assert item.thumbnail_path is None    # thumbnail generation failed gracefully


# ---------------------------------------------------------------------------
# GET /file: retention-aware serving
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_serves_original_for_full_item(client):
    """/file returns 200 for an item with storage_mode='full' and a storage_path."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    file_resp = await client.get(f"/api/v1/media/{item_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"].startswith("image/jpeg")


@pytest.mark.asyncio
async def test_file_returns_404_original_not_retained_for_preview_only(client, db_session_factory):
    """/file returns 404 with error_code='original_not_retained' for preview_only items."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    # Transition item to preview_only via direct DB manipulation
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.storage_mode = "preview_only"
        item.storage_path = None
        await db.commit()

    file_resp = await client.get(f"/api/v1/media/{item_id}/file")
    assert file_resp.status_code == 404
    assert file_resp.json()["error_code"] == "original_not_retained"


@pytest.mark.asyncio
async def test_file_returns_404_gracefully_when_storage_path_null(client, db_session_factory):
    """/file returns 404 (not 500) when storage_path is null, even if storage_mode='full'."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    # Set storage_path=None while keeping storage_mode='full'
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.storage_path = None
        await db.commit()

    file_resp = await client.get(f"/api/v1/media/{item_id}/file")
    assert file_resp.status_code == 404
    assert file_resp.json()["error_code"] == "original_not_retained"


# ---------------------------------------------------------------------------
# GET /thumbnail: Slice A serving
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thumbnail_serves_stored_thumbnail(client, db_session_factory):
    """/thumbnail serves the stored JPEG thumbnail when thumbnail_path is set."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    # Verify thumbnail was generated
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()

    if item.thumbnail_path is None:
        pytest.skip("Thumbnail not generated — skipping thumbnail-serve test")

    thumb_resp = await client.get(f"/api/v1/media/{item_id}/thumbnail")
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"].startswith("image/jpeg")
    assert len(thumb_resp.content) > 0


@pytest.mark.asyncio
async def test_thumbnail_falls_back_to_original_for_full_items_without_thumbnail(
    client, db_session_factory
):
    """/thumbnail falls back to original file for full items when thumbnail_path is null."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    # Clear thumbnail_path to simulate pre-P8-001 items
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.thumbnail_path = None
        await db.commit()

    thumb_resp = await client.get(f"/api/v1/media/{item_id}/thumbnail")
    assert thumb_resp.status_code == 200
    # Returns original (full item, full storage_mode), may be JPEG or original MIME type
    assert len(thumb_resp.content) > 0


@pytest.mark.asyncio
async def test_thumbnail_404_for_preview_only_with_no_thumbnail(client, db_session_factory):
    """/thumbnail returns 404 for preview_only item that also has no thumbnail_path."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    # Simulate a preview_only item with failed thumbnail (edge case)
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.storage_mode = "preview_only"
        item.storage_path = None
        item.thumbnail_path = None
        await db.commit()

    thumb_resp = await client.get(f"/api/v1/media/{item_id}/thumbnail")
    assert thumb_resp.status_code == 404
    assert thumb_resp.json()["error_code"] == "preview_unavailable"


@pytest.mark.asyncio
async def test_thumbnail_serves_thumbnail_for_preview_only_item(client, db_session_factory):
    """/thumbnail correctly serves the stored thumbnail for a preview_only item."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    item_id = resp.json()["id"]

    # Transition to preview_only but keep thumbnail_path
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        if item.thumbnail_path is None:
            pytest.skip("Thumbnail not generated — skipping")
        item.storage_mode = "preview_only"
        item.storage_path = None
        await db.commit()

    thumb_resp = await client.get(f"/api/v1/media/{item_id}/thumbnail")
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"].startswith("image/jpeg")


@pytest.mark.asyncio
async def test_thumbnail_404_for_nonexistent_item(client):
    """/thumbnail returns 404 for an item that does not exist."""
    resp = await client.get("/api/v1/media/nonexistent-id/thumbnail")
    assert resp.status_code == 404
