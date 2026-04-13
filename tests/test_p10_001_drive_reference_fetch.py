"""Tests for P10-001: On-Demand Drive Fetch for Reference Items.

Coverage:
  Service unit tests (fetch_drive_reference_bytes):
  1.  Success: returns bytes from Drive connector
  2.  Missing OriginAssetRef: raises 502 drive_fetch_failed
  3.  OriginAssetRef is non-Drive provider: raises 502 drive_fetch_failed
  4.  OriginAssetRef has no provider_object_id: raises 502 drive_fetch_failed
  5.  Missing SourceConnector: raises 502 drive_fetch_failed
  6.  DriveTokenError: raises 409 drive_auth_expired
  7.  httpx.HTTPStatusError 404: raises 404 drive_file_not_found
  8.  httpx.HTTPStatusError 410: raises 404 drive_file_not_found
  9.  httpx.HTTPStatusError 429: raises 429 drive_rate_limited
  10. httpx.TimeoutException: raises 504 drive_fetch_timeout
  11. Other exception from connector: raises 502 drive_fetch_failed

  Route tests (POST /media/{id}/reanalyze):
  12. Drive reference item: 202, job queued, file_store.save not called
  13. Non-Drive reference item: 409 original_at_source
  14. Drive reference item fetch error propagates correct status code

  Route tests (GET /media/{id}/download):
  15. Drive reference item: 200, enriched bytes served, file_store.save not called
  16. Non-Drive reference item: 409 original_at_source
  17. Drive reference item with no analysis: 409 (analysis not yet completed)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.connectors.drive_reference_fetch import (
    ERR_DRIVE_AUTH_EXPIRED,
    ERR_DRIVE_FETCH_FAILED,
    ERR_DRIVE_FETCH_TIMEOUT,
    ERR_DRIVE_FILE_NOT_FOUND,
    ERR_DRIVE_RATE_LIMITED,
    fetch_drive_reference_bytes,
)
from src.connectors.google_drive_tokens import DriveTokenError
from src.models import MediaItem, MediaMetadata, OriginAssetRef, Source, SourceConnector
from tests.conftest import DEV_USER_1, JPEG_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_drive_reference_item(db, *, provider_object_id: str = "drive-file-id-123"):
    """Insert a minimal Drive-backed reference item into the DB.

    Returns (source, connector_row, item, oar).
    """
    source = Source(
        id=_new_id(),
        user_id=DEV_USER_1,
        name="test-drive-source",
        source_type="google_drive",
    )
    db.add(source)

    connector_row = SourceConnector(
        id=_new_id(),
        source_id=source.id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        remote_container_id="root",
        remote_container_label="My Drive",
        # Credentials content is irrelevant — decrypt_credentials is patched in service tests
        credentials_encrypted="placeholder-encrypted",
    )
    db.add(connector_row)

    item = MediaItem(
        id=_new_id(),
        user_id=DEV_USER_1,
        content_hash=_new_id().replace("-", ""),
        original_filename="photo.jpg",
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
        user_id=DEV_USER_1,
        source_id=source.id,
        provider_type="google_drive",
        provider_object_id=provider_object_id,
        locator_snapshot=provider_object_id,
    )
    db.add(oar)
    await db.commit()
    await db.refresh(item)
    return source, connector_row, item, oar


async def _make_non_drive_reference_item(db):
    """Insert a local-folder reference item (no Google Drive OAR)."""
    source = Source(
        id=_new_id(),
        user_id=DEV_USER_1,
        name="local-folder-src",
        source_type="local_folder",
    )
    db.add(source)

    item = MediaItem(
        id=_new_id(),
        user_id=DEV_USER_1,
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
        user_id=DEV_USER_1,
        source_id=source.id,
        provider_type="local_folder",
        provider_object_id=None,
    )
    db.add(oar)
    await db.commit()
    await db.refresh(item)
    return source, item, oar


def _make_mock_connector(return_bytes: bytes | None = None, side_effect=None):
    """Return a mock ConnectorBase with a patched download_object."""
    connector = MagicMock()
    if side_effect is not None:
        connector.download_object = AsyncMock(side_effect=side_effect)
    else:
        connector.download_object = AsyncMock(return_value=return_bytes or JPEG_BYTES)
    return connector


# ---------------------------------------------------------------------------
# Service unit tests — fetch_drive_reference_bytes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_success(db_session_factory, seed_users):
    """Returns bytes when Drive connector successfully downloads the file."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_connector = _make_mock_connector(return_bytes=JPEG_BYTES)
        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            result = await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert result == JPEG_BYTES
    mock_connector.download_object.assert_awaited_once_with("drive-file-id-123")


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_missing_oar(db_session_factory, seed_users):
    """Raises 502 drive_fetch_failed when no OriginAssetRef exists for the item."""
    async with db_session_factory() as db:
        # Create item with no OAR
        item = MediaItem(
            id=_new_id(),
            user_id=DEV_USER_1,
            content_hash=_new_id().replace("-", ""),
            original_filename="orphan.jpg",
            file_size=100,
            mime_type="image/jpeg",
            storage_mode="reference",
            status="completed",
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)

        with pytest.raises(HTTPException) as exc_info:
            await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FETCH_FAILED


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_non_drive_oar_raises_422(db_session_factory, seed_users):
    """Raises 502 drive_fetch_failed when OriginAssetRef is for a non-Drive provider."""
    async with db_session_factory() as db:
        _, item, _ = await _make_non_drive_reference_item(db)

        with pytest.raises(HTTPException) as exc_info:
            await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FETCH_FAILED


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_no_provider_object_id_raises_422(db_session_factory, seed_users):
    """Raises 502 drive_fetch_failed when provider_object_id is None (incomplete OAR)."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db, provider_object_id=None)

        with pytest.raises(HTTPException) as exc_info:
            await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FETCH_FAILED


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_missing_connector_raises_502(db_session_factory, seed_users):
    """Raises 502 drive_fetch_failed when no SourceConnector exists."""
    async with db_session_factory() as db:
        # Create source + item + OAR but NO SourceConnector
        source = Source(id=_new_id(), user_id=DEV_USER_1, name="no-conn", source_type="google_drive")
        db.add(source)
        item = MediaItem(
            id=_new_id(),
            user_id=DEV_USER_1,
            content_hash=_new_id().replace("-", ""),
            original_filename="x.jpg",
            file_size=100,
            mime_type="image/jpeg",
            storage_mode="reference",
            status="completed",
            source_id=source.id,
        )
        db.add(item)
        db.add(OriginAssetRef(
            id=_new_id(),
            media_item_id=item.id,
            user_id=DEV_USER_1,
            source_id=source.id,
            provider_type="google_drive",
            provider_object_id="file-id",
        ))
        await db.commit()
        await db.refresh(item)

        with pytest.raises(HTTPException) as exc_info:
            await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FETCH_FAILED


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_token_error_raises_409(db_session_factory, seed_users):
    """DriveTokenError maps to 409 drive_auth_expired."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_connector = _make_mock_connector(side_effect=DriveTokenError("token expired"))
        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_AUTH_EXPIRED


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_http_404_raises_404(db_session_factory, seed_users):
    """HTTP 404 from Drive maps to 404 drive_file_not_found."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_response = MagicMock()
        mock_response.status_code = 404
        exc = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
        mock_connector = _make_mock_connector(side_effect=exc)

        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FILE_NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_http_410_raises_404(db_session_factory, seed_users):
    """HTTP 410 (Gone) from Drive also maps to 404 drive_file_not_found."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_response = MagicMock()
        mock_response.status_code = 410
        exc = httpx.HTTPStatusError("Gone", request=MagicMock(), response=mock_response)
        mock_connector = _make_mock_connector(side_effect=exc)

        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FILE_NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_rate_limit_raises_429(db_session_factory, seed_users):
    """HTTP 429 from Drive maps to 429 drive_rate_limited."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_response = MagicMock()
        mock_response.status_code = 429
        exc = httpx.HTTPStatusError("Rate Limited", request=MagicMock(), response=mock_response)
        mock_connector = _make_mock_connector(side_effect=exc)

        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_RATE_LIMITED


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_timeout_raises_504(db_session_factory, seed_users):
    """httpx.TimeoutException maps to 504 drive_fetch_timeout."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_connector = _make_mock_connector(
            side_effect=httpx.TimeoutException("connection timed out")
        )
        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FETCH_TIMEOUT


@pytest.mark.asyncio
async def test_fetch_drive_reference_bytes_other_exception_raises_502(db_session_factory, seed_users):
    """Any other exception maps to 502 drive_fetch_failed."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

        mock_connector = _make_mock_connector(side_effect=RuntimeError("something broke"))
        with (
            patch("src.connectors.drive_reference_fetch.decrypt_credentials", return_value={"refresh_token": "rt"}),
            patch("src.connectors.drive_reference_fetch.build_connector", return_value=mock_connector),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fetch_drive_reference_bytes(db, item, DEV_USER_1)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_code"] == ERR_DRIVE_FETCH_FAILED


# ---------------------------------------------------------------------------
# Route tests — POST /media/{id}/reanalyze
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reanalyze_drive_reference_returns_202(
    client, db_session_factory, seed_users, tmp_storage
):
    """Reanalyze Drive reference item: returns 202 with job_id, does not persist original."""
    import src.api.routes.upload as upload_mod

    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

    with (
        patch(
            "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
            new_callable=AsyncMock,
            return_value=JPEG_BYTES,
        ),
        patch.object(upload_mod._file_store, "save", new_callable=AsyncMock) as mock_save,
    ):
        resp = await client.post(f"/api/v1/media/{item.id}/reanalyze")

    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["media_item_id"] == item.id
    # Original bytes must never be persisted
    for call_args in mock_save.call_args_list:
        assert call_args.args[1] != JPEG_BYTES, "file_store.save called with original Drive bytes"


@pytest.mark.asyncio
async def test_reanalyze_non_drive_reference_returns_409(
    client, db_session_factory, seed_users, tmp_storage
):
    """Reanalyze non-Drive reference item still returns 409 original_at_source."""
    async with db_session_factory() as db:
        _, item, _ = await _make_non_drive_reference_item(db)

    resp = await client.post(f"/api/v1/media/{item.id}/reanalyze")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "original_at_source"


@pytest.mark.asyncio
async def test_reanalyze_drive_reference_fetch_error_propagates(
    client, db_session_factory, seed_users
):
    """Drive fetch errors surface immediately with the correct status code."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)

    with patch(
        "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=409,
            detail={"error_code": ERR_DRIVE_AUTH_EXPIRED, "message": "expired"},
        ),
    ):
        resp = await client.post(f"/api/v1/media/{item.id}/reanalyze")

    assert resp.status_code == 409
    assert resp.json()["error_code"] == ERR_DRIVE_AUTH_EXPIRED


# ---------------------------------------------------------------------------
# Route tests — GET /media/{id}/download
# ---------------------------------------------------------------------------

async def _add_metadata(db, media_item_id: str) -> None:
    """Insert minimal MediaMetadata for the given item."""
    db.add(MediaMetadata(
        id=_new_id(),
        media_item_id=media_item_id,
        title="Test Photo",
        description="description",
        tags='["nature"]',
        objects='["tree"]',
        scenes='["outdoor"]',
        context="outdoor",
        mood="calm",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors='["green"]',
        ai_provider="mock",
        ai_model="mock",
        analyzed_at=_now(),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_download_drive_reference_returns_200(
    client, db_session_factory, seed_users, tmp_storage
):
    """Download Drive reference item: returns 200 with enriched bytes, does not persist original."""
    import src.api.routes.upload as upload_mod

    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)
        await _add_metadata(db, item.id)

    with (
        patch(
            "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
            new_callable=AsyncMock,
            return_value=JPEG_BYTES,
        ),
        patch.object(upload_mod._file_store, "save", new_callable=AsyncMock) as mock_save,
    ):
        resp = await client.get(f"/api/v1/media/{item.id}/download")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert "attachment" in resp.headers.get("content-disposition", "")
    # Original bytes must never be persisted
    for call_args in mock_save.call_args_list:
        assert call_args.args[1] != JPEG_BYTES, "file_store.save called with original Drive bytes"


@pytest.mark.asyncio
async def test_download_non_drive_reference_returns_409(
    client, db_session_factory, seed_users, tmp_storage
):
    """Download non-Drive reference item still returns 409 original_at_source."""
    async with db_session_factory() as db:
        _, item, _ = await _make_non_drive_reference_item(db)

    resp = await client.get(f"/api/v1/media/{item.id}/download")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "original_at_source"


@pytest.mark.asyncio
async def test_download_drive_reference_no_metadata_returns_409(
    client, db_session_factory, seed_users
):
    """Download returns 409 when analysis is not yet completed (no metadata)."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)
        # No MediaMetadata inserted — analysis not complete

    with patch(
        "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
        new_callable=AsyncMock,
        return_value=JPEG_BYTES,
    ):
        resp = await client.get(f"/api/v1/media/{item.id}/download")

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_download_drive_reference_fetch_error_propagates(
    client, db_session_factory, seed_users
):
    """Drive fetch errors during download surface with the correct status code."""
    async with db_session_factory() as db:
        _, _, item, _ = await _make_drive_reference_item(db)
        await _add_metadata(db, item.id)

    with patch(
        "src.connectors.drive_reference_fetch.fetch_drive_reference_bytes",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=404,
            detail={"error_code": ERR_DRIVE_FILE_NOT_FOUND, "message": "file gone"},
        ),
    ):
        resp = await client.get(f"/api/v1/media/{item.id}/download")

    assert resp.status_code == 404
    assert resp.json()["error_code"] == ERR_DRIVE_FILE_NOT_FOUND
