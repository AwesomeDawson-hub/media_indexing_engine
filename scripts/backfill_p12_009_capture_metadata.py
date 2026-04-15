"""Backfill source-truth capture metadata for MediaItems uploaded before P12-009.

Processes all media_items where source-truth EXIF fields are NULL, reads the
stored file (storage_mode='full' only), extracts capture datetime and GPS, and
updates the DB in commit batches.  Safe to run multiple times (idempotent: skips
items that already have source_capture_datetime_raw populated).

Usage:
    python -m scripts.backfill_p12_009_capture_metadata [OPTIONS]

Options:
    --dry-run          Print what would be done without modifying the database.
    --batch-size N     Items per DB commit batch (default: 50).
    --stop-after N     Stop after processing N items (useful for staged rollout).
    --user-id ID       Restrict to a single user.

Examples:
    python -m scripts.backfill_p12_009_capture_metadata --dry-run
    python -m scripts.backfill_p12_009_capture_metadata --batch-size 100 --stop-after 500
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session, create_tables
from src.ingestion.metadata_extractor import extract_source_capture_metadata
from src.models import MediaItem
from src.storage.file_store import FileStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_file_store() -> FileStore:
    from src.storage.file_store import LocalFileStore, S3FileStore

    if settings.storage.provider == "s3":
        return S3FileStore(
            bucket=settings.storage.s3_bucket,
            region=settings.storage.s3_region,
            endpoint_url=settings.storage.s3_endpoint_url or None,
        )
    return LocalFileStore(base_path=settings.storage.local_path)


async def backfill(
    dry_run: bool = False,
    batch_size: int = 50,
    stop_after: int | None = None,
    user_id: str | None = None,
) -> None:
    await create_tables()

    file_store = _build_file_store()

    async with async_session() as db:
        # Query: full-storage items with no capture metadata yet
        query = (
            select(MediaItem)
            .where(MediaItem.storage_mode == "full")
            .where(MediaItem.source_capture_datetime_raw.is_(None))
            .where(MediaItem.storage_path.isnot(None))
            .order_by(MediaItem.created_at)
        )
        if user_id:
            query = query.where(MediaItem.user_id == user_id)

        result = await db.execute(query)
        pending: list[MediaItem] = list(result.scalars().all())
        total = len(pending)
        effective_total = min(total, stop_after) if stop_after else total

        logger.info(
            "P12-009 backfill: %d items pending%s (dry_run=%s, batch_size=%d)",
            effective_total,
            f" (capped from {total})" if stop_after and stop_after < total else "",
            dry_run,
            batch_size,
        )

        if dry_run:
            for item in pending[:effective_total]:
                logger.info("  would process: id=%s path=%s mime=%s", item.id, item.storage_path, item.mime_type)
            return

        processed = 0
        updated = 0
        batch: list[MediaItem] = []

        for item in pending[:effective_total]:
            try:
                file_bytes = await file_store.read(item.storage_path)
            except Exception as exc:
                logger.warning("Cannot read file for item id=%s path=%s: %s", item.id, item.storage_path, exc)
                processed += 1
                continue

            capture = extract_source_capture_metadata(file_bytes, item.mime_type or "")

            # Only update if we found at least a raw datetime or GPS
            if capture.capture_datetime_raw or capture.gps_latitude is not None:
                item.source_capture_datetime_utc = capture.capture_datetime_utc
                item.source_capture_datetime_raw = capture.capture_datetime_raw
                item.source_capture_time_offset_minutes = capture.capture_time_offset_minutes
                item.source_gps_latitude = capture.gps_latitude
                item.source_gps_longitude = capture.gps_longitude
                item.source_gps_altitude_meters = capture.gps_altitude_meters
                batch.append(item)
                updated += 1

            processed += 1

            if len(batch) >= batch_size:
                await db.commit()
                logger.info("  committed batch: %d/%d processed, %d updated", processed, effective_total, updated)
                batch = []

        if batch:
            await db.commit()

        logger.info(
            "P12-009 backfill complete: %d processed, %d updated, %d skipped (no EXIF)",
            processed,
            updated,
            processed - updated,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill P12-009 source capture metadata")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without modifying DB")
    parser.add_argument("--batch-size", type=int, default=50, metavar="N", help="DB commit batch size")
    parser.add_argument("--stop-after", type=int, default=None, metavar="N", help="Stop after N items")
    parser.add_argument("--user-id", type=str, default=None, metavar="ID", help="Restrict to one user")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        backfill(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            stop_after=args.stop_after,
            user_id=args.user_id,
        )
    )
