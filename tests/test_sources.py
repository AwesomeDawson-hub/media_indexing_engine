"""Integration tests for P4-003: Sources API and source-aware media."""

import pytest

from tests.conftest import JPEG_BYTES, PNG_BYTES, DEV_USER_1, DEV_USER_2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_source(client, name: str = "Test Source", source_type: str = "manual") -> dict:
    """Create a source and return the JSON body."""
    resp = await client.post(
        "/api/v1/sources",
        json={"name": name, "source_type": source_type},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v1/sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_source_returns_201(client):
    """Creating a source returns 201 with correct fields."""
    resp = await client.post(
        "/api/v1/sources",
        json={"name": "Campaign A", "source_type": "manual"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Campaign A"
    assert body["source_type"] == "manual"
    assert body["archived_at"] is None
    assert len(body["id"]) == 36  # UUID
    assert "created_at" in body


@pytest.mark.asyncio
async def test_create_source_default_type(client):
    """Omitting source_type defaults to 'manual'."""
    resp = await client.post("/api/v1/sources", json={"name": "My Source"})
    assert resp.status_code == 201
    assert resp.json()["source_type"] == "manual"


@pytest.mark.asyncio
async def test_create_source_empty_name_rejected(client):
    """An empty name is rejected with 422."""
    resp = await client.post("/api/v1/sources", json={"name": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_name_too_long_rejected(client):
    """A name exceeding 200 characters is rejected with 422."""
    resp = await client.post("/api/v1/sources", json={"name": "x" * 201})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_sources_empty(client):
    """No sources returns an empty list."""
    resp = await client.get("/api/v1/sources")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_sources_returns_created(client):
    """Created sources appear in list."""
    await _create_source(client, "Source 1")
    await _create_source(client, "Source 2")

    resp = await client.get("/api/v1/sources")
    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()}
    assert names == {"Source 1", "Source 2"}


@pytest.mark.asyncio
async def test_list_sources_excludes_archived_by_default(client):
    """Archived sources are hidden from the default list."""
    src = await _create_source(client, "To Archive")
    await client.post(f"/api/v1/sources/{src['id']}/archive")

    resp = await client.get("/api/v1/sources")
    assert resp.status_code == 200
    assert all(s["id"] != src["id"] for s in resp.json())


@pytest.mark.asyncio
async def test_list_sources_include_archived(client):
    """include_archived=true returns archived sources too."""
    src = await _create_source(client, "Archived Source")
    await client.post(f"/api/v1/sources/{src['id']}/archive")

    resp = await client.get("/api/v1/sources?include_archived=true")
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()}
    assert src["id"] in ids


@pytest.mark.asyncio
async def test_list_sources_is_user_scoped(client, client_user2):
    """User 1's sources are not visible to user 2."""
    await _create_source(client, "User 1 Source")

    resp = await client_user2.get("/api/v1/sources")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/v1/sources/{id}/archive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_archive_source(client):
    """Archiving a source sets archived_at."""
    src = await _create_source(client, "Active Source")
    assert src["archived_at"] is None

    resp = await client.post(f"/api/v1/sources/{src['id']}/archive")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == src["id"]
    assert body["archived_at"] is not None


@pytest.mark.asyncio
async def test_archive_source_idempotent(client):
    """Archiving an already-archived source is safe and returns the same archived_at."""
    src = await _create_source(client, "Source")
    resp1 = await client.post(f"/api/v1/sources/{src['id']}/archive")
    archived_at_1 = resp1.json()["archived_at"]

    resp2 = await client.post(f"/api/v1/sources/{src['id']}/archive")
    assert resp2.status_code == 200
    assert resp2.json()["archived_at"] == archived_at_1


@pytest.mark.asyncio
async def test_archive_source_not_found(client):
    """Archiving a non-existent source returns 404."""
    resp = await client.post("/api/v1/sources/does-not-exist/archive")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_source_other_user_404(client, client_user2):
    """Archiving another user's source returns 404 (not 403 — no info leak)."""
    src = await _create_source(client, "User 1 Source")

    resp = await client_user2.post(f"/api/v1/sources/{src['id']}/archive")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/sources/{id}/restore
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_source(client):
    """Restoring an archived source clears archived_at."""
    src = await _create_source(client, "Source")
    await client.post(f"/api/v1/sources/{src['id']}/archive")

    resp = await client.post(f"/api/v1/sources/{src['id']}/restore")
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None


@pytest.mark.asyncio
async def test_restore_source_idempotent(client):
    """Restoring an already-active source is safe."""
    src = await _create_source(client, "Source")

    resp = await client.post(f"/api/v1/sources/{src['id']}/restore")
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None


@pytest.mark.asyncio
async def test_restore_source_not_found(client):
    """Restoring a non-existent source returns 404."""
    resp = await client.post("/api/v1/sources/does-not-exist/restore")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_source_other_user_404(client, client_user2):
    """Restoring another user's source returns 404."""
    src = await _create_source(client, "User 1 Source")
    await client.post(f"/api/v1/sources/{src['id']}/archive")

    resp = await client_user2.post(f"/api/v1/sources/{src['id']}/restore")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# source_id filter on GET /api/v1/media
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_filter_by_source_id(client):
    """Items uploaded with a source_id are returned when filtering by that source_id."""
    src = await _create_source(client, "Campaign B")

    # Upload one tagged, one untagged
    await client.post(
        "/api/v1/upload",
        data={"source_id": src["id"]},
        files={"file": ("tagged.jpg", JPEG_BYTES, "image/jpeg")},
    )
    await client.post(
        "/api/v1/upload",
        files={"file": ("untagged.png", PNG_BYTES, "image/png")},
    )

    resp = await client.get(f"/api/v1/media?source_id={src['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["source_id"] == src["id"]
    assert body["items"][0]["original_filename"] == "tagged.jpg"


@pytest.mark.asyncio
async def test_media_source_id_returned_in_response(client):
    """MediaItemResponse includes source_id after upload with source."""
    src = await _create_source(client, "Campaign C")

    up_resp = await client.post(
        "/api/v1/upload",
        data={"source_id": src["id"]},
        files={"file": ("img.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert up_resp.status_code == 201
    item_id = up_resp.json()["id"]

    media_resp = await client.get(f"/api/v1/media/{item_id}")
    assert media_resp.status_code == 200
    assert media_resp.json()["source_id"] == src["id"]


@pytest.mark.asyncio
async def test_media_filter_no_match_returns_empty(client):
    """Filtering by a source_id with no uploads returns total=0."""
    src = await _create_source(client, "Empty Source")

    resp = await client.get(f"/api/v1/media?source_id={src['id']}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# source_id IDOR protection on upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_with_valid_source_id(client):
    """Upload with own source_id succeeds."""
    src = await _create_source(client, "Own Source")

    resp = await client.post(
        "/api/v1/upload",
        data={"source_id": src["id"]},
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_upload_with_nonexistent_source_id_returns_404(client):
    """Upload referencing a non-existent source_id returns 404."""
    resp = await client.post(
        "/api/v1/upload",
        data={"source_id": "00000000-0000-0000-0000-000000000000"},
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_with_other_users_source_id_returns_403(client, client_user2):
    """Upload referencing another user's source_id is forbidden (IDOR protection)."""
    src = await _create_source(client, "User 1 Source")

    # User 2 tries to tag an upload with user 1's source
    resp = await client_user2.post(
        "/api/v1/upload",
        data={"source_id": src["id"]},
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_without_source_id_succeeds(client):
    """Upload without source_id still works (source_id is optional)."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201
    assert resp.json()["is_duplicate"] is False
