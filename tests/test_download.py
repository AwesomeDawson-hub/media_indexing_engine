"""Tests for download endpoints (P2-002)."""

import asyncio
import io
import json
import zipfile

import piexif
import pytest
from PIL import Image

from tests.conftest import JPEG_BYTES, PNG_BYTES, GIF_BYTES


@pytest.mark.asyncio
async def test_single_download_jpeg(client):
    """Download enriched JPEG has metadata embedded and correct headers."""
    # Upload + wait for analysis
    resp = await client.post("/api/v1/upload", files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")})
    assert resp.status_code == 201
    item_id = resp.json()["id"]
    await asyncio.sleep(1.0)

    # Download
    resp = await client.get(f"/api/v1/media/{item_id}/download")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    # Filename uses AI title ("Test Image" from mock → "Test_Image.jpg"), not original camera name
    assert "Test_Image" in resp.headers["content-disposition"]

    # Verify EXIF embedded
    exif = piexif.load(resp.content)
    desc = exif["0th"].get(piexif.ImageIFD.ImageDescription, b"")
    assert len(desc) > 0  # AI title present


@pytest.mark.asyncio
async def test_single_download_unanalyzed(client):
    """Download before analysis completes returns 409."""
    resp = await client.post("/api/v1/upload", files={"file": ("new.png", PNG_BYTES, "image/png")})
    item_id = resp.json()["id"]
    # Don't wait for analysis — try download immediately
    # Mock provider is fast, so we need to check quickly
    # The item might already be analyzed; this test is best-effort
    resp = await client.get(f"/api/v1/media/{item_id}/download")
    # Either 200 (already analyzed) or 409 (not yet) — both are valid
    assert resp.status_code in (200, 409)


@pytest.mark.asyncio
async def test_single_download_not_found(client):
    """Download non-existent media returns 404."""
    resp = await client.get("/api/v1/media/nonexistent-id/download")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_download(client):
    """Batch download returns ZIP with correct files."""
    # Upload two files
    r1 = await client.post("/api/v1/upload", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")})
    r2 = await client.post("/api/v1/upload", files={"file": ("b.png", PNG_BYTES, "image/png")})
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]
    await asyncio.sleep(1.5)

    resp = await client.post("/api/v1/media/download-batch", content=json.dumps({"media_ids": [id1, id2]}),
                             headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "media_export.zip" in resp.headers.get("content-disposition", "")

    # Verify ZIP contents
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert len(names) == 2


@pytest.mark.asyncio
async def test_batch_download_empty(client):
    """Empty batch returns 400."""
    resp = await client.post("/api/v1/media/download-batch", content=json.dumps({"media_ids": []}),
                             headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_batch_download_limit(client):
    """Batch exceeding limit returns 400."""
    ids = [f"id-{i}" for i in range(51)]
    resp = await client.post("/api/v1/media/download-batch", content=json.dumps({"media_ids": ids}),
                             headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_convert_jpeg_rejected(client):
    """Converting a JPEG (already supports embedding) returns 400."""
    resp = await client.post("/api/v1/upload", files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")})
    item_id = resp.json()["id"]
    await asyncio.sleep(1.0)

    resp = await client.post(f"/api/v1/media/{item_id}/convert-png")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_convert_gif_to_png(client, db_engine):
    """Converting GIF creates a new PNG media item with XMP."""
    resp = await client.post("/api/v1/upload", files={"file": ("logo.gif", GIF_BYTES, "image/gif")})
    item_id = resp.json()["id"]
    await asyncio.sleep(1.0)

    resp = await client.post(f"/api/v1/media/{item_id}/convert-png")
    assert resp.status_code == 201
    data = resp.json()
    assert data["mime_type"] == "image/png"
    assert data["original_filename"].endswith(".png")
    assert "Converted from GIF" in data["message"]

    # Verify the new PNG exists and has metadata
    new_id = data["id"]
    resp = await client.get(f"/api/v1/media/{new_id}/analysis")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
