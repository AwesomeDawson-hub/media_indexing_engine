"""Migrate historical connector-backed MediaItems from full → preview_only storage.

Targets items that were ingested before P8-002 and are still in `storage_mode='full'`
despite being backed by a connector (where the original file source remains accessible).

For each eligible item:
  1. If `thumbnail_path` is NULL, read the original file and generate + save a thumbnail.
  2. Call `_attempt_preview_pivot()` — the canonical live-path function — to perform
     the actual transition (file deletion + `storage_mode='preview_only'`).

Idempotency: already-pivoted items and items with missing originals are skipped silently.

Usage:
    python -m scripts.migrate_historical_preview_only [OPTIONS]

Options:
    --dry-run              Count candidates without modifying anything.
    --batch-size N         Items per DB commit batch (default: 50).
    --stop-after N         Stop after processing N items.
    --user-id ID           Restrict to a single user.
    --source-id ID         Restrict to a single source.
    --sleep-seconds S      Sleep S seconds between batches (default: 0).

Examples:
    python -m scripts.migrate_historical_preview_only --dry-run
    python -m scripts.migrate_historical_preview_only --batch-size 25 --sleep-seconds 2
    python -m scripts.migrate_historical_preview_only --source-id <uuid> --stop-after 100
"""

import argparse
import asyncio
import logging
import sys
from typing import Any

from sqlalchemy import select

from src.analysis.processor import _attempt_preview_pivot
from src.config import settings
from src.database import async_session, create_tables
from src.ingestion.upload_service import _generate_thumbnail
from src.models import MediaItem, Source, SourceConnector
from src.storage.file_store import FileStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_file_store() -> FileStore:
    from src.storage.file_store import LocalFileStore, S3FileStore

    if settings.storage.provider == "s3":
        return S3FileStore(
            bucket=settings.storage.s3_bucket,
            region=settings.storage.s3_region,
            endpoint_url=settings.storage.s3_endpoint_url or "",
        )
    return LocalFileStore(settings.storage.local_path)


def _build_candidate_query(user_id: str | None, source_id: str | None):
    """Return a query for connector-backed full-mode items with non-null storage_path."""
    query = (
        select(MediaItem)
        .join(Source, MediaItem.source_id == Source.id)
        .join(SourceConnector, SourceConnector.source_id == Source.id)
        .where(
            MediaItem.storage_mode == "full",
            MediaItem.storage_path.is_not(None),
            MediaItem.source_id.is_not(None),
        )
        .order_by(MediaItem.created_at.asc(), MediaItem.id.asc())
    )
    if user_id:
        query = query.where(MediaItem.user_id == user_id)
    if source_id:
        query = query.where(MediaItem.source_id == source_id)
    return query


async def migrate(
    dry_run: bool = False,
    batch_size: int = 50,
    stop_after: int | None = None,
    user_id: str | None = None,
    source_id: str | None = None,
    sleep_seconds: float = 0.0,
    _db_factory: Any = None,
    _file_store: FileStore | None = None,
) -> dict:
    """Run the migration.  Returns a counters dict (useful for testing).

    The optional ``_db_factory`` and ``_file_store`` parameters allow tests to
    inject a scoped session factory and an in-memory file store without patching
    module globals.
    """
    if _db_factory is None:
        await create_tables()

    session_factory = _db_factory or async_session
    file_store = _file_store or build_file_store()

    # ------------------------------------------------------------------
    # Dry-run: count and log candidates without any mutations
    # ------------------------------------------------------------------
    if dry_run:
        async with session_factory() as db:
            count_query = _build_candidate_query(user_id, source_id)
            result = await db.execute(count_query)
            candidates = result.scalars().all()

        total = len(candidates)
        effective_total = min(total, stop_after) if stop_after else total
        logger.info(
            "[DRY-RUN] Found %d candidate items (stop_after=%s, effective=%d)",
            total,
            stop_after,
            effective_total,
        )
        for item in candidates[:effective_total]:
            logger.info(
                "[DRY-RUN]  id=%s user_id=%s source_id=%s thumbnail=%s",
                item.id,
                item.user_id,
                item.source_id,
                "present" if item.thumbnail_path else "MISSING",
            )
        return {
            "dry_run": True,
            "scanned": 0,
            "candidates": effective_total,
            "migrated": 0,
            "thumbnail_backfilled": 0,
            "skipped_already_preview_only": 0,
            "skipped_missing_original": 0,
            "failed_thumbnail_backfill": 0,
            "failed_other": 0,
        }

    # ------------------------------------------------------------------
    # Live run
    # ------------------------------------------------------------------
    scanned = 0
    migrated = 0
    thumbnail_backfilled = 0
    skipped_already_preview_only = 0
    skipped_missing_original = 0
    failed_thumbnail_backfill = 0
    failed_other = 0
    batch_migrated = 0  # Tracks items migrated within the current sleep window

    async with session_factory() as db:
        query = _build_candidate_query(user_id, source_id)
        if stop_after:
            query = query.limit(stop_after)

        result = await db.execute(query)
        items = result.scalars().all()

        logger.info(
            "Starting migration: %d candidates (batch_size=%d, stop_after=%s, sleep=%.1fs)",
            len(items),
            batch_size,
            stop_after,
            sleep_seconds,
        )

        for item in items:
            scanned += 1

            # Hard idempotency guard — shouldn't match the query, but be defensive
            if item.storage_mode == "preview_only":
                skipped_already_preview_only += 1
                continue

            # ----------------------------------------------------------
            # Thumbnail backfill phase (only when thumbnail is absent)
            # ----------------------------------------------------------
            if item.thumbnail_path is None:
                try:
                    file_bytes = await file_store.read(item.storage_path)
                except Exception as exc:
                    logger.warning(
                        "Cannot read original for thumbnail backfill id=%s: %s — skipping",
                        item.id,
                        exc,
                    )
                    skipped_missing_original += 1
                    continue

                try:
                    thumb_bytes = _generate_thumbnail(file_bytes)
                    thumbnail_path = await file_store.save_thumbnail(
                        item.user_id, item.content_hash, thumb_bytes
                    )
                    item.thumbnail_path = thumbnail_path
                    await db.commit()
                    thumbnail_backfilled += 1
                    logger.debug("Backfilled thumbnail for id=%s", item.id)
                except Exception as exc:
                    logger.warning(
                        "Thumbnail backfill failed for id=%s: %s — leaving full, skipping pivot",
                        item.id,
                        exc,
                    )
                    failed_thumbnail_backfill += 1
                    continue

            # ----------------------------------------------------------
            # Pivot phase — canonical function; handles eligibility + commit
            # ----------------------------------------------------------
            try:
                await _attempt_preview_pivot(db, item, file_store)
            except Exception as exc:
                logger.warning("Unexpected error pivoting id=%s: %s", item.id, exc)
                failed_other += 1
                continue

            if item.storage_mode == "preview_only":
                migrated += 1
                batch_migrated += 1
                logger.debug("Pivoted id=%s to preview_only", item.id)
            else:
                # _attempt_preview_pivot decided item is ineligible (legitimate skip)
                logger.debug(
                    "Skipped (ineligible after pivot check) id=%s storage_mode=%s",
                    item.id,
                    item.storage_mode,
                )

            # Throttle: sleep between each completed batch of `batch_size` migrations
            if sleep_seconds > 0 and batch_migrated > 0 and batch_migrated % batch_size == 0:
                logger.info(
                    "Batch complete (migrated=%d so far) — sleeping %.1fs",
                    migrated,
                    sleep_seconds,
                )
                await asyncio.sleep(sleep_seconds)

        # Periodic progress log every batch_size scanned items
        if scanned % batch_size == 0 or scanned == len(items):
            logger.info(
                "Progress: scanned=%d migrated=%d thumbnail_backfilled=%d failed=%d",
                scanned,
                migrated,
                thumbnail_backfilled,
                failed_thumbnail_backfill + failed_other,
            )

    stats = {
        "dry_run": False,
        "scanned": scanned,
        "candidates": scanned,
        "migrated": migrated,
        "thumbnail_backfilled": thumbnail_backfilled,
        "skipped_already_preview_only": skipped_already_preview_only,
        "skipped_missing_original": skipped_missing_original,
        "failed_thumbnail_backfill": failed_thumbnail_backfill,
        "failed_other": failed_other,
    }

    logger.info(
        "Migration complete: scanned=%d migrated=%d thumbnail_backfilled=%d "
        "skipped_already_preview_only=%d skipped_missing_original=%d "
        "failed_thumbnail_backfill=%d failed_other=%d",
        scanned,
        migrated,
        thumbnail_backfilled,
        skipped_already_preview_only,
        skipped_missing_original,
        failed_thumbnail_backfill,
        failed_other,
    )

    if failed_thumbnail_backfill + failed_other > 0:
        logger.warning("Some items failed — re-run to retry eligible items.")
        sys.exit(1)

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidates without modifying the database",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        metavar="N",
        help="Items per sleep window (default: 50)",
    )
    parser.add_argument(
        "--stop-after",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N items",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        metavar="ID",
        help="Restrict to a specific user ID",
    )
    parser.add_argument(
        "--source-id",
        default=None,
        metavar="ID",
        help="Restrict to a specific source ID",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        metavar="S",
        help="Sleep S seconds between batches (default: 0)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        migrate(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            stop_after=args.stop_after,
            user_id=args.user_id,
            source_id=args.source_id,
            sleep_seconds=args.sleep_seconds,
        )
    )
