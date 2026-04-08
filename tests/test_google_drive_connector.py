"""Tests for P7-002: Google Drive Connector (Root-Only).

Coverage:
  - google_drive_oauth: state signing, verification, nonce mismatch, expiry
  - google_drive_tokens: exchange_code, fetch_account_snapshot, token rotation
  - factory: build_connector dispatches correct type
  - google_drive_connector: list_objects applies correct Drive query
  - sync display_name: Drive connector RemoteObject carries file name
  - API: start auth endpoint (503 disabled, 200 enabled)
  - API: callback success redirect with connector upsert
  - API: callback error redirects (access_denied, invalid_state, expired, no_cookie)
  - API: account snapshot persisted on callback
  - API: disconnect clears credentials, preserves account snapshot
  - API: reconnect same account — no SourceObject purge
  - API: reconnect different account — purges SourceObject rows
  - S3 regression: sync still works via factory after refactor
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from tests.conftest import DEV_USER_1, DEV_USER_2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")
_TEST_SECRET_KEY = "test-secret-key-for-drive-tests"

_DRIVE_CONFIG = {
    "enabled": True,
    "client_id": "drive-client-id",
    "client_secret": "drive-client-secret",
    "redirect_uri": "http://localhost:8000/api/v1/connectors/google-drive/callback",
    "frontend_url": "http://localhost:5173",
}

_FAKE_TOKENS = {
    "access_token": "fake-access-token",
    "refresh_token": "fake-refresh-token",
    "scope": "https://www.googleapis.com/auth/drive.readonly",
    "expires_in": 3600,
    "token_type": "Bearer",
}

_FAKE_ACCOUNT = {
    "user": {
        "permissionId": "perm-abc123",
        "emailAddress": "driveuser@example.com",
        "displayName": "Drive User",
    }
}


# ---------------------------------------------------------------------------
# Helper: create source via API
# ---------------------------------------------------------------------------

async def _create_source(client: AsyncClient, name: str = "Drive Source") -> dict:
    resp = await client.post("/api/v1/sources", json={"name": name, "source_type": "manual"})
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Fixture: client with both Drive config and encryption key
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def drive_client(db_engine, db_session_factory, seed_users, tmp_storage, monkeypatch):
    """Test client with Google Drive connector and encryption key enabled."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(cfg_mod.settings.auth, "secret_key", _TEST_SECRET_KEY)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", True)
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", _DRIVE_CONFIG["client_id"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", _DRIVE_CONFIG["client_secret"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", _DRIVE_CONFIG["redirect_uri"])
    monkeypatch.setattr(cfg_mod.settings.google_drive, "frontend_url", _DRIVE_CONFIG["frontend_url"])

    from src.api.app import create_app
    from src.api import dependencies as deps
    from src.api.routes import upload as upload_mod
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService
    from src.analysis.mock_provider import MockVisionProvider
    import src.ingestion.job_manager as job_manager_mod
    import src.analysis.processor as processor_mod
    from src.api.routes import search as search_mod
    import tempfile as _tf
    from src.search.embedder import Embedder
    from src.search.chromadb_store import ChromaDBVectorStore
    from src.search.indexing_service import IndexingService
    from src.search.search_service import SearchService

    test_session_factory = db_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    async def override_get_user():
        return DEV_USER_1

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_id] = override_get_user

    file_store = LocalFileStore(tmp_storage)
    upload_service = UploadService(file_store)
    upload_mod._file_store = file_store
    upload_mod._upload_service = upload_service

    original_provider = upload_mod._vision_provider
    upload_mod._vision_provider = MockVisionProvider()

    _chroma_dir = _tf.mkdtemp()
    embedder = Embedder()
    vector_store = ChromaDBVectorStore(persist_directory=_chroma_dir, collection_name="drive_test")
    indexing_service = IndexingService(embedder, vector_store)
    search_service = SearchService(embedder, vector_store)

    original_indexing = upload_mod._indexing_service
    original_search = search_mod._search_service
    upload_mod._indexing_service = indexing_service
    search_mod._search_service = search_service

    original_jm_session = job_manager_mod.async_session
    original_proc_session = processor_mod.async_session
    job_manager_mod.async_session = db_session_factory
    processor_mod.async_session = db_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    job_manager_mod.async_session = original_jm_session
    processor_mod.async_session = original_proc_session
    upload_mod._vision_provider = original_provider
    upload_mod._indexing_service = original_indexing
    search_mod._search_service = original_search


# ---------------------------------------------------------------------------
# 1. google_drive_oauth — state signing & verification
# ---------------------------------------------------------------------------

def test_sign_and_verify_state_roundtrip():
    """sign_state / verify_state round-trips with correct nonce."""
    from src.auth.google_drive_oauth import sign_state, verify_state

    user_id = "user-abc"
    source_id = "source-xyz"
    nonce = "random-nonce-value"
    secret = "test-secret"

    signed = sign_state(user_id, source_id, nonce, secret)
    uid, sid, mode = verify_state(signed, nonce, secret)
    assert uid == user_id
    assert sid == source_id
    assert mode == "connect"


def test_verify_state_nonce_mismatch_raises():
    """verify_state raises ValueError when cookie nonce does not match embedded nonce."""
    from src.auth.google_drive_oauth import sign_state, verify_state

    signed = sign_state("u", "s", "nonce-a", "secret")
    with pytest.raises(ValueError, match="nonce"):
        verify_state(signed, "nonce-b", "secret")


def test_verify_state_invalid_hmac_raises():
    """verify_state raises ValueError on tampered HMAC."""
    from src.auth.google_drive_oauth import sign_state, verify_state

    signed = sign_state("u", "s", "nonce", "correct-secret")
    with pytest.raises(ValueError):
        verify_state(signed, "nonce", "wrong-secret")


def test_verify_state_expired_raises(monkeypatch):
    """verify_state raises ValueError when state is older than DRIVE_STATE_MAX_AGE."""
    from src.auth import google_drive_oauth
    from src.auth.google_drive_oauth import sign_state, verify_state

    # Sign a state that appears very old
    monkeypatch.setattr(google_drive_oauth, "_", None, raising=False)
    old_time = int(time.time()) - 700  # 700 seconds ago > max 600

    import hashlib, hmac as _hmac
    secret = "test-secret"
    nonce = "n"
    raw_state = f"u|s|{nonce}"
    ts_str = str(old_time)
    msg = f"{raw_state}:{ts_str}".encode()
    sig = _hmac.digest(secret.encode(), msg, hashlib.sha256).hex()
    forged_state = f"{raw_state}.{ts_str}.{sig}"

    with pytest.raises(ValueError, match="expired"):
        verify_state(forged_state, nonce, secret)


def test_build_auth_url_contains_drive_scope():
    """build_auth_url includes Drive writable scope and offline access (P7-004)."""
    from src.auth.google_drive_oauth import build_auth_url, DRIVE_SCOPE_READWRITE

    url = build_auth_url("client-id", "http://redirect", "signed-state")
    assert "accounts.google.com" in url
    # P7-004: default scope is readwrite, not readonly
    assert "drive.readonly" not in url
    assert "auth%2Fdrive" in url  # writable scope path present
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "signed-state" in url


# ---------------------------------------------------------------------------
# 2. google_drive_tokens — exchange_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_success():
    """exchange_code returns access_token, refresh_token, granted_scopes on success."""
    from src.connectors.google_drive_tokens import exchange_code

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _FAKE_TOKENS

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await exchange_code("code", "http://redirect", "client-id", "client-secret")

    assert result["access_token"] == "fake-access-token"
    assert result["refresh_token"] == "fake-refresh-token"
    assert isinstance(result["granted_scopes"], list)


@pytest.mark.asyncio
async def test_exchange_code_missing_refresh_token_raises():
    """exchange_code raises DriveTokenError when no refresh_token is returned."""
    from src.connectors.google_drive_tokens import exchange_code, DriveTokenError

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "at"}  # no refresh_token

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(DriveTokenError, match="refresh_token"):
            await exchange_code("code", "http://redirect", "cid", "csecret")


@pytest.mark.asyncio
async def test_fetch_account_snapshot_success():
    """fetch_account_snapshot returns provider_id, email, display_name."""
    from src.connectors.google_drive_tokens import fetch_account_snapshot

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _FAKE_ACCOUNT

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        snapshot = await fetch_account_snapshot("fake-access-token")

    assert snapshot["provider_id"] == "perm-abc123"
    assert snapshot["email"] == "driveuser@example.com"
    assert snapshot["display_name"] == "Drive User"


# ---------------------------------------------------------------------------
# 3. DriveTokenManager — token refresh and rotation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_manager_refresh_rotates_refresh_token(db_session_factory, seed_users, monkeypatch):
    """DriveTokenManager persists a new refresh_token when Google issues one."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

    from src.connectors.google_drive_tokens import DriveTokenManager
    from src.connectors.secrets import encrypt_credentials
    from src.models import Source, SourceConnector
    from sqlalchemy import select

    async with db_session_factory() as db:
        source = Source(name="Drive Token Test", user_id=DEV_USER_1, source_type="google_drive")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        initial_creds = {
            "refresh_token": "old-refresh-token",
            "refresh_token_issued_at": "2024-01-01T00:00:00+00:00",
            "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        }
        sc = SourceConnector(
            source_id=source.id,
            user_id=DEV_USER_1,
            connector_type="google_drive",
            remote_container_id="root",
            remote_container_label="My Drive",
            credentials_encrypted=encrypt_credentials(initial_creds),
        )
        db.add(sc)
        await db.commit()
        await db.refresh(sc)

        tm = DriveTokenManager(
            connector_row=sc,
            credentials=dict(initial_creds),
            client_id="cid",
            client_secret="csecret",
            redirect_uri="http://redirect",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",  # rotation!
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            token = await tm.get_access_token(db)

        assert token == "new-access-token"

        # Verify rotation was persisted
        await db.refresh(sc)
        from src.connectors.secrets import decrypt_credentials
        updated_creds = decrypt_credentials(sc.credentials_encrypted)
        assert updated_creds["refresh_token"] == "new-refresh-token"


# ---------------------------------------------------------------------------
# 4. factory — build_connector dispatch
# ---------------------------------------------------------------------------

def test_factory_builds_s3_connector(monkeypatch):
    """build_connector returns S3Connector for s3_compatible type."""
    from src.connectors.factory import build_connector
    from src.connectors.s3_connector import S3Connector

    connector_row = MagicMock()
    connector_row.connector_type = "s3_compatible"
    connector_row.remote_container_id = "my-bucket"
    connector_row.region = "us-east-1"
    connector_row.endpoint_url = None
    connector_row.prefix = None

    creds = {"access_key_id": "K", "secret_access_key": "S"}
    result = build_connector(connector_row, creds)
    assert isinstance(result, S3Connector)


def test_factory_builds_drive_connector(monkeypatch):
    """build_connector returns GoogleDriveConnector for google_drive type."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_id", "cid")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "client_secret", "csecret")
    monkeypatch.setattr(cfg_mod.settings.google_drive, "redirect_uri", "http://redir")

    from src.connectors.factory import build_connector
    from src.connectors.google_drive_connector import GoogleDriveConnector

    connector_row = MagicMock()
    connector_row.connector_type = "google_drive"

    creds = {
        "refresh_token": "rt",
        "refresh_token_issued_at": "2024-01-01T00:00:00+00:00",
        "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    }
    result = build_connector(connector_row, creds)
    assert isinstance(result, GoogleDriveConnector)


def test_factory_unknown_type_raises():
    """build_connector raises ValueError for unknown connector type."""
    from src.connectors.factory import build_connector

    connector_row = MagicMock()
    connector_row.connector_type = "unknown_type"

    with pytest.raises(ValueError, match="Unknown connector type"):
        build_connector(connector_row, {})


# ---------------------------------------------------------------------------
# 5. GoogleDriveConnector — list_objects query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_list_objects_sends_correct_query():
    """list_objects sends the correct q filter to exclude native formats and trashed files."""
    from src.connectors.google_drive_connector import GoogleDriveConnector, _LIST_QUERY

    assert "trashed=false" in _LIST_QUERY
    assert "vnd.google-apps.shortcut" in _LIST_QUERY
    assert "vnd.google-apps." in _LIST_QUERY
    assert "image/" in _LIST_QUERY

    mock_tm = MagicMock()
    mock_tm.get_access_token = AsyncMock(return_value="fake-at")

    connector = GoogleDriveConnector(token_manager=mock_tm)

    files_resp = MagicMock()
    files_resp.status_code = 200
    files_resp.json.return_value = {
        "files": [
            {
                "id": "file-id-1",
                "name": "photo.jpg",
                "version": "42",
                "mimeType": "image/jpeg",
                "size": "2048",
                "modifiedTime": "2024-03-15T10:00:00Z",
            }
        ]
        # No nextPageToken → single page
    }
    files_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=files_resp):
        objects = await connector.list_objects(max_keys=10)

    assert len(objects) == 1
    obj = objects[0]
    assert obj.key == "file-id-1"
    assert obj.display_name == "photo.jpg"
    assert obj.version == "42"
    assert obj.size == 2048


# ---------------------------------------------------------------------------
# 6. Sync display_name uses Drive file name
# ---------------------------------------------------------------------------

def test_remote_object_display_name():
    """RemoteObject.display_name is used by sync service for filename."""
    from src.connectors.base import RemoteObject
    from datetime import datetime, timezone

    obj = RemoteObject(
        key="1AbCdEfGhIjK",
        display_name="vacation-photo.jpg",
        version="17",
        last_modified_at=datetime.now(timezone.utc),
        size=512000,
    )
    assert obj.display_name == "vacation-photo.jpg"
    # Key is the Drive file ID — not a path-based name
    assert "/" not in obj.key


# ---------------------------------------------------------------------------
# 7. API — start endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_start_503_when_disabled(client, monkeypatch):
    """POST /connector/google-drive/start returns 503 when connector is disabled."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.google_drive, "enabled", False)
    source = await _create_source(client)
    resp = await client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/start"
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_drive_start_returns_authorization_url(drive_client):
    """POST /connector/google-drive/start returns authorization_url when enabled."""
    source = await _create_source(drive_client)
    resp = await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/start"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_url" in body
    assert "accounts.google.com" in body["authorization_url"]
    # P7-004: new connections request writable scope, not readonly
    assert "drive.readonly" not in body["authorization_url"]
    assert "auth%2Fdrive" in body["authorization_url"]


@pytest.mark.asyncio
async def test_drive_start_sets_state_cookie(drive_client):
    """POST start sets a gdrive_connector_state HTTP-only cookie."""
    from src.auth.google_drive_oauth import DRIVE_STATE_COOKIE

    source = await _create_source(drive_client)
    resp = await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/start"
    )
    assert resp.status_code == 200
    assert DRIVE_STATE_COOKIE in resp.cookies


# ---------------------------------------------------------------------------
# 8. API — callback success flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_callback_success(drive_client, db_session_factory):
    """Callback with valid signed state, code → connected redirect + connector row saved."""
    import src.config as cfg_mod
    from src.auth.google_drive_oauth import sign_state, generate_nonce
    from src.models import SourceConnector
    from sqlalchemy import select

    source = await _create_source(drive_client)
    nonce = generate_nonce()
    signed_state = sign_state(DEV_USER_1, source["id"], nonce, _TEST_SECRET_KEY)

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = _FAKE_TOKENS
    token_resp.raise_for_status = MagicMock()

    about_resp = MagicMock()
    about_resp.status_code = 200
    about_resp.json.return_value = _FAKE_ACCOUNT
    about_resp.raise_for_status = MagicMock()

    with patch("src.api.routes.google_drive_connector.exchange_code", new_callable=AsyncMock, return_value={
        "access_token": "fake-at",
        "refresh_token": "fake-rt",
        "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "expires_in": 3600,
    }), patch("src.api.routes.google_drive_connector.fetch_account_snapshot", new_callable=AsyncMock, return_value={
        "provider_id": "perm-abc123",
        "email": "driveuser@example.com",
        "display_name": "Drive User",
    }):
        resp = await drive_client.get(
            "/api/v1/connectors/google-drive/callback",
            params={"code": "auth-code", "state": signed_state},
            cookies={"gdrive_connector_state": nonce},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "connector_result=connected" in location
    assert source["id"] in location

    # Verify connector row was created
    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceConnector).where(SourceConnector.source_id == source["id"])
        )
        connector = result.scalar_one_or_none()

    assert connector is not None
    assert connector.connector_type == "google_drive"
    assert connector.remote_container_id == "root"
    assert connector.remote_container_label == "My Drive"
    assert connector.authorized_account_email == "driveuser@example.com"
    assert connector.authorized_account_provider_id == "perm-abc123"
    assert connector.authorized_account_display_name == "Drive User"


# ---------------------------------------------------------------------------
# 9. API — callback error redirects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_callback_access_denied_redirect(drive_client):
    """Callback with error=access_denied → error redirect."""
    resp = await drive_client.get(
        "/api/v1/connectors/google-drive/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "connector_result=error" in resp.headers["location"]
    assert "error_code=access_denied" in resp.headers["location"]


@pytest.mark.asyncio
async def test_drive_callback_missing_cookie_redirect(drive_client):
    """Callback with no state cookie → error redirect."""
    resp = await drive_client.get(
        "/api/v1/connectors/google-drive/callback",
        params={"code": "code", "state": "some.state.value"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "connector_result=error" in resp.headers["location"]


@pytest.mark.asyncio
async def test_drive_callback_tampered_state_redirect(drive_client):
    """Callback with tampered state signature → error redirect."""
    resp = await drive_client.get(
        "/api/v1/connectors/google-drive/callback",
        params={"code": "code", "state": "user|source|nonce.12345.invalid_sig"},
        cookies={"gdrive_connector_state": "nonce"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "connector_result=error" in resp.headers["location"]


# ---------------------------------------------------------------------------
# 10. API — granted scopes stored in credentials
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_callback_stores_granted_scopes(drive_client, db_session_factory):
    """Callback persists granted_scopes in encrypted credentials."""
    from src.auth.google_drive_oauth import sign_state, generate_nonce
    from src.models import SourceConnector
    from src.connectors.secrets import decrypt_credentials
    from sqlalchemy import select

    source = await _create_source(drive_client)
    nonce = generate_nonce()
    signed_state = sign_state(DEV_USER_1, source["id"], nonce, _TEST_SECRET_KEY)

    with patch("src.api.routes.google_drive_connector.exchange_code", new_callable=AsyncMock, return_value={
        "access_token": "at",
        "refresh_token": "rt",
        "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "expires_in": 3600,
    }), patch("src.api.routes.google_drive_connector.fetch_account_snapshot", new_callable=AsyncMock, return_value={
        "provider_id": "pid",
        "email": "u@example.com",
        "display_name": "U",
    }):
        resp = await drive_client.get(
            "/api/v1/connectors/google-drive/callback",
            params={"code": "code", "state": signed_state},
            cookies={"gdrive_connector_state": nonce},
            follow_redirects=False,
        )

    assert resp.status_code == 302

    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceConnector).where(SourceConnector.source_id == source["id"])
        )
        connector = result.scalar_one_or_none()

    creds = decrypt_credentials(connector.credentials_encrypted)
    assert "granted_scopes" in creds
    assert "drive.readonly" in creds["granted_scopes"][0]
    assert "refresh_token" in creds


# ---------------------------------------------------------------------------
# 11. API — disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_disconnect_clears_credentials(drive_client, db_session_factory):
    """DELETE /connector/google-drive clears credentials but preserves account snapshot."""
    from src.auth.google_drive_oauth import sign_state, generate_nonce
    from src.models import SourceConnector
    from src.connectors.secrets import decrypt_credentials
    from sqlalchemy import select

    source = await _create_source(drive_client)
    nonce = generate_nonce()
    signed_state = sign_state(DEV_USER_1, source["id"], nonce, _TEST_SECRET_KEY)

    # First connect
    with patch("src.api.routes.google_drive_connector.exchange_code", new_callable=AsyncMock, return_value={
        "access_token": "at", "refresh_token": "rt",
        "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"], "expires_in": 3600,
    }), patch("src.api.routes.google_drive_connector.fetch_account_snapshot", new_callable=AsyncMock, return_value={
        "provider_id": "pid", "email": "u@example.com", "display_name": "U",
    }):
        await drive_client.get(
            "/api/v1/connectors/google-drive/callback",
            params={"code": "code", "state": signed_state},
            cookies={"gdrive_connector_state": nonce},
            follow_redirects=False,
        )

    # Now disconnect
    resp = await drive_client.delete(f"/api/v1/sources/{source['id']}/connector/google-drive")
    assert resp.status_code == 204

    # Verify: credentials cleared, account snapshot preserved
    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceConnector).where(SourceConnector.source_id == source["id"])
        )
        connector = result.scalar_one_or_none()

    assert connector is not None
    creds = decrypt_credentials(connector.credentials_encrypted)
    assert creds == {}  # empty dict — credentials cleared
    assert connector.authorized_account_email == "u@example.com"  # preserved
    assert connector.authorized_account_display_name == "U"  # preserved


# ---------------------------------------------------------------------------
# 12. API — reconnect same account: no SourceObject purge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_reconnect_same_account_preserves_source_objects(drive_client, db_session_factory):
    """Reconnect with same provider_id preserves existing SourceObject rows."""
    from src.auth.google_drive_oauth import sign_state, generate_nonce
    from src.models import SourceConnector, SourceObject
    from sqlalchemy import select

    source = await _create_source(drive_client)

    async def _connect(provider_id: str):
        nonce = generate_nonce()
        signed_state = sign_state(DEV_USER_1, source["id"], nonce, _TEST_SECRET_KEY)
        with patch("src.api.routes.google_drive_connector.exchange_code", new_callable=AsyncMock, return_value={
            "access_token": "at", "refresh_token": "rt",
            "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"], "expires_in": 3600,
        }), patch("src.api.routes.google_drive_connector.fetch_account_snapshot", new_callable=AsyncMock, return_value={
            "provider_id": provider_id, "email": "u@example.com", "display_name": "U",
        }):
            resp = await drive_client.get(
                "/api/v1/connectors/google-drive/callback",
                params={"code": "code", "state": signed_state},
                cookies={"gdrive_connector_state": nonce},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "connector_result=connected" in resp.headers["location"]

    await _connect("same-pid")

    # Add a fake SourceObject
    async with db_session_factory() as db:
        so = SourceObject(
            source_id=source["id"],
            user_id=DEV_USER_1,
            external_object_key="file-id-abc",
            state="imported",
        )
        db.add(so)
        await db.commit()

    # Reconnect with the same account
    await _connect("same-pid")

    # SourceObject should still be present
    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceObject).where(SourceObject.source_id == source["id"])
        )
        objects = result.scalars().all()

    assert len(objects) == 1


# ---------------------------------------------------------------------------
# 13. API — reconnect different account: purge SourceObject rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_reconnect_different_account_purges_source_objects(drive_client, db_session_factory):
    """Reconnect with different provider_id purges prior SourceObject rows."""
    from src.auth.google_drive_oauth import sign_state, generate_nonce
    from src.models import SourceConnector, SourceObject
    from sqlalchemy import select

    source = await _create_source(drive_client)

    async def _connect(provider_id: str):
        nonce = generate_nonce()
        signed_state = sign_state(DEV_USER_1, source["id"], nonce, _TEST_SECRET_KEY)
        with patch("src.api.routes.google_drive_connector.exchange_code", new_callable=AsyncMock, return_value={
            "access_token": "at", "refresh_token": "rt",
            "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"], "expires_in": 3600,
        }), patch("src.api.routes.google_drive_connector.fetch_account_snapshot", new_callable=AsyncMock, return_value={
            "provider_id": provider_id, "email": "user@example.com", "display_name": "User",
        }):
            resp = await drive_client.get(
                "/api/v1/connectors/google-drive/callback",
                params={"code": "code", "state": signed_state},
                cookies={"gdrive_connector_state": nonce},
                follow_redirects=False,
            )
        assert resp.status_code == 302

    # Connect with account A
    await _connect("account-a-pid")

    # Add a fake SourceObject for account A's files
    async with db_session_factory() as db:
        so = SourceObject(
            source_id=source["id"],
            user_id=DEV_USER_1,
            external_object_key="old-file-id",
            state="imported",
        )
        db.add(so)
        await db.commit()

    # Reconnect with account B
    await _connect("account-b-pid")

    # SourceObject should be purged
    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceObject).where(SourceObject.source_id == source["id"])
        )
        objects = result.scalars().all()

    assert len(objects) == 0


# ---------------------------------------------------------------------------
# 14. Folder-scoped recursive listing (P7-007)
# ---------------------------------------------------------------------------

def _make_file_item(file_id: str, name: str) -> dict:
    return {
        "id": file_id,
        "name": name,
        "version": "1",
        "mimeType": "image/jpeg",
        "size": "1024",
        "modifiedTime": "2024-06-01T10:00:00Z",
    }


def _make_drive_resp(files: list[dict], next_page_token: str | None = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    payload: dict = {"files": files}
    if next_page_token:
        payload["nextPageToken"] = next_page_token
    mock.json.return_value = payload
    mock.raise_for_status = MagicMock()
    return mock


@pytest.mark.asyncio
async def test_list_objects_no_folder_uses_flat_query():
    """list_objects with no folder scoping uses the base flat query (unchanged from P7-002)."""
    from src.connectors.google_drive_connector import GoogleDriveConnector, _BASE_QUERY

    mock_tm = MagicMock()
    mock_tm.get_access_token = AsyncMock(return_value="at")
    connector = GoogleDriveConnector(token_manager=mock_tm)  # no folder_id

    img_resp = _make_drive_resp([_make_file_item("img-root", "photo.jpg")])

    captured_params: list[dict] = []

    async def fake_get(url, params=None, headers=None, **kwargs):
        captured_params.append(dict(params or {}))
        return img_resp

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=fake_get):
        objects = await connector.list_objects(max_keys=10)

    assert len(objects) == 1
    assert objects[0].key == "img-root"
    # No 'in parents' filter for the root case
    assert "in parents" not in captured_params[0]["q"]
    assert _BASE_QUERY in captured_params[0]["q"]


@pytest.mark.asyncio
async def test_list_objects_with_folder_recurses_into_subfolders():
    """list_objects with folder_id recurses into direct sub-folders (P7-007).

    Drive layout:
      photos-folder/
        root-img.jpg          ← returned in first images call
        events/               ← sub-folder returned by subfolder query
          event-img.jpg       ← returned in recursive images call
          (no sub-sub-folders)
    """
    from src.connectors.google_drive_connector import GoogleDriveConnector

    mock_tm = MagicMock()
    mock_tm.get_access_token = AsyncMock(return_value="at")
    connector = GoogleDriveConnector(token_manager=mock_tm, folder_id="photos-folder")

    # Call 1: images directly in "photos-folder" → 1 image
    images_in_root = _make_drive_resp([_make_file_item("img-root", "root-img.jpg")])
    # Call 2: sub-folders of "photos-folder" → 1 sub-folder "events"
    subfolders_root = MagicMock()
    subfolders_root.status_code = 200
    subfolders_root.json.return_value = {"files": [{"id": "events", "name": "Events"}]}
    subfolders_root.raise_for_status = MagicMock()
    # Call 3: images directly in "events" → 1 image
    images_in_events = _make_drive_resp([_make_file_item("img-event", "event-img.jpg")])
    # Call 4: sub-folders of "events" → none
    subfolders_events = MagicMock()
    subfolders_events.status_code = 200
    subfolders_events.json.return_value = {"files": []}
    subfolders_events.raise_for_status = MagicMock()

    call_responses = [images_in_root, subfolders_root, images_in_events, subfolders_events]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=call_responses):
        objects = await connector.list_objects(max_keys=100)

    assert len(objects) == 2
    keys = {o.key for o in objects}
    assert "img-root" in keys
    assert "img-event" in keys


@pytest.mark.asyncio
async def test_list_objects_recursive_respects_max_keys():
    """list_objects stops collecting after max_keys is reached during recursion."""
    from src.connectors.google_drive_connector import GoogleDriveConnector

    mock_tm = MagicMock()
    mock_tm.get_access_token = AsyncMock(return_value="at")
    connector = GoogleDriveConnector(token_manager=mock_tm, folder_id="parent-folder")

    # Images directly in parent — 3 images, but max_keys=2
    images_in_parent = _make_drive_resp([
        _make_file_item("img-1", "a.jpg"),
        _make_file_item("img-2", "b.jpg"),
        _make_file_item("img-3", "c.jpg"),
    ])
    # Sub-folder query (should not be reached since max_keys hit)
    subfolders_parent = MagicMock()
    subfolders_parent.status_code = 200
    subfolders_parent.json.return_value = {"files": [{"id": "sub", "name": "Sub"}]}
    subfolders_parent.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock,
               side_effect=[images_in_parent, subfolders_parent]):
        objects = await connector.list_objects(max_keys=2)

    assert len(objects) == 2


@pytest.mark.asyncio
async def test_list_objects_depth_limit_stops_infinite_recursion():
    """_collect_recursive honours _MAX_FOLDER_DEPTH and stops at the limit."""
    from src.connectors.google_drive_connector import GoogleDriveConnector, _MAX_FOLDER_DEPTH

    mock_tm = MagicMock()
    mock_tm.get_access_token = AsyncMock(return_value="at")
    connector = GoogleDriveConnector(token_manager=mock_tm, folder_id="root-f")

    no_images = _make_drive_resp([])
    one_subfolder = MagicMock()
    one_subfolder.status_code = 200
    one_subfolder.json.return_value = {"files": [{"id": "child-f", "name": "Child"}]}
    one_subfolder.raise_for_status = MagicMock()

    # Alternate no_images / one_subfolder for _MAX_FOLDER_DEPTH+2 levels ×2
    side_effects = []
    for _ in range(_MAX_FOLDER_DEPTH + 2):
        side_effects.append(no_images)  # image query
        side_effects.append(one_subfolder)  # subfolder query

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=side_effects):
        objects = await connector.list_objects(max_keys=100)

    # Should complete without stack overflow or infinite recursion
    assert objects == []


# ---------------------------------------------------------------------------
# 15. google_drive_configure endpoint (P7-007)
# ---------------------------------------------------------------------------

async def _connect_drive_source(
    client: AsyncClient,
    db_session_factory,
    source_id: str,
    monkeypatch,
) -> None:
    """Helper: run the OAuth callback flow to create a Drive connector row."""
    import src.config as cfg_mod
    from src.auth.google_drive_oauth import sign_state, generate_nonce

    nonce = generate_nonce()
    signed_state = sign_state(DEV_USER_1, source_id, nonce, _TEST_SECRET_KEY)

    with patch(
        "src.api.routes.google_drive_connector.exchange_code",
        new_callable=AsyncMock,
        return_value={
            "access_token": "at",
            "refresh_token": "rt",
            "granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            "expires_in": 3600,
        },
    ), patch(
        "src.api.routes.google_drive_connector.fetch_account_snapshot",
        new_callable=AsyncMock,
        return_value={
            "provider_id": "pid",
            "email": "user@example.com",
            "display_name": "User",
        },
    ):
        resp = await client.get(
            "/api/v1/connectors/google-drive/callback",
            params={"code": "auth-code", "state": signed_state},
            cookies={"gdrive_connector_state": nonce},
            follow_redirects=False,
        )
    assert resp.status_code == 302


@pytest.mark.asyncio
async def test_drive_configure_sets_folder(drive_client, db_session_factory, monkeypatch):
    """POST configure sets target_folder_id and target_folder_label on the connector."""
    from src.models import SourceConnector
    from sqlalchemy import select

    source = await _create_source(drive_client, "FolderScope Test")
    await _connect_drive_source(drive_client, db_session_factory, source["id"], monkeypatch)

    resp = await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/configure",
        json={
            "target_folder_id": "folder-abc",
            "target_folder_label": "My Photos",
            "target_collection_id": None,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_folder_id"] == "folder-abc"
    assert body["target_folder_label"] == "My Photos"
    assert body["target_collection_id"] is None

    # Verify persisted in DB
    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceConnector).where(SourceConnector.source_id == source["id"])
        )
        connector = result.scalar_one_or_none()

    assert connector is not None
    assert connector.target_folder_id == "folder-abc"
    assert connector.target_folder_label == "My Photos"


@pytest.mark.asyncio
async def test_drive_configure_resets_to_root(drive_client, db_session_factory, monkeypatch):
    """POST configure with target_folder_id=null resets to My Drive root."""
    from src.models import SourceConnector
    from sqlalchemy import select

    source = await _create_source(drive_client, "FolderScope Reset")
    await _connect_drive_source(drive_client, db_session_factory, source["id"], monkeypatch)

    # First set a folder
    await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/configure",
        json={"target_folder_id": "folder-xyz", "target_folder_label": "Old Folder"},
    )

    # Now reset to root
    resp = await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/configure",
        json={"target_folder_id": None, "target_folder_label": None},
    )
    assert resp.status_code == 200
    assert resp.json()["target_folder_id"] is None
    assert resp.json()["target_folder_label"] is None

    async with db_session_factory() as db:
        result = await db.execute(
            select(SourceConnector).where(SourceConnector.source_id == source["id"])
        )
        connector = result.scalar_one_or_none()
    assert connector.target_folder_id is None


@pytest.mark.asyncio
async def test_drive_configure_no_connector_404(drive_client):
    """POST configure returns 404 when no Drive connector exists."""
    source = await _create_source(drive_client, "NoConnector Configure")
    resp = await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/configure",
        json={"target_folder_id": "folder-abc"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_drive_configure_invalid_collection_404(drive_client, db_session_factory, monkeypatch):
    """POST configure with non-existent collection_id returns 404."""
    source = await _create_source(drive_client, "InvalidCollection Configure")
    await _connect_drive_source(drive_client, db_session_factory, source["id"], monkeypatch)

    resp = await drive_client.post(
        f"/api/v1/sources/{source['id']}/connector/google-drive/configure",
        json={
            "target_folder_id": None,
            "target_collection_id": "non-existent-collection-id",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_drive_configure_wrong_user_404(
    drive_client, db_session_factory, monkeypatch,
    db_engine, tmp_storage,
):
    """POST configure by a different user returns 404 (user scoping)."""
    import src.config as cfg_mod
    from src.api.app import create_app
    from src.api import dependencies as deps
    from src.api.routes import upload as upload_mod
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService
    from src.analysis.mock_provider import MockVisionProvider
    import src.ingestion.job_manager as jm_mod
    import src.analysis.processor as proc_mod
    from src.api.routes import search as search_mod
    import tempfile as _tf2
    from src.search.embedder import Embedder
    from src.search.chromadb_store import ChromaDBVectorStore
    from src.search.indexing_service import IndexingService
    from src.search.search_service import SearchService

    source = await _create_source(drive_client, "UserScope Configure")
    await _connect_drive_source(drive_client, db_session_factory, source["id"], monkeypatch)

    # Build a second client authenticated as DEV_USER_2 sharing the same DB
    test_sf = db_session_factory

    async def override_get_db2():
        async with test_sf() as session:
            yield session

    async def override_user2():
        return DEV_USER_2

    app2 = create_app()
    app2.dependency_overrides[deps.get_db] = override_get_db2
    app2.dependency_overrides[deps.get_current_user_id] = override_user2

    fs2 = LocalFileStore(tmp_storage)
    upload_mod._file_store = fs2
    upload_mod._upload_service = UploadService(fs2)
    original_prov = upload_mod._vision_provider
    upload_mod._vision_provider = MockVisionProvider()

    _cd = _tf2.mkdtemp()
    _vs2 = ChromaDBVectorStore(persist_directory=_cd, collection_name="cfg_user2")
    _is2 = IndexingService(Embedder(), _vs2)
    _ss2 = SearchService(Embedder(), _vs2)
    original_indexing = upload_mod._indexing_service
    original_search = search_mod._search_service
    upload_mod._indexing_service = _is2
    search_mod._search_service = _ss2
    orig_jm = jm_mod.async_session
    orig_proc = proc_mod.async_session
    jm_mod.async_session = test_sf
    proc_mod.async_session = test_sf

    from httpx import ASGITransport, AsyncClient as _AC
    transport2 = ASGITransport(app=app2)
    async with _AC(transport=transport2, base_url="http://test") as client2:
        resp = await client2.post(
            f"/api/v1/sources/{source['id']}/connector/google-drive/configure",
            json={"target_folder_id": "hacker-folder"},
        )

    jm_mod.async_session = orig_jm
    proc_mod.async_session = orig_proc
    upload_mod._vision_provider = original_prov
    upload_mod._indexing_service = original_indexing
    search_mod._search_service = original_search

    assert resp.status_code == 404
