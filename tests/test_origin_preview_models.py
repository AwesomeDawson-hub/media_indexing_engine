"""P9-003 integration tests: OriginAssetRef and PreviewAsset domain split.

Coverage (12 tests):
  1.  Upload creates OriginAssetRef with provider_type='app_upload'
  2.  Upload: OriginAssetRef.app_storage_path mirrors MediaItem.storage_path
  3.  Upload creates PreviewAsset(variant_type='thumbnail') when thumbnail generated
  4.  Connector import creates OriginAssetRef
  5.  Connector import: OriginAssetRef.app_storage_path is None (reference mode)
  6.  Connector import: provider_type and provider_object_id stored correctly
  7.  Connector import creates PreviewAsset(variant_type='thumbnail') when thumbnail generated
  8.  Connector import: source_object_id is initially None (set by sync_service later)
  9.  Sync populates OriginAssetRef.source_object_id after SourceObject is committed
  10. MediaItem.origin_asset_ref ORM relationship loads correctly
  11. MediaItem.preview_assets ORM relationship loads correctly
  12. Duplicate upload produces no second OriginAssetRef
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from unittest.mock import AsyncMock, patch

from src.ingestion.connector_ingest import process_connector_import
from src.ingestion.upload_service import UploadService
from src.models import MediaItem, OriginAssetRef, PreviewAsset, Source, SourceConnector
from src.storage.file_store import LocalFileStore
from tests.conftest import DEV_USER_1, JPEG_BYTES

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_s3_source(db, user_id: str) -> tuple[Source, SourceConnector]:
    """Create a Source + s3_compatible SourceConnector in the session."""
    from src.connectors.secrets import encrypt_credentials
    import src.config as cfg_mod

    original_key = cfg_mod.settings.connector.credentials_key
    cfg_mod.settings.connector.credentials_key = _TEST_FERNET_KEY
    try:
        source = Source(user_id=user_id, name="Test Bucket", source_type="s3_compatible")
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
# 1. Upload creates OriginAssetRef with provider_type='app_upload'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_creates_origin_asset_ref(db_session_factory, seed_users, tmp_storage):
    """process_upload creates an OriginAssetRef with provider_type='app_upload'."""
    file_store = LocalFileStore(tmp_storage)
    service = UploadService(file_store)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        result = await service.process_upload(
            db, DEV_USER_1, "photo.jpg", JPEG_BYTES
        )
        assert result.success
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one_or_none()

    assert ref is not None
    assert ref.provider_type == "app_upload"
    assert ref.user_id == DEV_USER_1


# ---------------------------------------------------------------------------
# 2. Upload: OriginAssetRef.app_storage_path mirrors MediaItem.storage_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_origin_ref_app_storage_path_mirrors_media_item(
    db_session_factory, seed_users, tmp_storage
):
    """OriginAssetRef.app_storage_path must equal MediaItem.storage_path for uploads."""
    file_store = LocalFileStore(tmp_storage)
    service = UploadService(file_store)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        result = await service.process_upload(db, DEV_USER_1, "photo.jpg", JPEG_BYTES)
        assert result.success
        media_item_id = result.media_item.id
        storage_path = result.media_item.storage_path

    async with db_session_factory() as db:
        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one()

    assert ref.app_storage_path == storage_path
    assert ref.app_storage_path is not None


# ---------------------------------------------------------------------------
# 3. Upload creates PreviewAsset(variant_type='thumbnail') when thumbnail generated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_creates_preview_asset_for_thumbnail(
    db_session_factory, seed_users, tmp_storage
):
    """process_upload creates a PreviewAsset with variant_type='thumbnail' when a
    thumbnail is persisted."""
    file_store = LocalFileStore(tmp_storage)
    service = UploadService(file_store)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        result = await service.process_upload(db, DEV_USER_1, "photo.jpg", JPEG_BYTES)
        assert result.success
        assert result.thumbnail_path is not None, "Thumbnail must be generated for this test"
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        preview = (await db.execute(
            select(PreviewAsset).where(
                PreviewAsset.media_item_id == media_item_id,
                PreviewAsset.variant_type == "thumbnail",
            )
        )).scalar_one_or_none()

    assert preview is not None
    assert preview.variant_type == "thumbnail"
    assert preview.mime_type == "image/jpeg"
    assert preview.storage_path is not None


# ---------------------------------------------------------------------------
# 4. Connector import creates OriginAssetRef
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_import_creates_origin_asset_ref(
    db_session_factory, seed_users, tmp_storage
):
    """process_connector_import creates an OriginAssetRef for the imported item."""
    file_store = LocalFileStore(tmp_storage)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db, user_id=DEV_USER_1, filename="photo.jpg",
            file_bytes=JPEG_BYTES, source_id=source.id, file_store=file_store,
        )
        assert result.success
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one_or_none()

    assert ref is not None
    assert ref.user_id == DEV_USER_1


# ---------------------------------------------------------------------------
# 5. Connector import: OriginAssetRef.app_storage_path is None (reference mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_import_origin_ref_app_storage_path_is_null(
    db_session_factory, seed_users, tmp_storage
):
    """Connector imports use reference mode — no original in app storage, so
    OriginAssetRef.app_storage_path must be None."""
    file_store = LocalFileStore(tmp_storage)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db, user_id=DEV_USER_1, filename="photo.jpg",
            file_bytes=JPEG_BYTES, source_id=source.id, file_store=file_store,
        )
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one()

    assert ref.app_storage_path is None


# ---------------------------------------------------------------------------
# 6. Connector import: provider_type and provider_object_id stored correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_import_provider_type_and_object_id_stored(
    db_session_factory, seed_users, tmp_storage
):
    """process_connector_import stores provider_type and provider_object_id on the
    OriginAssetRef from the kwargs passed to it."""
    file_store = LocalFileStore(tmp_storage)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db, user_id=DEV_USER_1, filename="photo.jpg",
            file_bytes=JPEG_BYTES, source_id=source.id, file_store=file_store,
            provider_type="s3_compatible",
            provider_object_id="images/photo.jpg",
            revision_marker="etag-abc123",
        )
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one()

    assert ref.provider_type == "s3_compatible"
    assert ref.provider_object_id == "images/photo.jpg"
    assert ref.revision_marker == "etag-abc123"


# ---------------------------------------------------------------------------
# 7. Connector import creates PreviewAsset when thumbnail generated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_import_creates_preview_asset(
    db_session_factory, seed_users, tmp_storage
):
    """process_connector_import creates a PreviewAsset(variant_type='thumbnail') when
    thumbnail generation succeeds."""
    file_store = LocalFileStore(tmp_storage)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db, user_id=DEV_USER_1, filename="photo.jpg",
            file_bytes=JPEG_BYTES, source_id=source.id, file_store=file_store,
        )
        assert result.thumbnail_path is not None, "Thumbnail must be generated for this test"
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        preview = (await db.execute(
            select(PreviewAsset).where(
                PreviewAsset.media_item_id == media_item_id,
                PreviewAsset.variant_type == "thumbnail",
            )
        )).scalar_one_or_none()

    assert preview is not None
    assert preview.mime_type == "image/jpeg"


# ---------------------------------------------------------------------------
# 8. Connector import: source_object_id is initially None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_import_source_object_id_initially_null(
    db_session_factory, seed_users, tmp_storage
):
    """Right after process_connector_import, OriginAssetRef.source_object_id must be
    None because the SourceObject has not been upserted yet (sync_service does it
    afterward)."""
    file_store = LocalFileStore(tmp_storage)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()

        result = await process_connector_import(
            db=db, user_id=DEV_USER_1, filename="photo.jpg",
            file_bytes=JPEG_BYTES, source_id=source.id, file_store=file_store,
        )
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one()

    assert ref.source_object_id is None


# ---------------------------------------------------------------------------
# 9. Sync populates OriginAssetRef.source_object_id after SourceObject is committed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_populates_source_object_id(
    db_session_factory, seed_users, tmp_storage
):
    """After a full trigger_sync, OriginAssetRef.source_object_id must be non-null
    and must reference the SourceObject created by the sync."""
    from src.connectors.base import RemoteObject
    from src.connectors.sync_service import trigger_sync
    from src.analysis.mock_provider import MockVisionProvider
    from src.models import SourceObject
    from datetime import datetime, timezone

    file_store = LocalFileStore(tmp_storage)
    upload_service_stub = object()  # not used directly by trigger_sync

    remote_obj = RemoteObject(
        key="images/photo.jpg",
        display_name="photo.jpg",
        version="etag-1",
        last_modified_at=datetime.now(timezone.utc),
        size=len(JPEG_BYTES),
    )

    import src.config as _cfg
    source_id: str | None = None
    media_item_id: str | None = None

    async with db_session_factory() as db:
        source, _ = await _make_s3_source(db, DEV_USER_1)
        await db.commit()
        source_id = source.id

    async with db_session_factory() as db:
        _cfg.settings.connector.credentials_key = _TEST_FERNET_KEY
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
            sync_result = await trigger_sync(
                source_id=source_id,
                user_id=DEV_USER_1,
                db=db,
                file_store=file_store,
                upload_service=upload_service_stub,
            )
        _cfg.settings.connector.credentials_key = ""

    assert sync_result.imported_count == 1

    async with db_session_factory() as db:
        # Find the imported MediaItem
        so_row = (await db.execute(
            select(SourceObject).where(
                SourceObject.source_id == source_id,
                SourceObject.external_object_key == "images/photo.jpg",
            )
        )).scalar_one()
        media_item_id = so_row.last_imported_media_item_id

        ref = (await db.execute(
            select(OriginAssetRef).where(OriginAssetRef.media_item_id == media_item_id)
        )).scalar_one()

    assert ref.source_object_id is not None
    assert ref.source_object_id == so_row.id


# ---------------------------------------------------------------------------
# 10. MediaItem.origin_asset_ref ORM relationship loads correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_item_origin_asset_ref_relationship(
    db_session_factory, seed_users, tmp_storage
):
    """MediaItem.origin_asset_ref must load via the ORM relationship."""
    file_store = LocalFileStore(tmp_storage)
    service = UploadService(file_store)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        result = await service.process_upload(db, DEV_USER_1, "photo.jpg", JPEG_BYTES)
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        item = (await db.execute(
            select(MediaItem)
            .options(selectinload(MediaItem.origin_asset_ref))
            .where(MediaItem.id == media_item_id)
        )).scalar_one()

    assert item.origin_asset_ref is not None
    assert item.origin_asset_ref.media_item_id == media_item_id


# ---------------------------------------------------------------------------
# 11. MediaItem.preview_assets ORM relationship loads correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_item_preview_assets_relationship(
    db_session_factory, seed_users, tmp_storage
):
    """MediaItem.preview_assets must load via the ORM relationship and contain
    the thumbnail PreviewAsset created during upload."""
    file_store = LocalFileStore(tmp_storage)
    service = UploadService(file_store)

    media_item_id: str | None = None
    async with db_session_factory() as db:
        result = await service.process_upload(db, DEV_USER_1, "photo.jpg", JPEG_BYTES)
        assert result.thumbnail_path is not None
        media_item_id = result.media_item.id

    async with db_session_factory() as db:
        item = (await db.execute(
            select(MediaItem)
            .options(selectinload(MediaItem.preview_assets))
            .where(MediaItem.id == media_item_id)
        )).scalar_one()

    assert len(item.preview_assets) == 1
    assert item.preview_assets[0].variant_type == "thumbnail"


# ---------------------------------------------------------------------------
# 12. Duplicate upload produces no second OriginAssetRef
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_upload_no_duplicate_origin_asset_ref(
    db_session_factory, seed_users, tmp_storage
):
    """Uploading the same file twice returns a duplicate result the second time
    and does NOT create a second OriginAssetRef."""
    file_store = LocalFileStore(tmp_storage)
    service = UploadService(file_store)

    async with db_session_factory() as db:
        first = await service.process_upload(db, DEV_USER_1, "photo.jpg", JPEG_BYTES)
        assert first.success and not first.is_duplicate

    async with db_session_factory() as db:
        second = await service.process_upload(db, DEV_USER_1, "photo_copy.jpg", JPEG_BYTES)
        assert second.is_duplicate

    async with db_session_factory() as db:
        refs = (await db.execute(
            select(OriginAssetRef).where(
                OriginAssetRef.media_item_id == first.media_item.id
            )
        )).scalars().all()

    assert len(refs) == 1, f"Expected exactly 1 OriginAssetRef, got {len(refs)}"
