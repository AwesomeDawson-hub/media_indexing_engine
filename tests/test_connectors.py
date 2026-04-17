"""Integration and unit tests for P5-003: Connector Sync Foundation.

Coverage:
  - secrets.py: encrypt/decrypt round-trip, missing key behaviour
  - API: configure connector, get connector, trigger sync, list sync runs
  - User scoping: user 2 cannot access user 1's connector or sync history
  - Sync service: idempotency skip, import new objects, duplicate handling,
                  per-object failure tolerance, archived source rejection,
                  overlap prevention, no-connector rejection
"""

from __future__ import annotations

import io
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import DEV_USER_1, DEV_USER_2, JPEG_BYTES

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")

_S3_CONFIG = {
    "bucket_name": "my-bucket",
    "access_key_id": "AKIATEST",
    "secret_access_key": "secret",
    "region": "us-east-1",
    "endpoint_url": "",
    "prefix": "images/",
}


async def _create_source(client: AsyncClient, name: str = "S3 Source") -> dict:
    resp = await client.post("/api/v1/sources", json={"name": name, "source_type": "manual"})
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def encryption_enabled(monkeypatch):
    """Patch settings so CONNECTOR_CREDENTIALS_KEY is set for these tests."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    yield _TEST_FERNET_KEY


@pytest_asyncio.fixture
async def client_with_key(
    db_engine, db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """Like conftest.client but also patches in a valid encryption key."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

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
    vector_store = ChromaDBVectorStore(persist_directory=_chroma_dir, collection_name="conn_test")
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


@pytest_asyncio.fixture
async def client_user2_with_key(
    db_engine, db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """Like client_with_key but authenticated as user 2."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

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
        return DEV_USER_2

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
    vector_store = ChromaDBVectorStore(persist_directory=_chroma_dir, collection_name="conn_test2")
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
# 1. secrets.py — encryption key enforcement
# ---------------------------------------------------------------------------

def test_missing_encryption_key_fails_closed(monkeypatch):
    """require_encryption_key() raises when CONNECTOR_CREDENTIALS_KEY is empty."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", "")
    from src.connectors.secrets import require_encryption_key, MissingEncryptionKeyError
    with pytest.raises(MissingEncryptionKeyError):
        require_encryption_key()


def test_encrypt_decrypt_roundtrip(monkeypatch):
    """encrypt_credentials → decrypt_credentials returns the original payload."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    from src.connectors.secrets import encrypt_credentials, decrypt_credentials

    payload = {"access_key_id": "AKIA123", "secret_access_key": "s3cr3t"}
    ciphertext = encrypt_credentials(payload)
    assert isinstance(ciphertext, str)
    # Secret must not appear in ciphertext in plaintext
    assert "s3cr3t" not in ciphertext
    recovered = decrypt_credentials(ciphertext)
    assert recovered == payload


# ---------------------------------------------------------------------------
# 2. API — configure S3 connector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_configure_connector_no_key_returns_503(client, monkeypatch):
    """POST /connector/s3 fails with 503 when encryption key is not set."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", "")
    source = await _create_source(client)
    resp = await client.post(f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_configure_connector_stores_encrypted_credentials(
    client_with_key, db_session_factory
):
    """Saved connector row never stores secret_access_key in plaintext."""
    from sqlalchemy import select as _select
    from src.models import SourceConnector as _SC

    source = await _create_source(client_with_key)
    resp = await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    assert resp.status_code == 200

    async with db_session_factory() as db:
        result = await db.execute(
            _select(_SC).where(_SC.source_id == source["id"])
        )
        row = result.scalar_one_or_none()

    assert row is not None
    assert row.credentials_encrypted is not None
    # Secret must NOT appear in plaintext in the DB field
    assert _S3_CONFIG["secret_access_key"] not in row.credentials_encrypted


@pytest.mark.asyncio
async def test_configure_connector_response_excludes_secrets(client_with_key):
    """API response never contains access_key_id, secret_access_key, or credentials_encrypted."""
    source = await _create_source(client_with_key)
    resp = await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    assert resp.status_code == 200
    body = resp.json()
    response_text = str(body)
    assert "secret_access_key" not in response_text
    assert "AKIATEST" not in response_text
    assert "credentials_encrypted" not in response_text
    # Should include non-secret fields
    assert body["remote_container_id"] == "my-bucket"
    assert body["connector_type"] == "s3_compatible"


# ---------------------------------------------------------------------------
# 3. API — user scoping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_configure_connector_user_scoped(
    client_with_key, client_user2_with_key, db_session_factory
):
    """User 2 cannot read or modify user 1's connector config."""
    # User 1 creates a source and configures a connector
    source = await _create_source(client_with_key, "User1 Source")
    resp = await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    assert resp.status_code == 200

    # User 2 tries to GET user 1's connector — must get 404
    resp2 = await client_user2_with_key.get(f"/api/v1/sources/{source['id']}/connector")
    assert resp2.status_code == 404

    # User 2 tries to configure user 1's connector — must get 404
    resp3 = await client_user2_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    assert resp3.status_code == 404


# ---------------------------------------------------------------------------
# 4. API — GET connector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_connector_returns_configured_data(client_with_key):
    """GET /connector returns non-secret fields after POST /connector/s3."""
    source = await _create_source(client_with_key)
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.get(f"/api/v1/sources/{source['id']}/connector")
    assert resp.status_code == 200
    body = resp.json()
    assert body["remote_container_id"] == "my-bucket"
    assert body["connector_type"] == "s3_compatible"
    assert "secret_access_key" not in str(body)


@pytest.mark.asyncio
async def test_get_connector_404_when_no_connector(client_with_key):
    """GET /connector returns 404 when no connector has been configured."""
    source = await _create_source(client_with_key)
    resp = await client_with_key.get(f"/api/v1/sources/{source['id']}/connector")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. API — trigger sync: no connector or archived source
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_sync_no_connector_returns_422(client_with_key):
    """POST /sync returns 422 when no connector is configured."""
    source = await _create_source(client_with_key)
    resp = await client_with_key.post(f"/api/v1/sources/{source['id']}/sync")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_trigger_sync_no_encryption_key_returns_503(client, monkeypatch):
    """POST /sync returns 503 when encryption key is not configured."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", "")
    source = await _create_source(client)
    resp = await client.post(f"/api/v1/sources/{source['id']}/sync")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 6. API — trigger sync overlap rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_sync_overlap_rejected(client_with_key, db_session_factory):
    """A second sync trigger is rejected with 409 when one is already in progress."""
    from src.models import Source as _Source, SourceConnector as _SC, SyncRun as _SR
    from sqlalchemy import select as _select
    from datetime import datetime, timezone

    source = await _create_source(client_with_key, "Overlap Test")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )

    # Inject a running SyncRun directly to simulate overlap
    async with db_session_factory() as db:
        result = await db.execute(_select(_SC).where(_SC.source_id == source["id"]))
        sc = result.scalar_one()
        running = _SR(
            source_id=source["id"],
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            trigger_type="manual",
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(running)
        await db.commit()

    resp = await client_with_key.post(f"/api/v1/sources/{source['id']}/sync")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 7. Sync runs list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_run_history_visible(client_with_key, db_session_factory):
    """GET /sync-runs returns runs for the authenticated user."""
    from src.models import SyncRun as _SR, SourceConnector as _SC
    from sqlalchemy import select as _select
    from datetime import datetime, timezone

    source = await _create_source(client_with_key, "History Test")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )

    # Insert a completed run directly
    async with db_session_factory() as db:
        run = _SR(
            source_id=source["id"],
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            trigger_type="manual",
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            discovered_count=5,
            imported_count=3,
            duplicate_count=1,
            skipped_count=1,
            failed_count=0,
        )
        db.add(run)
        await db.commit()

    resp = await client_with_key.get(f"/api/v1/sources/{source['id']}/sync-runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    run_data = body["runs"][0]
    assert run_data["status"] == "completed"
    assert run_data["discovered_count"] == 5
    assert run_data["imported_count"] == 3


@pytest.mark.asyncio
async def test_sync_run_history_user_scoped(
    client_with_key, client_user2_with_key, db_session_factory
):
    """User 2 cannot see user 1's sync run history."""
    from src.models import SyncRun as _SR
    from datetime import datetime, timezone

    source = await _create_source(client_with_key, "History Scope")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )

    # Insert a run as user 1
    async with db_session_factory() as db:
        run = _SR(
            source_id=source["id"],
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            trigger_type="manual",
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.commit()

    # User 2 queries this source — source 404 means no run leakage
    resp = await client_user2_with_key.get(f"/api/v1/sources/{source['id']}/sync-runs")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. Sync service unit tests (mocked S3)
# ---------------------------------------------------------------------------

def _make_remote_obj(key: str = "images/photo.jpg", version: str = "etag-v1", size: int = 1024):
    from src.connectors.base import RemoteObject
    from datetime import datetime, timezone
    import os
    return RemoteObject(
        key=key,
        display_name=os.path.basename(key) or key,
        version=version,
        last_modified_at=datetime.now(timezone.utc),
        size=size,
    )


@pytest.mark.asyncio
async def test_trigger_sync_idempotent_skip(db_session_factory, seed_users, tmp_storage, monkeypatch):
    """An unchanged remote object (same key + version) is skipped, not re-imported."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

    from src.connectors.sync_service import trigger_sync
    from src.connectors.secrets import encrypt_credentials
    from src.models import Source as _Source, SourceConnector as _SC, SourceObject as _SO
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService

    async with db_session_factory() as db:
        # Create source + connector
        source = _Source(name="Idempotent", user_id=DEV_USER_1, source_type="s3_compatible")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        sc = _SC(
            source_id=source.id,
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            remote_container_id="my-bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
        )
        db.add(sc)
        await db.commit()
        await db.refresh(sc)

        # Pre-populate a SourceObject with this key+version already imported
        from datetime import datetime, timezone
        existing_so = _SO(
            source_id=source.id,
            user_id=DEV_USER_1,
            external_object_key="images/photo.jpg",
            external_version="etag-v1",
            external_last_modified_at=datetime.now(timezone.utc),
            external_size=1024,
            state="imported",
        )
        db.add(existing_so)
        await db.commit()

        remote_obj = _make_remote_obj()

        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)

        with patch("src.connectors.s3_connector.S3Connector.list_objects", new_callable=AsyncMock) as mock_list, \
             patch("src.connectors.s3_connector.S3Connector.download_object", new_callable=AsyncMock) as mock_dl:
            mock_list.return_value = [remote_obj]
            mock_dl.return_value = JPEG_BYTES

            result = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
            )

        # Object was skipped (same key+version), not re-downloaded
        assert result.skipped_count == 1
        assert result.imported_count == 0
        mock_dl.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_sync_imports_new_object(db_session_factory, seed_users, tmp_storage, monkeypatch):
    """A new remote object flows through process_upload and is counted as imported."""
    import src.config as cfg_mod
    import src.connectors.sync_service as sync_service_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    # This test covers import/download behavior only; disable analysis so the
    # P12-010 task wrapper does not count vision-provider errors as failures.
    monkeypatch.setattr(sync_service_mod, "_get_vision_provider", lambda: None)

    from src.connectors.sync_service import trigger_sync
    from src.connectors.secrets import encrypt_credentials
    from src.models import Source as _Source, SourceConnector as _SC
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService

    async with db_session_factory() as db:
        source = _Source(name="New Import", user_id=DEV_USER_1, source_type="s3_compatible")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        sc = _SC(
            source_id=source.id,
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            remote_container_id="my-bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
        )
        db.add(sc)
        await db.commit()

        remote_obj = _make_remote_obj(key="images/new.jpg", version="etag-new")

        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)

        with patch("src.connectors.s3_connector.S3Connector.list_objects", new_callable=AsyncMock) as mock_list, \
             patch("src.connectors.s3_connector.S3Connector.download_object", new_callable=AsyncMock) as mock_dl:
            mock_list.return_value = [remote_obj]
            mock_dl.return_value = JPEG_BYTES

            result = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
            )

        assert result.imported_count == 1
        assert result.failed_count == 0
        assert result.status in ("completed", "completed_with_errors")


@pytest.mark.asyncio
async def test_trigger_sync_duplicate_object(db_session_factory, seed_users, tmp_storage, monkeypatch):
    """A content-duplicate object counts as duplicate, not imported."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

    from src.connectors.sync_service import trigger_sync
    from src.connectors.secrets import encrypt_credentials
    from src.models import Source as _Source, SourceConnector as _SC
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService

    async with db_session_factory() as db:
        source = _Source(name="Duplicate Test", user_id=DEV_USER_1, source_type="s3_compatible")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        sc = _SC(
            source_id=source.id,
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            remote_container_id="my-bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
        )
        db.add(sc)
        await db.commit()

        # Upload the same JPEG manually first (so the hash is in DB)
        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)
        first_result = await upload_service.process_upload(
            db=db,
            user_id=DEV_USER_1,
            filename="original.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
        )
        assert first_result.success

        # Now sync the same bytes under a different S3 key
        remote_obj = _make_remote_obj(key="images/copy.jpg", version="etag-copy")

        with patch("src.connectors.s3_connector.S3Connector.list_objects", new_callable=AsyncMock) as mock_list, \
             patch("src.connectors.s3_connector.S3Connector.download_object", new_callable=AsyncMock) as mock_dl:
            mock_list.return_value = [remote_obj]
            mock_dl.return_value = JPEG_BYTES  # same bytes → duplicate

            result = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
            )

        assert result.duplicate_count == 1
        assert result.imported_count == 0


@pytest.mark.asyncio
async def test_trigger_sync_failed_object_does_not_abort_run(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """A per-object download failure increments failed_count but the run continues."""
    import src.config as cfg_mod
    import src.connectors.sync_service as sync_service_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    # This test covers download-failure tolerance only; disable analysis so the
    # P12-010 task wrapper does not add extra failures to the expected count.
    monkeypatch.setattr(sync_service_mod, "_get_vision_provider", lambda: None)

    from src.connectors.sync_service import trigger_sync
    from src.connectors.secrets import encrypt_credentials
    from src.models import Source as _Source, SourceConnector as _SC
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService

    async with db_session_factory() as db:
        source = _Source(name="Failure Test", user_id=DEV_USER_1, source_type="s3_compatible")
        db.add(source)
        await db.commit()
        await db.refresh(source)

        sc = _SC(
            source_id=source.id,
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            remote_container_id="my-bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
        )
        db.add(sc)
        await db.commit()

        remote_bad = _make_remote_obj(key="images/bad.jpg", version="v1")
        remote_good = _make_remote_obj(key="images/good.jpg", version="v2")

        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)

        def _fake_download(key: str):
            if "bad" in key:
                raise RuntimeError("Simulated download failure")
            return JPEG_BYTES

        with patch("src.connectors.s3_connector.S3Connector.list_objects", new_callable=AsyncMock) as mock_list, \
             patch("src.connectors.s3_connector.S3Connector.download_object", new_callable=AsyncMock) as mock_dl:
            mock_list.return_value = [remote_bad, remote_good]
            mock_dl.side_effect = _fake_download

            result = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
            )

        assert result.failed_count == 1
        assert result.imported_count == 1
        # Run should still complete (not fail entirely)
        assert result.status in ("completed", "completed_with_errors")


@pytest.mark.asyncio
async def test_archived_source_sync_rejected(db_session_factory, seed_users, tmp_storage, monkeypatch):
    """trigger_sync raises ValueError when the source is archived."""
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

    from src.connectors.sync_service import trigger_sync
    from src.connectors.secrets import encrypt_credentials
    from src.models import Source as _Source, SourceConnector as _SC
    from src.storage.file_store import LocalFileStore
    from src.ingestion.upload_service import UploadService
    from datetime import datetime, timezone

    async with db_session_factory() as db:
        source = _Source(name="Archived", user_id=DEV_USER_1, source_type="s3_compatible",
                         archived_at=datetime.now(timezone.utc))
        db.add(source)
        await db.commit()
        await db.refresh(source)

        sc = _SC(
            source_id=source.id,
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            remote_container_id="bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
        )
        db.add(sc)
        await db.commit()

        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)

        with pytest.raises(ValueError, match="archived"):
            await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
            )


# ---------------------------------------------------------------------------
# P7-006: PATCH /sources/{id}/connector/auto-sync
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_auto_sync_enable(client_with_key):
    """PATCH auto-sync returns 200 and sets auto_sync_enabled=True."""
    source = await _create_source(client_with_key, "AutoSync Enable Test")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": True, "interval_minutes": 60},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_sync_enabled"] is True
    assert body["auto_sync_interval_minutes"] == 60


@pytest.mark.asyncio
async def test_update_auto_sync_disable(client_with_key):
    """PATCH auto-sync can disable auto-sync after it was enabled."""
    source = await _create_source(client_with_key, "AutoSync Disable Test")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    # Enable first
    await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": True, "interval_minutes": 30},
    )
    # Then disable
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": False, "interval_minutes": 30},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_sync_enabled"] is False


@pytest.mark.asyncio
async def test_update_auto_sync_invalid_interval(client_with_key):
    """PATCH auto-sync with interval < 15 returns 422."""
    source = await _create_source(client_with_key, "AutoSync Bad Interval")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": True, "interval_minutes": 5},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_auto_sync_max_interval(client_with_key):
    """PATCH auto-sync with interval_minutes=1440 (24 h) returns 200."""
    source = await _create_source(client_with_key, "AutoSync Max Interval")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": True, "interval_minutes": 1440},
    )
    assert resp.status_code == 200
    assert resp.json()["auto_sync_interval_minutes"] == 1440


@pytest.mark.asyncio
async def test_update_auto_sync_no_connector_404(client_with_key):
    """PATCH auto-sync returns 404 when no connector has been configured."""
    source = await _create_source(client_with_key, "AutoSync No Connector")
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": True, "interval_minutes": 60},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_auto_sync_wrong_source_404(client_with_key, client_user2_with_key):
    """PATCH auto-sync on another user's source returns 404."""
    # User 1 creates + configures a source
    source = await _create_source(client_with_key, "AutoSync Scoped Source")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    # User 2 tries to set auto-sync on it
    resp = await client_user2_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/auto-sync",
        json={"enabled": True, "interval_minutes": 60},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 10. Cross-source sync-run dashboard (P7-008)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_all_sync_runs_includes_source_name(client_with_key, db_session_factory):
    """GET /api/v1/sync-runs returns sync runs with source_name populated."""
    from src.models import SyncRun as _SR
    from datetime import datetime, timezone

    source = await _create_source(client_with_key, "Dashboard Source")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )

    # Insert a completed run directly (no real network call needed)
    async with db_session_factory() as db:
        run = _SR(
            source_id=source["id"],
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            trigger_type="manual",
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            discovered_count=2,
            imported_count=2,
        )
        db.add(run)
        await db.commit()

    resp = await client_with_key.get("/api/v1/sync-runs")
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body
    assert "total" in body
    assert body["total"] >= 1
    run = body["runs"][0]
    assert run["source_name"] == "Dashboard Source"
    assert "status" in run
    assert "created_at" in run


@pytest.mark.asyncio
async def test_list_all_sync_runs_empty_for_new_user(client):
    """GET /api/v1/sync-runs returns empty list when user has no runs."""
    resp = await client.get("/api/v1/sync-runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runs"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_all_sync_runs_user_scoped(client_with_key, client_user2_with_key, db_session_factory):
    """GET /api/v1/sync-runs only returns the current user's sync runs."""
    from src.models import SyncRun as _SR
    from datetime import datetime, timezone

    # User 1: create source + insert a run
    source1 = await _create_source(client_with_key, "User1 Dashboard Source")
    async with db_session_factory() as db:
        db.add(_SR(
            source_id=source1["id"],
            user_id=DEV_USER_1,
            connector_type="s3_compatible",
            trigger_type="manual",
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    # User 2 should see 0 runs (no sources/runs for user 2)
    resp2 = await client_user2_with_key.get("/api/v1/sync-runs")
    assert resp2.status_code == 200
    assert resp2.json()["total"] == 0

    # User 1 sees their own run
    resp1 = await client_with_key.get("/api/v1/sync-runs")
    assert resp1.json()["total"] >= 1


# ---------------------------------------------------------------------------
# 11. PATCH /sources/{id}/connector/s3 — S3 re-configuration (P7-009)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_s3_connector_updates_bucket(client_with_key):
    """PATCH updates the bucket name in place without touching credentials."""
    source = await _create_source(client_with_key, "S3 Patch Bucket")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/s3",
        json={"bucket_name": "updated-bucket"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["remote_container_id"] == "updated-bucket"
    assert body["region"] == _S3_CONFIG["region"]


@pytest.mark.asyncio
async def test_patch_s3_connector_updates_credentials(client_with_key):
    """PATCH re-encrypts credentials when both access_key_id + secret are provided."""
    source = await _create_source(client_with_key, "S3 Patch Creds")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/s3",
        json={
            "access_key_id": "NEW_KEY_ID",
            "secret_access_key": "NEW_SECRET",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Bucket unchanged
    assert body["remote_container_id"] == _S3_CONFIG["bucket_name"]
    # Secrets are never returned
    assert "access_key_id" not in body
    assert "secret_access_key" not in body


@pytest.mark.asyncio
async def test_patch_s3_connector_partial_credentials_422(client_with_key):
    """PATCH with only one credential field returns 422."""
    source = await _create_source(client_with_key, "S3 Patch Half Creds")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/s3",
        json={"access_key_id": "ONLY_KEY_ID"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_s3_connector_no_connector_404(client_with_key):
    """PATCH returns 404 when no connector has been configured yet."""
    source = await _create_source(client_with_key, "S3 Patch No Connector")
    resp = await client_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/s3",
        json={"bucket_name": "anything"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_s3_connector_user_scoped(client_with_key, client_user2_with_key):
    """PATCH on another user's source returns 404."""
    source = await _create_source(client_with_key, "S3 Patch Scope")
    await client_with_key.post(
        f"/api/v1/sources/{source['id']}/connector/s3", json=_S3_CONFIG
    )
    resp = await client_user2_with_key.patch(
        f"/api/v1/sources/{source['id']}/connector/s3",
        json={"bucket_name": "hacked"},
    )
    assert resp.status_code == 404


