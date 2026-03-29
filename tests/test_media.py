"""Integration tests for media list/detail endpoints."""

import pytest
from tests.conftest import JPEG_BYTES, PNG_BYTES, GIF_BYTES


@pytest.mark.asyncio
async def test_list_media_empty(client):
    """Empty library returns zero items."""
    resp = await client.get("/api/v1/media")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_media_with_items(client):
    """List returns uploaded items."""
    await client.post("/api/v1/upload", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")})
    await client.post("/api/v1/upload", files={"file": ("b.png", PNG_BYTES, "image/png")})

    resp = await client.get("/api/v1/media")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_media_pagination(client):
    """Pagination works correctly."""
    await client.post("/api/v1/upload", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")})
    await client.post("/api/v1/upload", files={"file": ("b.png", PNG_BYTES, "image/png")})
    await client.post("/api/v1/upload", files={"file": ("c.gif", GIF_BYTES, "image/gif")})

    resp = await client.get("/api/v1/media", params={"page": 1, "per_page": 2})
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["page"] == 1

    resp = await client.get("/api/v1/media", params={"page": 2, "per_page": 2})
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 1
    assert data["page"] == 2


@pytest.mark.asyncio
async def test_get_media_by_id(client):
    """Get a single item by ID."""
    upload_resp = await client.post(
        "/api/v1/upload", files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")}
    )
    item_id = upload_resp.json()["id"]

    resp = await client.get(f"/api/v1/media/{item_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == item_id
    assert data["original_filename"] == "photo.jpg"


@pytest.mark.asyncio
async def test_get_media_not_found(client):
    """Non-existent ID returns 404."""
    resp = await client.get("/api/v1/media/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_media_isolation_between_users(client, client_user2):
    """Users can only see their own media."""
    # User 1 uploads
    await client.post("/api/v1/upload", files={"file": ("u1.jpg", JPEG_BYTES, "image/jpeg")})

    # User 2 uploads
    await client_user2.post("/api/v1/upload", files={"file": ("u2.png", PNG_BYTES, "image/png")})

    # User 1 sees only their item
    resp1 = await client.get("/api/v1/media")
    assert resp1.json()["total"] == 1
    assert resp1.json()["items"][0]["original_filename"] == "u1.jpg"

    # User 2 sees only their item
    resp2 = await client_user2.get("/api/v1/media")
    assert resp2.json()["total"] == 1
    assert resp2.json()["items"][0]["original_filename"] == "u2.png"
