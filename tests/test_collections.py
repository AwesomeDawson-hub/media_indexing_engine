"""Integration tests for P7-001: Collections API."""

import pytest

from tests.conftest import JPEG_BYTES, PNG_BYTES, DEV_USER_1, DEV_USER_2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _upload_jpeg(client, name: str = "photo.jpg") -> str:
    """Upload a JPEG and return the media item ID."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": (name, JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _upload_png(client, name: str = "photo.png") -> str:
    """Upload a PNG and return the media item ID."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": (name, PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_collection(client, name: str = "My Collection", description: str | None = None) -> dict:
    """Create a collection and return its JSON response."""
    body: dict = {"name": name}
    if description is not None:
        body["description"] = description
    resp = await client.post("/api/v1/collections", json=body)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v1/collections — create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_collection_returns_201(client):
    """Creating a collection returns 201 with all expected fields."""
    resp = await client.post("/api/v1/collections", json={"name": "Road Trip 2024"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Road Trip 2024"
    assert body["description"] is None
    assert body["item_count"] == 0
    assert body["cover_url"] is None
    assert len(body["id"]) == 36  # UUID
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_collection_with_description(client):
    """Description is stored and returned."""
    resp = await client.post(
        "/api/v1/collections",
        json={"name": "Portfolio", "description": "My best work"},
    )
    assert resp.status_code == 201
    assert resp.json()["description"] == "My best work"


@pytest.mark.asyncio
async def test_create_collection_strips_whitespace(client):
    """Leading/trailing whitespace is stripped from names."""
    resp = await client.post("/api/v1/collections", json={"name": "  Birthday  "})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Birthday"


@pytest.mark.asyncio
async def test_create_collection_duplicate_name_returns_409(client):
    """A duplicate name for the same user returns 409."""
    await _create_collection(client, "Vacation")
    resp = await client.post("/api/v1/collections", json={"name": "Vacation"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_collection_empty_name_rejected(client):
    """Empty name returns 422."""
    resp = await client.post("/api/v1/collections", json={"name": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_collection_name_too_long_rejected(client):
    """Name exceeding 200 characters returns 422."""
    resp = await client.post("/api/v1/collections", json={"name": "x" * 201})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_collection_same_name_different_users_allowed(client, client_user2):
    """Two different users can have collections with the same name."""
    await _create_collection(client, "Family")
    # Must succeed for user 2
    resp = await client_user2.post("/api/v1/collections", json={"name": "Family"})
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/v1/collections — list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_collections_empty(client):
    """Returns empty list when user has no collections."""
    resp = await client.get("/api/v1/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert body["collections"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_collections_returns_created(client):
    """Created collections appear in list."""
    await _create_collection(client, "Alpha")
    await _create_collection(client, "Beta")
    resp = await client.get("/api/v1/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    names = {c["name"] for c in body["collections"]}
    assert names == {"Alpha", "Beta"}


@pytest.mark.asyncio
async def test_list_collections_user_scoped(client, client_user2):
    """User 2's collections are not visible to user 1."""
    await _create_collection(client, "Mine")
    await _create_collection(client_user2, "Theirs")

    resp1 = await client.get("/api/v1/collections")
    names1 = {c["name"] for c in resp1.json()["collections"]}
    assert names1 == {"Mine"}

    resp2 = await client_user2.get("/api/v1/collections")
    names2 = {c["name"] for c in resp2.json()["collections"]}
    assert names2 == {"Theirs"}


# ---------------------------------------------------------------------------
# GET /api/v1/collections/{id} — detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_collection_empty(client):
    """Detail response for a new collection has empty items list."""
    coll = await _create_collection(client, "Empty")
    resp = await client.get(f"/api/v1/collections/{coll['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == coll["id"]
    assert body["name"] == "Empty"
    assert body["items"] == []
    assert body["item_count"] == 0


@pytest.mark.asyncio
async def test_get_collection_missing_returns_404(client):
    """Non-existent collection ID returns 404."""
    resp = await client.get("/api/v1/collections/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_collection_other_users_returns_404(client, client_user2):
    """A collection owned by another user returns 404 (IDOR protection)."""
    coll = await _create_collection(client, "Private")
    resp = await client_user2.get(f"/api/v1/collections/{coll['id']}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_collection_with_items(client):
    """Detail response includes items and correct item_count after adding."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "With Items")
    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    resp = await client.get(f"/api/v1/collections/{coll['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["item_count"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == item_id


# ---------------------------------------------------------------------------
# PATCH /api/v1/collections/{id} — update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_collection_name(client):
    """Renaming a collection returns the updated name."""
    coll = await _create_collection(client, "Old Name")
    resp = await client.patch(
        f"/api/v1/collections/{coll['id']}",
        json={"name": "New Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_update_collection_description(client):
    """Updating only description leaves name unchanged."""
    coll = await _create_collection(client, "Named", description="First")
    resp = await client.patch(
        f"/api/v1/collections/{coll['id']}",
        json={"description": "Updated"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Named"
    assert body["description"] == "Updated"


@pytest.mark.asyncio
async def test_update_collection_duplicate_name_returns_409(client):
    """Renaming to an existing collection name returns 409."""
    await _create_collection(client, "Existing")
    coll2 = await _create_collection(client, "To Rename")
    resp = await client.patch(
        f"/api/v1/collections/{coll2['id']}",
        json={"name": "Existing"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_collection_missing_returns_404(client):
    """PATCH on a non-existent collection returns 404."""
    resp = await client.patch(
        "/api/v1/collections/00000000-0000-0000-0000-000000000000",
        json={"name": "Whatever"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_collection_other_users_returns_404(client, client_user2):
    """PATCH on another user's collection returns 404 (IDOR protection)."""
    coll = await _create_collection(client, "Protected")
    resp = await client_user2.patch(
        f"/api/v1/collections/{coll['id']}",
        json={"name": "Hijacked"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/collections/{id} — delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_collection_returns_204(client):
    """Deleting a collection returns 204."""
    coll = await _create_collection(client, "To Delete")
    resp = await client.delete(f"/api/v1/collections/{coll['id']}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_collection_removes_from_list(client):
    """Deleted collection no longer appears in list."""
    coll = await _create_collection(client, "Ephemeral")
    await client.delete(f"/api/v1/collections/{coll['id']}")
    resp = await client.get("/api/v1/collections")
    ids = [c["id"] for c in resp.json()["collections"]]
    assert coll["id"] not in ids


@pytest.mark.asyncio
async def test_delete_collection_missing_returns_404(client):
    """DELETE on a non-existent collection returns 404."""
    resp = await client.delete("/api/v1/collections/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_collection_other_users_returns_404(client, client_user2):
    """DELETE on another user's collection returns 404 (IDOR protection)."""
    coll = await _create_collection(client, "Safe")
    resp = await client_user2.delete(f"/api/v1/collections/{coll['id']}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_collection_does_not_delete_media_items(client):
    """Deleting a collection does not delete the underlying media items."""
    item_id = await _upload_jpeg(client, "keep.jpg")
    coll = await _create_collection(client, "Container")
    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    await client.delete(f"/api/v1/collections/{coll['id']}")

    # Media item must still exist
    resp = await client.get(f"/api/v1/media/{item_id}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/collections/{id}/items — add items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_items_returns_added_count(client):
    """Adding items returns the correct added count."""
    item_id = await _upload_jpeg(client, "img1.jpg")
    coll = await _create_collection(client, "Additions")
    resp = await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["added"] == 1
    assert body["skipped"] == 0


@pytest.mark.asyncio
async def test_add_items_idempotent(client):
    """Adding the same item twice skips the duplicate."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "Idempotent")
    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    resp = await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["added"] == 0
    assert body["skipped"] == 1


@pytest.mark.asyncio
async def test_add_items_cross_user_media_silently_skipped(client, client_user2):
    """Media items owned by another user are silently skipped (IDOR protection)."""
    # Upload a jpeg as user 2
    other_item_id = await _upload_jpeg(client_user2, "other.jpg")
    # User 1 tries to add user 2's item to their collection
    coll = await _create_collection(client, "Safe Collection")
    resp = await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [other_item_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Should be skipped (0 added) rather than returning 404 (to avoid enumeration)
    assert body["added"] == 0


@pytest.mark.asyncio
async def test_add_items_to_missing_collection_returns_404(client):
    """Adding items to a non-existent collection returns 404."""
    item_id = await _upload_jpeg(client, "img.jpg")
    resp = await client.post(
        "/api/v1/collections/00000000-0000-0000-0000-000000000000/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_items_to_other_users_collection_returns_404(client, client_user2):
    """Adding items to another user's collection returns 404 (IDOR protection)."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "User1 Coll")
    resp = await client_user2.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_multiple_items(client):
    """Multiple distinct items are each added once."""
    id1 = await _upload_jpeg(client, "a.jpg")
    id2 = await _upload_png(client, "b.png")
    coll = await _create_collection(client, "Multi")
    resp = await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [id1, id2]},
    )
    assert resp.status_code == 200
    assert resp.json()["added"] == 2


# ---------------------------------------------------------------------------
# DELETE /api/v1/collections/{id}/items — remove items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_items_returns_removed_count(client):
    """Removing items returns the correct removed count."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "Removal Test")
    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    resp = await client.request(
        "DELETE",
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["removed"] == 1


@pytest.mark.asyncio
async def test_remove_items_not_in_collection_is_idempotent(client):
    """Removing an item that isn't in the collection returns 0 removed (no error)."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "Empty Removal")
    resp = await client.request(
        "DELETE",
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["removed"] == 0


@pytest.mark.asyncio
async def test_remove_items_from_missing_collection_returns_404(client):
    """Removing items from a non-existent collection returns 404."""
    item_id = await _upload_jpeg(client, "img.jpg")
    resp = await client.request(
        "DELETE",
        "/api/v1/collections/00000000-0000-0000-0000-000000000000/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remove_items_from_other_users_collection_returns_404(client, client_user2):
    """Removing items from another user's collection returns 404."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "Protected")
    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    resp = await client_user2.request(
        "DELETE",
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remove_item_then_count_decreases(client):
    """item_count in list drops to 0 after all items are removed."""
    item_id = await _upload_jpeg(client, "img.jpg")
    coll = await _create_collection(client, "Decrement")
    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    await client.request(
        "DELETE",
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )
    resp = await client.get("/api/v1/collections")
    coll_data = next(c for c in resp.json()["collections"] if c["id"] == coll["id"])
    assert coll_data["item_count"] == 0


# ---------------------------------------------------------------------------
# Cover URL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cover_url_set_after_adding_item(client):
    """cover_url is filled once at least one item is in the collection."""
    item_id = await _upload_jpeg(client, "cover.jpg")
    coll = await _create_collection(client, "Cover Test")
    assert coll["cover_url"] is None

    await client.post(
        f"/api/v1/collections/{coll['id']}/items",
        json={"media_item_ids": [item_id]},
    )

    resp = await client.get("/api/v1/collections")
    updated = next(c for c in resp.json()["collections"] if c["id"] == coll["id"])
    assert updated["cover_url"] is not None
    assert item_id in updated["cover_url"]
