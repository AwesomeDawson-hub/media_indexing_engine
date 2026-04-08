"""Tests for P7-004: Source Mutation Completion States.

Coverage:
  - scope_has_write: True for readable scope, False for read-only / NULL
  - verify_state: returns 3-tuple (user_id, source_id, mode) for new format
  - verify_state: legacy 3-part state returns mode="connect" (backward compat)
  - _slugify / _target_filename unit tests
  - drive_mutation_service: blocked_writeback when connector has read-only scope
  - drive_mutation_service: blocked_writeback when no SourceObject drive file ID
  - drive_mutation_service: fully_applied on Drive PATCH HTTP 200
  - drive_mutation_service: pending_writeback on Drive PATCH HTTP 500
  - drive_mutation_service: first_seen_source_filename set on first attempt
  - drive_mutation_service: history row written on each attempt
  - No source_id on MediaItem → mutation_state remains NULL (early return)
  - POST /media/{id}/mutation-result succeeded=True → fully_applied
  - POST /media/{id}/mutation-result succeeded=False → blocked_writeback
  - POST /media/{id}/mutation-result history row persisted
  - POST /media/{id}/mutation-result 404 for unknown item
  - POST /media/{id}/retry-writeback pending_writeback → fully_applied (mocked Drive 200)
  - POST /media/{id}/retry-writeback non-pending state → 422
  - POST /media/{id}/retry-writeback blocked_writeback → 422
  - POST /media/{id}/retry-writeback unknown item → 404
  - POST /media/{id}/retry-writeback wrong user → 404
  - POST /media/{id}/retry-writeback stays pending_writeback on transient Drive failure
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from tests.conftest import DEV_USER_1, DEV_USER_2, JPEG_BYTES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")
_TEST_SECRET_KEY = "test-secret-for-mutation-tests"

_DRIVE_CONFIG = {
    "enabled": True,
    "client_id": "mut-client-id",
    "client_secret": "mut-client-secret",
    "redirect_uri": "http://localhost:8000/api/v1/connectors/google-drive/callback",
    "frontend_url": "http://localhost:5173",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encrypt_credentials(creds: dict, key: str) -> str:
    """Encrypt a credential dict with the given Fernet key."""
    f = Fernet(key.encode())
    return f.encrypt(json.dumps(creds).encode()).decode()


# ---------------------------------------------------------------------------
# 1. scope_has_write unit tests
# ---------------------------------------------------------------------------

def test_scope_has_write_with_readwrite_scope():
    from src.auth.google_drive_oauth import scope_has_write, DRIVE_SCOPE_READWRITE
    assert scope_has_write(DRIVE_SCOPE_READWRITE) is True


def test_scope_has_write_with_readonly_scope():
    from src.auth.google_drive_oauth import scope_has_write, DRIVE_SCOPE_READONLY
    assert scope_has_write(DRIVE_SCOPE_READONLY) is False


def test_scope_has_write_with_none():
    from src.auth.google_drive_oauth import scope_has_write
    assert scope_has_write(None) is False


def test_scope_has_write_with_empty_string():
    from src.auth.google_drive_oauth import scope_has_write
    assert scope_has_write("") is False


def test_scope_has_write_readwrite_in_compound_scope():
    from src.auth.google_drive_oauth import scope_has_write, DRIVE_SCOPE_READWRITE
    # Space-separated compound scope string
    compound = f"openid email {DRIVE_SCOPE_READWRITE}"
    assert scope_has_write(compound) is True


# ---------------------------------------------------------------------------
# 2. verify_state — 3-tuple + legacy backward compat
# ---------------------------------------------------------------------------

def test_verify_state_returns_three_tuple():
    """verify_state returns (user_id, source_id, mode) for a new-format state."""
    from src.auth.google_drive_oauth import sign_state, verify_state

    signed = sign_state("user-1", "source-1", "nonce-1", _TEST_SECRET_KEY, mode="connect")
    user_id, source_id, mode = verify_state(signed, "nonce-1", _TEST_SECRET_KEY)

    assert user_id == "user-1"
    assert source_id == "source-1"
    assert mode == "connect"


def test_verify_state_upgrade_mode():
    """verify_state correctly returns mode='upgrade' for scope-upgrade flows."""
    from src.auth.google_drive_oauth import sign_state, verify_state

    signed = sign_state("user-1", "source-1", "nonce-u", _TEST_SECRET_KEY, mode="upgrade")
    user_id, source_id, mode = verify_state(signed, "nonce-u", _TEST_SECRET_KEY)

    assert mode == "upgrade"


def test_verify_state_legacy_three_part_returns_connect_mode():
    """Legacy 3-part state strings (P7-002) return mode='connect' for backward compat."""
    import hashlib, hmac

    secret = _TEST_SECRET_KEY
    nonce = "legacy-nonce"
    user_id = "user-l"
    source_id = "source-l"

    # Craft a legacy 3-part state: user_id|source_id|nonce (no mode)
    raw_state = f"{user_id}|{source_id}|{nonce}"
    ts_str = str(int(time.time()))
    msg = f"{raw_state}:{ts_str}".encode()
    sig = hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
    legacy_signed = f"{raw_state}.{ts_str}.{sig}"

    from src.auth.google_drive_oauth import verify_state
    uid, sid, mode = verify_state(legacy_signed, nonce, secret)

    assert uid == user_id
    assert sid == source_id
    assert mode == "connect"


# ---------------------------------------------------------------------------
# 3. _slugify / _target_filename unit tests
# ---------------------------------------------------------------------------

def test_slugify_basic():
    from src.analysis.drive_mutation_service import _slugify
    assert _slugify("Hello World") == "hello_world"


def test_slugify_special_chars():
    from src.analysis.drive_mutation_service import _slugify
    assert _slugify("Café au lait!") == "caf_au_lait"


def test_slugify_empty_produces_untitled():
    from src.analysis.drive_mutation_service import _slugify
    assert _slugify("") == "untitled"


def test_slugify_all_special_chars():
    from src.analysis.drive_mutation_service import _slugify
    assert _slugify("!@#$%") == "untitled"


def test_target_filename_preserves_extension():
    from src.analysis.drive_mutation_service import _target_filename
    result = _target_filename("Golden Gate Bridge", "IMG_1234.JPG")
    assert result == "golden_gate_bridge.jpg"


def test_target_filename_no_extension():
    from src.analysis.drive_mutation_service import _target_filename
    result = _target_filename("My Photo", "myfile")
    assert result == "my_photo"


# ---------------------------------------------------------------------------
# 4. Service-level tests — drive_mutation_service (unit, async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mutation_service_no_source_id_skips(db: AsyncSession):
    """attempt_drive_rename_after_analysis returns immediately when item has no source_id."""
    from src.models import MediaItem
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    item = MediaItem(
        id=_new_id(),
        user_id=DEV_USER_1,
        content_hash="abc123",
        original_filename="photo.jpg",
        file_size=1000,
        mime_type="image/jpeg",
        storage_path="/tmp/photo.jpg",
        status="completed",
        source_id=None,  # No source → early return
    )
    db.add(item)
    await db.commit()

    await attempt_drive_rename_after_analysis(db, item)

    assert item.mutation_state is None


@pytest.mark.asyncio
async def test_mutation_service_blocked_writeback_readonly_scope(db: AsyncSession, monkeypatch):
    """blocked_writeback is set when the Drive connector has no write scope."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", True)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", _DRIVE_CONFIG["client_id"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", _DRIVE_CONFIG["client_secret"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", _DRIVE_CONFIG["redirect_uri"])

    from src.models import Source, MediaItem, MediaMetadata, SourceConnector
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    source_id = _new_id()
    item_id = _new_id()

    source = Source(id=source_id, user_id=DEV_USER_1, name="Drive Source", source_type="drive")
    db.add(source)

    item = MediaItem(
        id=item_id,
        user_id=DEV_USER_1,
        content_hash="def456",
        original_filename="shot.jpg",
        file_size=2000,
        mime_type="image/jpeg",
        storage_path="/tmp/shot.jpg",
        status="completed",
        source_id=source_id,
    )
    db.add(item)

    # Connector with read-only scope
    creds_enc = _encrypt_credentials(
        {"access_token": "at", "refresh_token": "rt"},
        _TEST_FERNET_KEY,
    )
    connector = SourceConnector(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        credentials_encrypted=creds_enc,
        remote_container_id="my-drive-root",
        granted_scopes="https://www.googleapis.com/auth/drive.readonly",  # read-only
    )
    db.add(connector)

    metadata = MediaMetadata(
        id=_new_id(),
        media_item_id=item_id,
        title="Beautiful Sunset",
        description="A stunning sunset",
        tags="[]",
        objects="[]",
        scenes="[]",
        context="landscape",
        mood="calm",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors="[]",
        ai_provider="mock",
        ai_model="mock-v1",
        analyzed_at=_now(),
    )
    db.add(metadata)
    await db.commit()

    await attempt_drive_rename_after_analysis(db, item)

    assert item.mutation_state == "blocked_writeback"
    assert item.last_mutation_error_code == "no_write_scope"
    assert item.first_seen_source_filename == "shot.jpg"


@pytest.mark.asyncio
async def test_mutation_service_blocked_writeback_no_source_object(db: AsyncSession, monkeypatch):
    """blocked_writeback when no SourceObject row exists (cannot find Drive file ID)."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", True)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", _DRIVE_CONFIG["client_id"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", _DRIVE_CONFIG["client_secret"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", _DRIVE_CONFIG["redirect_uri"])

    from src.models import Source, MediaItem, MediaMetadata, SourceConnector
    from src.auth.google_drive_oauth import DRIVE_SCOPE_READWRITE
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    source_id = _new_id()
    item_id = _new_id()

    source = Source(id=source_id, user_id=DEV_USER_1, name="Drive W", source_type="drive")
    db.add(source)

    item = MediaItem(
        id=item_id,
        user_id=DEV_USER_1,
        content_hash="ghi789",
        original_filename="family.jpg",
        file_size=3000,
        mime_type="image/jpeg",
        storage_path="/tmp/family.jpg",
        status="completed",
        source_id=source_id,
    )
    db.add(item)

    creds_enc = _encrypt_credentials(
        {"access_token": "at", "refresh_token": "rt"},
        _TEST_FERNET_KEY,
    )
    connector = SourceConnector(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        credentials_encrypted=creds_enc,
        remote_container_id="my-drive-root",
        granted_scopes=DRIVE_SCOPE_READWRITE,  # writable scope granted
    )
    db.add(connector)

    metadata = MediaMetadata(
        id=_new_id(),
        media_item_id=item_id,
        title="Family Portrait",
        description="Family photo",
        tags="[]",
        objects="[]",
        scenes="[]",
        context="portrait",
        mood="happy",
        people="[]",
        people_count=3,
        orientation="portrait",
        colors="[]",
        ai_provider="mock",
        ai_model="mock-v1",
        analyzed_at=_now(),
    )
    db.add(metadata)
    await db.commit()

    # Stub token fetch to succeed (skip real HTTP call to Google)
    with patch(
        "src.connectors.google_drive_tokens.DriveTokenManager.get_access_token",
        new_callable=AsyncMock,
        return_value="fake-access-token",
    ):
        await attempt_drive_rename_after_analysis(db, item)

    # No SourceObject row → cannot find drive_file_id
    assert item.mutation_state == "blocked_writeback"
    assert item.last_mutation_error_code == "no_drive_file_id"


@pytest.mark.asyncio
async def test_mutation_service_fully_applied_on_drive_200(db: AsyncSession, monkeypatch):
    """fully_applied is set when Drive PATCH returns HTTP 200."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", True)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", _DRIVE_CONFIG["client_id"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", _DRIVE_CONFIG["client_secret"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", _DRIVE_CONFIG["redirect_uri"])

    from src.models import Source, MediaItem, MediaMetadata, SourceConnector, SourceObject, SourceMutationHistory
    from src.auth.google_drive_oauth import DRIVE_SCOPE_READWRITE
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    source_id = _new_id()
    item_id = _new_id()
    drive_file_id = "gdrive-file-abc"

    source = Source(id=source_id, user_id=DEV_USER_1, name="Drive Full", source_type="drive")
    db.add(source)

    item = MediaItem(
        id=item_id,
        user_id=DEV_USER_1,
        content_hash="jkl012",
        original_filename="landscape.jpg",
        file_size=5000,
        mime_type="image/jpeg",
        storage_path="/tmp/landscape.jpg",
        status="completed",
        source_id=source_id,
    )
    db.add(item)

    creds_enc = _encrypt_credentials(
        {"access_token": "at", "refresh_token": "rt"},
        _TEST_FERNET_KEY,
    )
    connector = SourceConnector(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        credentials_encrypted=creds_enc,
        remote_container_id="my-drive-root",
        granted_scopes=DRIVE_SCOPE_READWRITE,
    )
    db.add(connector)

    source_object = SourceObject(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        external_object_key=drive_file_id,
        last_imported_media_item_id=item_id,
        state="imported",
    )
    db.add(source_object)

    metadata = MediaMetadata(
        id=_new_id(),
        media_item_id=item_id,
        title="Rolling Hills",
        description="Wide open landscape",
        tags="[]",
        objects="[]",
        scenes="[]",
        context="nature",
        mood="serene",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors="[]",
        ai_provider="mock",
        ai_model="mock-v1",
        analyzed_at=_now(),
    )
    db.add(metadata)
    await db.commit()

    # Mock token fetch and Drive PATCH to return 200
    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 200
    mock_patch_resp.json.return_value = {"id": drive_file_id, "name": "rolling_hills.jpg"}

    with (
        patch(
            "src.connectors.google_drive_tokens.DriveTokenManager.get_access_token",
            new_callable=AsyncMock,
            return_value="fake-access-token",
        ),
        patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=mock_patch_resp),
    ):
        await attempt_drive_rename_after_analysis(db, item)
        await db.commit()

    assert item.mutation_state == "fully_applied"
    assert item.prior_source_filename == "landscape.jpg"
    assert item.source_filename_applied_at is not None
    assert item.last_mutation_error_code is None

    # Verify history row was written
    result = await db.execute(
        select(SourceMutationHistory).where(SourceMutationHistory.media_item_id == item_id)
    )
    history_rows = result.scalars().all()
    assert len(history_rows) == 1
    assert history_rows[0].succeeded is True
    assert history_rows[0].operation_type == "rename"


@pytest.mark.asyncio
async def test_mutation_service_pending_writeback_on_drive_500(db: AsyncSession, monkeypatch):
    """pending_writeback is set when Drive PATCH returns HTTP 500 (transient error)."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", True)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", _DRIVE_CONFIG["client_id"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", _DRIVE_CONFIG["client_secret"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", _DRIVE_CONFIG["redirect_uri"])

    from src.models import Source, MediaItem, MediaMetadata, SourceConnector, SourceObject
    from src.auth.google_drive_oauth import DRIVE_SCOPE_READWRITE
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    source_id = _new_id()
    item_id = _new_id()
    drive_file_id = "gdrive-file-500"

    source = Source(id=source_id, user_id=DEV_USER_1, name="Drive 500", source_type="drive")
    db.add(source)

    item = MediaItem(
        id=item_id,
        user_id=DEV_USER_1,
        content_hash="mno345",
        original_filename="city.jpg",
        file_size=4000,
        mime_type="image/jpeg",
        storage_path="/tmp/city.jpg",
        status="completed",
        source_id=source_id,
    )
    db.add(item)

    creds_enc = _encrypt_credentials(
        {"access_token": "at", "refresh_token": "rt"},
        _TEST_FERNET_KEY,
    )
    connector = SourceConnector(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        credentials_encrypted=creds_enc,
        remote_container_id="my-drive-root",
        granted_scopes=DRIVE_SCOPE_READWRITE,
    )
    db.add(connector)

    source_object = SourceObject(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        external_object_key=drive_file_id,
        last_imported_media_item_id=item_id,
        state="imported",
    )
    db.add(source_object)

    metadata = MediaMetadata(
        id=_new_id(),
        media_item_id=item_id,
        title="City at Night",
        description="Beautiful city lights",
        tags="[]",
        objects="[]",
        scenes="[]",
        context="urban",
        mood="dynamic",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors="[]",
        ai_provider="mock",
        ai_model="mock-v1",
        analyzed_at=_now(),
    )
    db.add(metadata)
    await db.commit()

    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 500
    mock_patch_resp.text = "Internal Server Error"

    with (
        patch(
            "src.connectors.google_drive_tokens.DriveTokenManager.get_access_token",
            new_callable=AsyncMock,
            return_value="fake-access-token",
        ),
        patch("httpx.AsyncClient.patch", new_callable=AsyncMock, return_value=mock_patch_resp),
    ):
        await attempt_drive_rename_after_analysis(db, item)

    assert item.mutation_state == "pending_writeback"
    assert item.last_mutation_error_code == "drive_api_error"


@pytest.mark.asyncio
async def test_mutation_service_first_seen_source_filename_set_once(db: AsyncSession, monkeypatch):
    """first_seen_source_filename is set on the first attempt and not overwritten."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", True)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", _DRIVE_CONFIG["client_id"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", _DRIVE_CONFIG["client_secret"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", _DRIVE_CONFIG["redirect_uri"])

    from src.models import Source, MediaItem, MediaMetadata, SourceConnector
    from src.auth.google_drive_oauth import DRIVE_SCOPE_READONLY
    from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis

    source_id = _new_id()
    item_id = _new_id()

    source = Source(id=source_id, user_id=DEV_USER_1, name="Drive First", source_type="drive")
    db.add(source)

    item = MediaItem(
        id=item_id,
        user_id=DEV_USER_1,
        content_hash="pqr678",
        original_filename="original_name.jpg",
        file_size=1500,
        mime_type="image/jpeg",
        storage_path="/tmp/original_name.jpg",
        status="completed",
        source_id=source_id,
        first_seen_source_filename=None,  # not set yet
    )
    db.add(item)

    creds_enc = _encrypt_credentials(
        {"access_token": "at", "refresh_token": "rt"},
        _TEST_FERNET_KEY,
    )
    connector = SourceConnector(
        id=_new_id(),
        source_id=source_id,
        user_id=DEV_USER_1,
        connector_type="google_drive",
        credentials_encrypted=creds_enc,
        remote_container_id="my-drive-root",
        granted_scopes=DRIVE_SCOPE_READONLY,  # read-only → blocked immediately
    )
    db.add(connector)

    metadata = MediaMetadata(
        id=_new_id(),
        media_item_id=item_id,
        title="Mountain View",
        description="A mountain",
        tags="[]",
        objects="[]",
        scenes="[]",
        context="nature",
        mood="peaceful",
        people="[]",
        people_count=0,
        orientation="landscape",
        colors="[]",
        ai_provider="mock",
        ai_model="mock-v1",
        analyzed_at=_now(),
    )
    db.add(metadata)
    await db.commit()

    await attempt_drive_rename_after_analysis(db, item)

    # first_seen_source_filename should be captured from original_filename
    assert item.first_seen_source_filename == "original_name.jpg"

    # Simulate a second run (e.g. re-analysis) — first_seen should not be overwritten
    item.first_seen_source_filename = "should_not_change.jpg"
    item.original_filename = "new_name.jpg"
    await attempt_drive_rename_after_analysis(db, item)

    assert item.first_seen_source_filename == "should_not_change.jpg"


# ---------------------------------------------------------------------------
# 5. API endpoint tests — POST /media/{id}/mutation-result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_mutation_result_succeeded_true(client):
    """POST mutation-result with succeeded=True sets fully_applied."""
    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("photo.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={
            "succeeded": True,
            "operation_type": "rename",
            "new_filename": "beautiful_photo.jpg",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mutation_state"] == "fully_applied"
    assert data["media_item_id"] == item_id
    assert data["prior_source_filename"] == "photo.jpg"
    assert data["source_filename_applied_at"] is not None


@pytest.mark.asyncio
async def test_local_mutation_result_succeeded_false(client):
    """POST mutation-result with succeeded=False sets blocked_writeback."""
    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("image2.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={
            "succeeded": False,
            "operation_type": "rename",
            "error_code": "local_access_lost",
            "error_message": "File system access was revoked by the user.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mutation_state"] == "blocked_writeback"
    assert data["last_mutation_error_code"] == "local_access_lost"


@pytest.mark.asyncio
async def test_local_mutation_result_not_found(client):
    """POST mutation-result returns 404 for a non-existent media item."""
    resp = await client.post(
        f"/api/v1/media/{_new_id()}/mutation-result",
        json={"succeeded": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_local_mutation_result_history_row_written(client, db_session_factory):
    """POST mutation-result writes a SourceMutationHistory row."""
    from src.models import SourceMutationHistory

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("pic.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={
            "succeeded": True,
            "operation_type": "rename",
            "new_filename": "my_picture.jpg",
        },
    )
    assert resp.status_code == 200

    async with db_session_factory() as session:
        result = await session.execute(
            select(SourceMutationHistory).where(
                SourceMutationHistory.media_item_id == item_id
            )
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].succeeded is True
    assert rows[0].new_filename == "my_picture.jpg"
    assert rows[0].operation_type == "rename"


@pytest.mark.asyncio
async def test_local_mutation_result_first_seen_filename_set(client):
    """first_seen_source_filename is captured from original_filename on first call."""
    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("original.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={"succeeded": True, "new_filename": "renamed.jpg"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_seen_source_filename"] == "original.jpg"


@pytest.mark.asyncio
async def test_local_mutation_result_metadata_write_sets_last_writeback_at(
    client, db_session_factory
):
    """operation_type=metadata_write sets last_writeback_at on the MediaItem."""
    from src.models import MediaItem

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("meta.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={
            "succeeded": True,
            "operation_type": "metadata_write",
            "new_filename": "meta.jpg",
        },
    )
    assert resp.status_code == 200

    async with db_session_factory() as session:
        result = await session.execute(
            select(MediaItem).where(MediaItem.id == item_id)
        )
        item = result.scalar_one()

    assert item.last_writeback_at is not None
    assert item.mutation_state == "fully_applied"


@pytest.mark.asyncio
async def test_local_mutation_result_source_fingerprint_stored(client, db_session_factory):
    """source_file_fingerprint is persisted when provided in the request body."""
    from src.models import MediaItem

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("fp.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    fingerprint = hashlib.sha256(b"file-contents").hexdigest()

    await client.post(
        f"/api/v1/media/{item_id}/mutation-result",
        json={
            "succeeded": True,
            "new_filename": "fp_renamed.jpg",
            "source_file_fingerprint": fingerprint,
        },
    )

    async with db_session_factory() as session:
        result = await session.execute(
            select(MediaItem).where(MediaItem.id == item_id)
        )
        item = result.scalar_one()

    assert item.source_file_fingerprint == fingerprint


# ---------------------------------------------------------------------------
# 6. API endpoint tests — POST /media/{id}/retry-writeback (P7-005)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_writeback_pending_item_fully_applied(client, db_session_factory):
    """POST retry-writeback transitions pending_writeback → fully_applied on Drive 200 (mocked)."""
    from src.models import MediaItem

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("drive.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    # Manually set mutation_state to pending_writeback
    async with db_session_factory() as session:
        result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.mutation_state = "pending_writeback"
        item.last_mutation_error_code = "drive_api_error"
        await session.commit()

    # Mock attempt_drive_rename_after_analysis to simulate Drive 200 success
    async def _mock_attempt(db, media_item):
        media_item.mutation_state = "fully_applied"
        media_item.last_mutation_error_code = None
        media_item.last_mutation_error_message = None

    with patch(
        "src.api.routes.media.attempt_drive_rename_after_analysis",
        side_effect=_mock_attempt,
    ):
        resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")

    assert resp.status_code == 200
    data = resp.json()
    assert data["mutation_state"] == "fully_applied"
    assert data["media_item_id"] == item_id
    assert data["last_mutation_error_code"] is None


@pytest.mark.asyncio
async def test_retry_writeback_null_state_returns_422(client):
    """POST retry-writeback returns 422 when mutation_state is NULL (no pending retry needed)."""
    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("notpending.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    # Item has mutation_state = NULL by default after upload
    resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_retry_writeback_blocked_state_returns_422(client, db_session_factory):
    """POST retry-writeback returns 422 when item is in blocked_writeback (user action required)."""
    from src.models import MediaItem

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("blocked.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    async with db_session_factory() as session:
        result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.mutation_state = "blocked_writeback"
        await session.commit()

    resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_retry_writeback_unknown_item_returns_404(client):
    """POST retry-writeback returns 404 for a non-existent media_id."""
    resp = await client.post(f"/api/v1/media/{_new_id()}/retry-writeback")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_retry_writeback_wrong_user_returns_404(client, db_session_factory):
    """POST retry-writeback returns 404 when item belongs to a different user."""
    from src.models import MediaItem

    # Create item directly as DEV_USER_2; client authenticates as DEV_USER_1
    item_id = _new_id()
    async with db_session_factory() as session:
        session.add(MediaItem(
            id=item_id,
            user_id=DEV_USER_2,
            content_hash="wronguser456",
            original_filename="secret.jpg",
            file_size=1000,
            mime_type="image/jpeg",
            storage_path="/tmp/secret.jpg",
            status="completed",
            mutation_state="pending_writeback",
        ))
        await session.commit()

    resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_retry_writeback_stays_pending_on_transient_drive_failure(client, db_session_factory):
    """POST retry-writeback returns 200 but leaves mutation_state=pending_writeback on Drive 5xx."""
    from src.models import MediaItem

    upload_resp = await client.post(
        "/api/v1/upload",
        files={"file": ("transient.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    item_id = upload_resp.json()["id"]

    async with db_session_factory() as session:
        result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
        item.mutation_state = "pending_writeback"
        await session.commit()

    # Mock another Drive 5xx — service sets state back to pending_writeback
    async def _mock_still_pending(db, media_item):
        media_item.mutation_state = "pending_writeback"
        media_item.last_mutation_error_code = "drive_api_error"
        media_item.last_mutation_error_message = "Service unavailable"

    with patch(
        "src.api.routes.media.attempt_drive_rename_after_analysis",
        side_effect=_mock_still_pending,
    ):
        resp = await client.post(f"/api/v1/media/{item_id}/retry-writeback")

    assert resp.status_code == 200
    data = resp.json()
    assert data["mutation_state"] == "pending_writeback"
    assert data["last_mutation_error_code"] == "drive_api_error"

