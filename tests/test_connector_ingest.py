"""Integration tests for P9-001: Zero-Transient Connector Ingestion.

Coverage:
  - process_connector_import: happy path creates reference-mode item without storage_path
  - process_connector_import: duplicate detection returns existing item
  - process_connector_import: validation failure returns error UploadResult
  - process_connector_import: thumbnail failure leaves item in reference mode (no thumbnail)
  - analyze_connector_item: persists analysis metadata, marks job completed
  - analyze_connector_item: marks job/item failed on vision-provider error (no crash)
  - trigger_sync: full connector sync produces reference-mode items, storage_path=None
  - trigger_sync: file_store.save() is never called during connector sync
  - trigger_sync: re-sync of same objects produces duplicate result
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from cryptography.fernet import Fernet
from sqlalchemy import select

from src.ingestion.connector_ingest import process_connector_import
from src.models import MediaItem, ProcessingJob, Source, SourceConnector, SourceObject
from src.storage.file_store import LocalFileStore
from tests.conftest import DEV_USER_1, JPEG_BYTES

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_s3_source(db, user_id: str) -> tuple[Source, SourceConnector]:
    from src.connectors.secrets import encrypt_credentials
    import src.config as cfg_mod

    original_key = cfg_mod.settings.connector.credentials_key
    cfg_mod.settings.connector.credentials_key = _TEST_FERNET_KEY
    try:
        source = Source(user_id=user_id, name="Test Drive", source_type="s3_compatible")
        db.add(source)
        await db.flush()

        sc = SourceConnector(
            source_id=source.id,
            user_id=user_id,
            connector_type="s3_compatible",
            remote_container_id="my-bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials(
                {"access_key_id": "K", "secret_access_key": "S"}
            ),
        )
        db.add(sc)
        await db.flush()
        return source, sc
    finally:
        cfg_mod.settings.connector.credentials_key = original_key


# ---------------------------------------------------------------------------
# 1. Happy path: reference-mode item created, no storage_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_connector_import_happy_path(
    db_session_factory, seed_users, tmp_storage
):
    """process_connector_import creates a MediaItem with storage_mode='reference' and
    storage_path=None, and only persists a thumbnail to app storage."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="photo.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
            file_store=file_store,
        )

    assert result.success is True
    assert result.is_duplicate is False
    assert result.media_item is not None
    assert result.media_item.storage_mode == "reference"
    assert result.media_item.storage_path is None
    assert result.processing_job_id is not None

    # Thumbnail should have been generated and persisted
    assert result.thumbnail_path is not None

    # No full original should exist in the file store
    original_would_be = f"files/{DEV_USER_1}/{result.media_item.content_hash}_photo.jpg"
    import os
    assert not os.path.exists(os.path.join(tmp_storage, original_would_be))


# ---------------------------------------------------------------------------
# 2. Duplicate detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_connector_import_duplicate(
    db_session_factory, seed_users, tmp_storage
):
    """Second import of the same bytes returns is_duplicate=True without creating
    a new MediaItem."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        # First import
        first_result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="photo.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
            file_store=file_store,
        )
        first_item_id = first_result.media_item.id

    # Second import (same bytes)
    async with db_session_factory() as db:
        result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="photo_copy.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
            file_store=file_store,
        )

    assert result.success is True
    assert result.is_duplicate is True
    assert result.media_item.id == first_item_id

    # Confirm only one MediaItem exists for this user
    async with db_session_factory() as db:
        count_result = await db.execute(
            select(MediaItem).where(MediaItem.user_id == DEV_USER_1)
        )
        items = count_result.scalars().all()
    assert len(items) == 1


# ---------------------------------------------------------------------------
# 3. Validation failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_connector_import_validation_failure(
    db_session_factory, seed_users, tmp_storage
):
    """process_connector_import returns error UploadResult for invalid files."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="malware.exe",
            file_bytes=b"\x00" * 50,
            source_id=source.id,
            file_store=file_store,
        )

    assert result.success is False
    assert result.error is not None

    # No MediaItem created
    async with db_session_factory() as db:
        count_result = await db.execute(
            select(MediaItem).where(MediaItem.user_id == DEV_USER_1)
        )
        assert count_result.scalars().first() is None


# ---------------------------------------------------------------------------
# 4. Thumbnail failure leaves item in reference mode without thumbnail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_connector_import_thumbnail_failure(
    db_session_factory, seed_users, tmp_storage
):
    """If thumbnail generation fails, item is still saved in reference mode with
    thumbnail_path=None.  The failure must not abort the import."""
    file_store = LocalFileStore(tmp_storage)

    with patch(
        "src.ingestion.connector_ingest._generate_thumbnail",
        side_effect=RuntimeError("pillow broke"),
    ):
        async with db_session_factory() as db:
            source, _ = await _make_s3_source(db, DEV_USER_1)
            await db.commit()

            result = await process_connector_import(
                db=db,
                user_id=DEV_USER_1,
                filename="photo.jpg",
                file_bytes=JPEG_BYTES,
                source_id=source.id,
                file_store=file_store,
            )

    assert result.success is True
    assert result.is_duplicate is False
    assert result.media_item.storage_mode == "reference"
    assert result.media_item.storage_path is None
    assert result.thumbnail_path is None


# ---------------------------------------------------------------------------
# 5. analyze_connector_item: success path persists metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_connector_item_success(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """analyze_connector_item marks the job completed and the item completed."""
    import src.analysis.processor as processor_mod
    from src.analysis.processor import analyze_connector_item
    from src.analysis.mock_provider import MockVisionProvider

    monkeypatch.setattr(processor_mod, "async_session", db_session_factory)

    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        import_result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="photo.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
            file_store=file_store,
        )

    assert import_result.success
    job_id = import_result.processing_job_id

    await analyze_connector_item(
        job_id=job_id,
        file_bytes=JPEG_BYTES,
        vision_provider=MockVisionProvider(),
        file_store=file_store,
    )

    async with db_session_factory() as db:
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = job_result.scalar_one()
        item_result = await db.execute(
            select(MediaItem).where(MediaItem.id == job.media_item_id)
        )
        item = item_result.scalar_one()

    assert job.status == "completed"
    assert item.status == "completed"
    # storage_mode must remain reference — no pivot occurred
    assert item.storage_mode == "reference"
    assert item.storage_path is None


# ---------------------------------------------------------------------------
# 6. analyze_connector_item: vision-provider error marks job failed gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_connector_item_analysis_error(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """If vision analysis raises, analyze_connector_item marks the job/item failed
    without crashing and without changing storage_mode."""
    import src.analysis.processor as processor_mod
    from src.analysis.processor import analyze_connector_item

    monkeypatch.setattr(processor_mod, "async_session", db_session_factory)

    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        import_result = await process_connector_import(
            db=db,
            user_id=DEV_USER_1,
            filename="photo.jpg",
            file_bytes=JPEG_BYTES,
            source_id=source.id,
            file_store=file_store,
        )

    assert import_result.success
    job_id = import_result.processing_job_id

    broken_provider = MagicMock()
    broken_provider.analyze_image = AsyncMock(side_effect=RuntimeError("API down"))

    await analyze_connector_item(
        job_id=job_id,
        file_bytes=JPEG_BYTES,
        vision_provider=broken_provider,
        file_store=file_store,
    )

    async with db_session_factory() as db:
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = job_result.scalar_one()
        item_result = await db.execute(
            select(MediaItem).where(MediaItem.id == job.media_item_id)
        )
        item = item_result.scalar_one()

    assert job.status == "failed"
    assert item.status == "error"
    assert item.storage_mode == "reference"
    assert item.storage_path is None


# ---------------------------------------------------------------------------
# 7. trigger_sync: full connector sync produces reference-mode items, no save()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_sync_produces_reference_items(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """trigger_sync imports connector objects as storage_mode='reference' with
    storage_path=None.  file_store.save() must never be called."""
    import src.config as cfg_mod
    import src.analysis.processor as processor_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(processor_mod, "async_session", db_session_factory)

    file_store = LocalFileStore(tmp_storage)
    upload_service_stub = MagicMock()  # kept in signature for backward compat; not called

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        from src.connectors.base import RemoteObject
        from datetime import datetime, timezone

        remote_obj = RemoteObject(
            key="images/photo.jpg",
            display_name="photo.jpg",
            version="etag-1",
            last_modified_at=datetime.now(timezone.utc),
            size=len(JPEG_BYTES),
        )

        save_calls: list = []
        original_save = file_store.save

        async def tracking_save(*args, **kwargs):
            save_calls.append((args, kwargs))
            return await original_save(*args, **kwargs)

        file_store.save = tracking_save  # type: ignore[method-assign]

        from src.connectors.sync_service import trigger_sync
        from src.analysis.mock_provider import MockVisionProvider

        with (
            patch("src.connectors.sync_service._get_vision_provider", return_value=MockVisionProvider()),
            patch("src.connectors.sync_service._get_indexing_service", return_value=None),
            patch(
                "src.connectors.s3_connector.S3Connector.list_objects",
                new_callable=AsyncMock,
                return_value=[remote_obj],
            ),
            patch(
                "src.connectors.s3_connector.S3Connector.download_object",
                new_callable=AsyncMock,
                return_value=JPEG_BYTES,
            ),
        ):
            result = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service_stub,
            )

    assert result.imported_count == 1, f"Expected 1 import, got {result}"

    # file_store.save() must NEVER have been called (no full-original writes)
    assert save_calls == [], (
        f"file_store.save() was called {len(save_calls)} time(s) — transient write detected"
    )

    # Check DB state
    async with db_session_factory() as db:
        item_result = await db.execute(
            select(MediaItem).where(
                MediaItem.user_id == DEV_USER_1,
                MediaItem.source_id == source.id,
            )
        )
        item = item_result.scalar_one_or_none()

    assert item is not None
    assert item.storage_mode == "reference"
    assert item.storage_path is None


# ---------------------------------------------------------------------------
# 8. trigger_sync: re-sync of identical objects produces duplicate result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_sync_resync_duplicate(
    db_session_factory, seed_users, tmp_storage, monkeypatch
):
    """A second sync with unchanged objects produces duplicate_count=1, imported_count=0."""
    import src.config as cfg_mod
    import src.analysis.processor as processor_mod

    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)
    monkeypatch.setattr(processor_mod, "async_session", db_session_factory)

    file_store = LocalFileStore(tmp_storage)
    upload_service_stub = MagicMock()

    from src.connectors.base import RemoteObject
    from datetime import datetime, timezone

    remote_obj = RemoteObject(
        key="images/photo.jpg",
        display_name="photo.jpg",
        version="etag-1",
        last_modified_at=datetime.now(timezone.utc),
        size=len(JPEG_BYTES),
    )

    from src.connectors.sync_service import trigger_sync
    from src.analysis.mock_provider import MockVisionProvider

    mock_patches = (
        patch("src.connectors.sync_service._get_vision_provider", return_value=MockVisionProvider()),
        patch("src.connectors.sync_service._get_indexing_service", return_value=None),
        patch(
            "src.connectors.s3_connector.S3Connector.list_objects",
            new_callable=AsyncMock,
            return_value=[remote_obj],
        ),
        patch(
            "src.connectors.s3_connector.S3Connector.download_object",
            new_callable=AsyncMock,
            return_value=JPEG_BYTES,
        ),
    )

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        with mock_patches[0], mock_patches[1], mock_patches[2], mock_patches[3]:
            first = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service_stub,
            )

    assert first.imported_count == 1

    # Second sync — same object, different version (forces re-download), same bytes
    remote_obj_v2 = RemoteObject(
        key="images/photo.jpg",
        display_name="photo.jpg",
        version="etag-2",  # new version triggers re-download
        last_modified_at=datetime.now(timezone.utc),
        size=len(JPEG_BYTES),
    )

    async with db_session_factory() as db:
        with (
            patch("src.connectors.sync_service._get_vision_provider", return_value=MockVisionProvider()),
            patch("src.connectors.sync_service._get_indexing_service", return_value=None),
            patch(
                "src.connectors.s3_connector.S3Connector.list_objects",
                new_callable=AsyncMock,
                return_value=[remote_obj_v2],
            ),
            patch(
                "src.connectors.s3_connector.S3Connector.download_object",
                new_callable=AsyncMock,
                return_value=JPEG_BYTES,
            ),
        ):
            second = await trigger_sync(
                source_id=source.id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service_stub,
            )

    assert second.imported_count == 0
    assert second.duplicate_count == 1
