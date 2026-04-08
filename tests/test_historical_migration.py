"""Integration tests for P8-003: Historical Connector Preview-Only Migration.

Coverage:
  1. Dry-run reports candidates without mutating any rows
  2. Already-preview_only items are skipped idempotently
  3. Items with storage_path=None are excluded from candidates
  4. Manual __uploads__ items are skipped (ineligible after pivot check)
  5. Connector item with SourceObject + existing thumbnail → pivots to preview_only
  6. Connector item with no thumbnail → backfills thumbnail then pivots
  7. Thumbnail generation failure → leaves full, no pivot, failed_thumbnail_backfill += 1
  8. Thumbnail save failure → leaves full, state consistent
  9. Idempotency: second run skips already-pivoted items, migrated=0
  10. Live-path parity: _attempt_preview_pivot is called (not custom delete logic)
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from cryptography.fernet import Fernet
from sqlalchemy import select

from src.models import MediaItem, Source, SourceConnector, SourceObject
from src.storage.file_store import LocalFileStore
from scripts.migrate_historical_preview_only import migrate
from tests.conftest import JPEG_BYTES, DEV_USER_1, DEV_USER_2

_TEST_FERNET_KEY: str = Fernet.generate_key().decode("utf-8")

# Counter used to generate unique content hashes per item within a test
_item_counter = 0


def _unique_hash(prefix: str = "abc") -> str:
    global _item_counter
    _item_counter += 1
    return f"{prefix}{_item_counter:016x}"


# ---------------------------------------------------------------------------
# Helpers (mirror test_preview_pivot.py helpers)
# ---------------------------------------------------------------------------

async def _make_source(db, user_id: str, name: str, source_type: str = "manual") -> Source:
    source = Source(user_id=user_id, name=name, source_type=source_type)
    db.add(source)
    await db.flush()
    return source


async def _make_connector_source(
    db, user_id: str, name: str = "S3 Source"
) -> tuple[Source, SourceConnector]:
    from src.connectors.secrets import encrypt_credentials
    import src.config as cfg_mod

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
            credentials_encrypted=encrypt_credentials(
                {"access_key_id": "K", "secret_access_key": "S"}
            ),
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
    save_file: bool = True,
) -> MediaItem:
    """Create a MediaItem with a real file on disk."""
    content_hash = _unique_hash("cafe")
    if save_file and storage_mode == "full":
        storage_path: str | None = await file_store.save(
            user_id, content_hash, "photo.jpg", JPEG_BYTES
        )
    else:
        storage_path = None

    if thumbnail_path and thumbnail_path.startswith("thumbnails/"):
        thumbnail_path = await file_store.save_thumbnail(user_id, content_hash, JPEG_BYTES)

    item = MediaItem(
        user_id=user_id,
        content_hash=content_hash,
        original_filename="photo.jpg",
        file_size=len(JPEG_BYTES),
        mime_type="image/jpeg",
        storage_path=storage_path,
        storage_mode=storage_mode,
        thumbnail_path=thumbnail_path,
        status="completed",
        source_id=source_id,
    )
    db.add(item)
    await db.flush()
    return item


_so_counter = 0


async def _make_source_object(
    db, source_id: str, user_id: str, media_item_id: str
) -> SourceObject:
    global _so_counter
    _so_counter += 1
    from datetime import datetime, timezone

    so = SourceObject(
        source_id=source_id,
        user_id=user_id,
        external_object_key=f"images/photo_{_so_counter}.jpg",
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
# 1. Dry-run reports candidates without mutation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_counts_candidates_no_mutation(
    db_session_factory, seed_users, tmp_storage
):
    """Dry-run returns a positive candidate count and leaves all items as full."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item1 = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        item2 = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        await _make_source_object(db, source.id, DEV_USER_1, item1.id)
        await _make_source_object(db, source.id, DEV_USER_1, item2.id)
        await db.commit()
        item1_id, item2_id = item1.id, item2.id

    stats = await migrate(
        dry_run=True,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    assert stats["dry_run"] is True
    assert stats["candidates"] == 2
    assert stats["migrated"] == 0

    # No rows mutated
    async with db_session_factory() as db:
        for item_id in (item1_id, item2_id):
            result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
            item = result.scalar_one()
            assert item.storage_mode == "full"
            assert item.storage_path is not None


# ---------------------------------------------------------------------------
# 2. Already-preview_only items skipped idempotently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_already_preview_only_skipped(db_session_factory, seed_users, tmp_storage):
    """Items already in preview_only mode are not touched (skipped_already_preview_only += 1)."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        # Manually create a preview_only item — won't appear in candidate query
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, storage_mode="preview_only"
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

    stats = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    # preview_only item is filtered out at query level — scanned == 0
    assert stats["scanned"] == 0
    assert stats["migrated"] == 0


# ---------------------------------------------------------------------------
# 3. Items with storage_path=None excluded from candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_storage_path_excluded(db_session_factory, seed_users, tmp_storage):
    """Items with storage_path=None are excluded by the candidate query."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        # Force storage_path to None while storage_mode stays full (edge case)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, save_file=False
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

    stats = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    assert stats["scanned"] == 0
    assert stats["migrated"] == 0


# ---------------------------------------------------------------------------
# 4. __uploads__ items are skipped by _attempt_preview_pivot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_uploads_source_skipped(db_session_factory, seed_users, tmp_storage):
    """Items from the __uploads__ source pass the candidate query but are rejected by pivot."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        # __uploads__ source with a SourceConnector attached (hypothetical edge case)
        source = await _make_source(db, DEV_USER_1, "__uploads__", source_type="s3_compatible")
        import src.config as cfg_mod
        from src.connectors.secrets import encrypt_credentials
        original_key = cfg_mod.settings.connector.credentials_key
        cfg_mod.settings.connector.credentials_key = _TEST_FERNET_KEY
        try:
            sc = SourceConnector(
                source_id=source.id,
                user_id=DEV_USER_1,
                connector_type="s3_compatible",
                remote_container_id="bucket",
                region="us-east-1",
                credentials_encrypted=encrypt_credentials(
                    {"access_key_id": "K", "secret_access_key": "S"}
                ),
            )
            db.add(sc)
            await db.flush()
        finally:
            cfg_mod.settings.connector.credentials_key = original_key

        item = await _make_media_item(db, DEV_USER_1, source.id, file_store)
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()
        item_id = item.id

    stats = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    # Item is scanned but not migrated — __uploads__ is ineligible
    assert stats["scanned"] == 1
    assert stats["migrated"] == 0

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
    assert item.storage_mode == "full"
    assert item.storage_path is not None


# ---------------------------------------------------------------------------
# 5. Connector item with existing thumbnail → pivots to preview_only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_item_with_thumbnail_pivots(
    db_session_factory, seed_users, tmp_storage
):
    """Eligible connector item that already has a thumbnail transitions to preview_only."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        # thumbnail_path starts with "thumbnails/" → real thumbnail is saved
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, thumbnail_path="thumbnails/"
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()
        item_id = item.id

    stats = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    assert stats["migrated"] == 1
    assert stats["thumbnail_backfilled"] == 0
    assert stats["failed_thumbnail_backfill"] == 0

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
    assert item.storage_mode == "preview_only"
    assert item.storage_path is None


# ---------------------------------------------------------------------------
# 6. Connector item with no thumbnail → backfills thumbnail then pivots
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connector_item_no_thumbnail_backfills_then_pivots(
    db_session_factory, seed_users, tmp_storage
):
    """Item without a thumbnail has its thumbnail generated before the pivot."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, thumbnail_path=None
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()
        item_id = item.id

    stats = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    assert stats["thumbnail_backfilled"] == 1
    assert stats["migrated"] == 1
    assert stats["failed_thumbnail_backfill"] == 0

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
    assert item.storage_mode == "preview_only"
    assert item.storage_path is None
    assert item.thumbnail_path is not None


# ---------------------------------------------------------------------------
# 7. Thumbnail generation failure → leaves full, no pivot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thumbnail_generation_failure_leaves_full(
    db_session_factory, seed_users, tmp_storage
):
    """When _generate_thumbnail raises, the item stays full and is counted as failed."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, thumbnail_path=None
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()
        item_id, original_path = item.id, item.storage_path

    with patch(
        "scripts.migrate_historical_preview_only._generate_thumbnail",
        side_effect=ValueError("corrupted image"),
    ):
        with pytest.raises(SystemExit):
            await migrate(
                dry_run=False,
                _db_factory=db_session_factory,
                _file_store=file_store,
            )

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
    assert item.storage_mode == "full"
    assert item.storage_path == original_path
    assert item.thumbnail_path is None


# ---------------------------------------------------------------------------
# 8. Thumbnail save failure → leaves full, state consistent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thumbnail_save_failure_leaves_full(
    db_session_factory, seed_users, tmp_storage
):
    """When save_thumbnail raises, the item stays full and thumbnail_path remains None."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, thumbnail_path=None
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()
        item_id, original_path = item.id, item.storage_path

    with patch.object(
        file_store, "save_thumbnail", new_callable=AsyncMock, side_effect=OSError("disk full")
    ):
        with pytest.raises(SystemExit):
            await migrate(
                dry_run=False,
                _db_factory=db_session_factory,
                _file_store=file_store,
            )

    async with db_session_factory() as db:
        result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
        item = result.scalar_one()
    assert item.storage_mode == "full"
    assert item.storage_path == original_path
    assert item.thumbnail_path is None


# ---------------------------------------------------------------------------
# 9. Idempotency: second run skips already-pivoted items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotency_second_run_skips_pivoted(
    db_session_factory, seed_users, tmp_storage
):
    """Running the migration twice produces migrated=0 on the second run."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, thumbnail_path="thumbnails/"
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

    # First run
    stats1 = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )
    assert stats1["migrated"] == 1

    # Second run — item is preview_only, excluded by candidate query
    stats2 = await migrate(
        dry_run=False,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )
    assert stats2["migrated"] == 0
    assert stats2["scanned"] == 0


# ---------------------------------------------------------------------------
# 10. Live-path parity: _attempt_preview_pivot is called for pivot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_uses_attempt_preview_pivot_for_pivot(
    db_session_factory, seed_users, tmp_storage
):
    """The migration must delegate to _attempt_preview_pivot — not perform its own deletion."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        item = await _make_media_item(
            db, DEV_USER_1, source.id, file_store, thumbnail_path="thumbnails/"
        )
        await _make_source_object(db, source.id, DEV_USER_1, item.id)
        await db.commit()

    pivot_calls = []

    original_pivot = None

    async def _spy_pivot(db, media_item, fs):
        pivot_calls.append(media_item.id)
        await original_pivot(db, media_item, fs)

    import scripts.migrate_historical_preview_only as mig_mod
    from src.analysis.processor import _attempt_preview_pivot as real_pivot

    original_pivot = real_pivot

    with patch.object(mig_mod, "_attempt_preview_pivot", side_effect=_spy_pivot):
        stats = await migrate(
            dry_run=False,
            _db_factory=db_session_factory,
            _file_store=file_store,
        )

    assert len(pivot_calls) == 1, "Expected exactly one call to _attempt_preview_pivot"
    assert stats["migrated"] == 1


# ---------------------------------------------------------------------------
# 11. stop_after limits candidates processed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_after_limits_processing(db_session_factory, seed_users, tmp_storage):
    """--stop-after N processes at most N candidates."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source, _sc = await _make_connector_source(db, DEV_USER_1)
        items = []
        for i in range(4):
            item = await _make_media_item(
                db, DEV_USER_1, source.id, file_store, thumbnail_path="thumbnails/"
            )
            await _make_source_object(db, source.id, DEV_USER_1, item.id)
            items.append(item)
        await db.commit()

    stats = await migrate(
        dry_run=False,
        stop_after=2,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    assert stats["scanned"] == 2
    assert stats["migrated"] == 2


# ---------------------------------------------------------------------------
# 12. user-id and source-id filters restrict candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_id_filter_restricts_candidates(
    db_session_factory, seed_users, tmp_storage
):
    """--user-id restricts migration to that user's items only."""
    file_store = LocalFileStore(tmp_storage)

    async with db_session_factory() as db:
        source1, _sc1 = await _make_connector_source(db, DEV_USER_1, name="Source U1")
        source2, _sc2 = await _make_connector_source(db, DEV_USER_2, name="Source U2")

        item1 = await _make_media_item(
            db, DEV_USER_1, source1.id, file_store, thumbnail_path="thumbnails/"
        )
        item2 = await _make_media_item(
            db, DEV_USER_2, source2.id, file_store, thumbnail_path="thumbnails/"
        )
        await _make_source_object(db, source1.id, DEV_USER_1, item1.id)
        await _make_source_object(db, source2.id, DEV_USER_2, item2.id)
        await db.commit()
        item1_id, item2_id = item1.id, item2.id

    stats = await migrate(
        dry_run=False,
        user_id=DEV_USER_1,
        _db_factory=db_session_factory,
        _file_store=file_store,
    )

    assert stats["migrated"] == 1

    async with db_session_factory() as db:
        r1 = await db.execute(select(MediaItem).where(MediaItem.id == item1_id))
        r2 = await db.execute(select(MediaItem).where(MediaItem.id == item2_id))
        m1 = r1.scalar_one()
        m2 = r2.scalar_one()

    assert m1.storage_mode == "preview_only"
    assert m2.storage_mode == "full"  # DEV_USER_2 item untouched
