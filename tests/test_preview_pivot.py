"""Integration tests for P8-002: Browser-Upload Preview-Only Pivot.

Coverage:
  - _attempt_preview_pivot eligibility for connector items
  - _attempt_preview_pivot eligibility for local working-folder items
  - _attempt_preview_pivot non-eligibility for __uploads__ system source
  - _attempt_preview_pivot guards: no thumbnail_path, no SourceObject, already preview_only
  - Non-fatal deletion failure leaves item in consistent full state
  - Replay-safety: persisted state (not transient flag) drives the decision
  - Sync-service refactor regression: connector sync still transitions to preview_only
  - Manual browser upload stays full after analysis
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from cryptography.fernet import Fernet
from sqlalchemy import select

from src.analysis.processor import _attempt_preview_pivot, SOURCE_TYPE_LOCAL_FOLDER
from src.models import MediaItem, ProcessingJob, Source, SourceConnector, SourceObject
from src.storage.file_store import LocalFileStore
from src.ingestion.upload_service import UploadService
from tests.conftest import JPEG_BYTES, DEV_USER_1

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_source(db, user_id: str, name: str, source_type: str = "manual") -> Source:
    source = Source(user_id=user_id, name=name, source_type=source_type)
    db.add(source)
    await db.flush()
    return source


async def _make_connector_source(db, user_id: str, name: str = "S3 Source") -> tuple[Source, SourceConnector]:
    from src.connectors.secrets import encrypt_credentials
    import src.config as cfg_mod
    # Temporarily set key for encrypt_credentials
    original_key = cfg_mod.settings.connector.credentials_key
    cfg_mod.settings.connector.credentials_key = _TEST_FERNET_KEY
    try:
        source = await _make_source(db, user_id, name, source_type="s3_compatible")
        sc = SourceConnector(
            source_id=source.id,
            user_id=user_id,
            connector_type="s3_compatible",
            remote_container_id="my-bucket",
            region="us-east-1",
            credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
        )
        db.add(sc)
        await db.flush()
    finally:
        cfg_mod.settings.connector.credentials_key = original_key
    return source, sc


async def _make_media_item(
    db,
    user_id: str,
    source_id: str,
    file_store: LocalFileStore,
    *,
    storage_mode: str = "full",
    thumbnail_path: str | None = "thumbs/thumb.jpg",
    source_file_fingerprint: str | None = None,
) -> MediaItem:
    """Create a MediaItem with a stored file so delete() won't raise."""
    content_hash = "deadbeef" + user_id[:8].replace("-", "")
    # Store a real file so file_store.delete() can find it
    storage_path = await file_store.save(user_id, content_hash, "photo.jpg", JPEG_BYTES)
    if thumbnail_path and thumbnail_path.startswith("thumbnails/"):
        # Use real save_thumbnail path
        thumb_bytes = JPEG_BYTES
        thumbnail_path = await file_store.save_thumbnail(user_id, content_hash, thumb_bytes)
    item = MediaItem(
        user_id=user_id,
        content_hash=content_hash,
        original_filename="photo.jpg",
        file_size=len(JPEG_BYTES),
        mime_type="image/jpeg",
        storage_path=storage_path if storage_mode == "full" else None,
        storage_mode=storage_mode,
        thumbnail_path=thumbnail_path,
        status="completed",
        source_id=source_id,
        source_file_fingerprint=source_file_fingerprint,
    )
    db.add(item)
    await db.flush()
    return item


async def _make_source_object(db, source_id: str, user_id: str, media_item_id: str) -> SourceObject:
    from datetime import datetime, timezone
    so = SourceObject(
        source_id=source_id,
        user_id=user_id,
        external_object_key="images/photo.jpg",
        external_version="etag-v1",
        external_last_modified_at=datetime.now(timezone.utc),
        external_size=len(JPEG_BYTES),
        last_imported_media_item_id=media_item_id,
        last_content_hash="deadbeef",
        state="imported",
        last_error=None,
    )
    db.add(so)
    await db.flush()
    return so


# ---------------------------------------------------------------------------
# 1. Connector item — eligible → transitions to preview_only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_eligible_connector_item(db_session_factory, seed_users, tmp_storage):
    """Eligible connector item with SourceObject + thumbnail transitions to preview_only."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

        original_path = item.storage_path
        await _attempt_preview_pivot(db, item, file_store)

        assert item.storage_mode == "preview_only"
        assert item.storage_path is None

    # Verify committed to DB
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item.id))
        refreshed = result.scalar_one()
    assert refreshed.storage_mode == "preview_only"
    assert refreshed.storage_path is None


# ---------------------------------------------------------------------------
# 2. Local working-folder item — eligible → transitions to preview_only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_eligible_local_folder_item(db_session_factory, seed_users, tmp_storage):
    """Eligible local_folder source item with fingerprint transitions to preview_only."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        # No SourceConnector — this is a local working-folder source
        source = await _make_source(db, DEV_USER_1, "Local Folder", source_type=SOURCE_TYPE_LOCAL_FOLDER)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store,
            source_file_fingerprint="abc123fingerprint",
        )
        await db.commit()

        await _attempt_preview_pivot(db, item, file_store)

        assert item.storage_mode == "preview_only"
        assert item.storage_path is None


# ---------------------------------------------------------------------------
# 3. __uploads__ system source — never eligible
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_ineligible_uploads_source(db_session_factory, seed_users, tmp_storage):
    """Manual __uploads__ source items must never transition to preview_only."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source = await _make_source(db, DEV_USER_1, "__uploads__", source_type="manual")
        item = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        await db.commit()

        original_path = item.storage_path
        await _attempt_preview_pivot(db, item, file_store)

        assert item.storage_mode == "full"
        assert item.storage_path == original_path


# ---------------------------------------------------------------------------
# 4. Missing thumbnail_path — stays full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_no_thumbnail_path_leaves_full(db_session_factory, seed_users, tmp_storage):
    """Item without a thumbnail_path must never be transitioned to preview_only."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store,
            thumbnail_path=None,
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

        original_path = item.storage_path
        await _attempt_preview_pivot(db, item, file_store)

        assert item.storage_mode == "full"
        assert item.storage_path == original_path


# ---------------------------------------------------------------------------
# 5. Connector item but no SourceObject — stays full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_no_source_object_leaves_full(db_session_factory, seed_users, tmp_storage):
    """Connector item without a committed SourceObject stays full (Decision 9 contract)."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        # No SourceObject created
        await db.commit()

        original_path = item.storage_path
        await _attempt_preview_pivot(db, item, file_store)

        assert item.storage_mode == "full"
        assert item.storage_path == original_path


# ---------------------------------------------------------------------------
# 6. Deletion failure — non-fatal, item stays full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_deletion_failure_leaves_full(db_session_factory, seed_users, tmp_storage):
    """When file_store.delete raises, the item remains full and the state is consistent."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

        original_path = item.storage_path

        # Patch file_store.delete to raise
        with patch.object(file_store, "delete", new_callable=AsyncMock, side_effect=OSError("disk error")):
            await _attempt_preview_pivot(db, item, file_store)

        # Item must stay full — no state corruption
        assert item.storage_mode == "full"
        assert item.storage_path == original_path

    # Verify DB state is also unchanged
    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item.id))
        refreshed = result.scalar_one()
    assert refreshed.storage_mode == "full"
    assert refreshed.storage_path is not None


# ---------------------------------------------------------------------------
# 7. Already preview_only — idempotent no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_idempotent_when_already_preview_only(db_session_factory, seed_users, tmp_storage):
    """Calling _attempt_preview_pivot on an already-preview_only item is a safe no-op."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store,
            storage_mode="preview_only",
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

        # Should not raise and should not change state
        with patch.object(file_store, "delete", new_callable=AsyncMock) as mock_del:
            await _attempt_preview_pivot(db, item, file_store)
            mock_del.assert_not_called()

        assert item.storage_mode == "preview_only"


# ---------------------------------------------------------------------------
# 8. Replay-safety: same result driven from persisted state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_replay_safe_persisted_state(db_session_factory, seed_users, tmp_storage):
    """Pivot decision is driven from persisted state — calling twice yields the same result."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

        # First call — should pivot
        await _attempt_preview_pivot(db, item, file_store)
        assert item.storage_mode == "preview_only"

        # Second call — idempotent no-op (storage_mode already preview_only)
        with patch.object(file_store, "delete", new_callable=AsyncMock) as mock_del:
            await _attempt_preview_pivot(db, item, file_store)
            mock_del.assert_not_called()

        assert item.storage_mode == "preview_only"


# ---------------------------------------------------------------------------
# 9. Local folder WITHOUT fingerprint stays full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_local_folder_no_fingerprint_stays_full(db_session_factory, seed_users, tmp_storage):
    """Local folder item without source_file_fingerprint is not eligible."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source = await _make_source(db, DEV_USER_1, "My Folder", source_type=SOURCE_TYPE_LOCAL_FOLDER)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store,
            source_file_fingerprint=None,  # no fingerprint — not eligible
        )
        await db.commit()

        original_path = item.storage_path
        await _attempt_preview_pivot(db, item, file_store)

        assert item.storage_mode == "full"
        assert item.storage_path == original_path


# ---------------------------------------------------------------------------
# 10. Sync-service regression: connector sync still pivots after refactor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_connector_pivot_regression(db_session_factory, seed_users, tmp_storage, monkeypatch):
    """After P8-002 refactor, connector sync still transitions items to preview_only."""
    import src.config as cfg_mod
    import src.analysis.processor as processor_mod
    monkeypatch.setattr(cfg_mod.settings.connector, "credentials_key", _TEST_FERNET_KEY)

    # Wire processor to use test DB
    original_proc_session = processor_mod.async_session
    processor_mod.async_session = db_session_factory

    try:
        from src.connectors.sync_service import trigger_sync
        from src.connectors.secrets import encrypt_credentials
        from src.analysis.mock_provider import MockVisionProvider

        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)

        async with db_session_factory() as db:
            source = Source(name="Drive Source", user_id=DEV_USER_1, source_type="s3_compatible")
            db.add(source)
            await db.commit()
            await db.refresh(source)

            sc = SourceConnector(
                source_id=source.id,
                user_id=DEV_USER_1,
                connector_type="s3_compatible",
                remote_container_id="my-bucket",
                region="us-east-1",
                credentials_encrypted=encrypt_credentials({"access_key_id": "K", "secret_access_key": "S"}),
            )
            db.add(sc)
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

            # Patch the mock vision provider into the processor for this test
            with patch("src.connectors.sync_service._get_vision_provider", return_value=MockVisionProvider()), \
                 patch("src.connectors.s3_connector.S3Connector.list_objects", new_callable=AsyncMock, return_value=[remote_obj]), \
                 patch("src.connectors.s3_connector.S3Connector.download_object", new_callable=AsyncMock, return_value=JPEG_BYTES):

                result = await trigger_sync(
                    source_id=source.id,
                    user_id=DEV_USER_1,
                    db=db,
                    file_store=file_store,
                    upload_service=upload_service,
                )

        assert result.imported_count == 1
        assert result.status in ("completed", "completed_with_errors")

        # Verify media item transitioned to preview_only
        async with db_session_factory() as db:
            result_q = await db.execute(
                select(MediaItem).where(
                    MediaItem.user_id == DEV_USER_1,
                    MediaItem.source_id == source.id,
                )
            )
            item = result_q.scalar_one_or_none()

        assert item is not None
        # Item should be preview_only if analysis + thumbnail succeeded
        if item.thumbnail_path is not None:
            assert item.storage_mode == "preview_only", (
                f"Expected preview_only but got {item.storage_mode!r}"
            )
        else:
            # No thumbnail means no pivot — full retention is correct
            assert item.storage_mode == "full"

    finally:
        processor_mod.async_session = original_proc_session


# ---------------------------------------------------------------------------
# 11. Manual browser upload stays full after analysis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manual_upload_stays_full_after_analysis(db_session_factory, seed_users, tmp_storage, monkeypatch):
    """Items in the __uploads__ source are never transitioned to preview_only by the processor."""
    import src.analysis.processor as processor_mod
    from src.analysis.processor import analyze_media_item
    from src.analysis.mock_provider import MockVisionProvider

    original_proc_session = processor_mod.async_session
    processor_mod.async_session = db_session_factory

    try:
        file_store = LocalFileStore(tmp_storage)
        upload_service = UploadService(file_store)

        async with db_session_factory() as db:
            # Create __uploads__ source manually
            uploads_source = Source(user_id=DEV_USER_1, name="__uploads__", source_type="manual")
            db.add(uploads_source)
            await db.commit()
            await db.refresh(uploads_source)

        # Upload a file (which auto-creates __uploads__ or uses the one we made)
        async with db_session_factory() as db:
            result = await upload_service.process_upload(
                db, DEV_USER_1, "manual.jpg", JPEG_BYTES,
                source_id=uploads_source.id,
            )
            assert result.success
            media_item = result.media_item
            job_id = result.processing_job_id
            assert job_id is not None

        # Run analysis directly
        await analyze_media_item(
            job_id,
            MockVisionProvider(),
            file_store,
        )

        # Verify item is still full — __uploads__ is never eligible
        async with db_session_factory() as db:
            q = await db.execute(select(MediaItem).where(MediaItem.id == media_item.id))
            refreshed = q.scalar_one()

        assert refreshed.storage_mode == "full", (
            f"__uploads__ item must stay full but got {refreshed.storage_mode!r}"
        )
        assert refreshed.storage_path is not None

    finally:
        processor_mod.async_session = original_proc_session
