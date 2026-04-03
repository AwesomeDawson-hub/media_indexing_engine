"""Backfill perceptual hashes for media items that were uploaded before P5-001.

Processes all media items whose `perceptual_hash` column is NULL, computing
pHash from the stored file and updating the DB in batches.  Safe to run
multiple times (idempotent: skips items that already have a hash).

Usage:
    python -m scripts.backfill_phash [OPTIONS]

Options:
    --dry-run          Print what would be done without modifying the database.
    --batch-size N     Items per DB commit batch (default: 50).
    --stop-after N     Stop after processing N items (useful for staged rollout).
    --user-id ID       Restrict to a single user.

Examples:
    python -m scripts.backfill_phash --dry-run
    python -m scripts.backfill_phash --batch-size 100 --stop-after 500
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.curation.phash_service import compute_phash, PHASH_VERSION, phash_timestamp
from src.database import async_session, create_tables
from src.models import MediaItem
from src.storage.file_store import FileStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_file_store() -> FileStore:
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

    file_store = build_file_store()

    async with async_session() as db:
        # Count total work first
        count_query = select(MediaItem).where(MediaItem.perceptual_hash.is_(None))
        if user_id:
            count_query = count_query.where(MediaItem.user_id == user_id)
        result = await db.execute(count_query)
        pending = result.scalars().all()
        total = len(pending)
        effective_total = min(total, stop_after) if stop_after else total

        if dry_run:
            logger.info("[DRY-RUN] Would process %d items (stop_after=%s)", effective_total, stop_after)
            for item in pending[:effective_total]:
                logger.info("[DRY-RUN]  would hash id=%s mime=%s", item.id, item.mime_type)
            return

        logger.info("Starting pHash backfill: %d items to process (batch_size=%d)", effective_total, batch_size)

    processed = skipped = failed = 0

    async with async_session() as db:
        query = (
            select(MediaItem)
            .where(MediaItem.perceptual_hash.is_(None))
            .order_by(MediaItem.created_at.asc())
        )
        if user_id:
            query = query.where(MediaItem.user_id == user_id)
        if stop_after:
            query = query.limit(stop_after)

        result = await db.execute(query)
        items = result.scalars().all()

        batch: list[MediaItem] = []

        for item in items:
            try:
                file_bytes = await file_store.read(item.storage_path)
                phash = compute_phash(file_bytes, item.mime_type)
            except Exception as exc:
                logger.warning("Could not read/hash id=%s: %s", item.id, exc)
                failed += 1
                continue

            if phash is None:
                # Unsupported MIME type (e.g. GIF) — intentional null; skip permanently
                logger.debug("Skipping id=%s mime=%s (unsupported for pHash)", item.id, item.mime_type)
                skipped += 1
                continue

            item.perceptual_hash = phash
            item.phash_version = PHASH_VERSION
            item.phash_computed_at = phash_timestamp()
            batch.append(item)
            processed += 1

            if len(batch) >= batch_size:
                await db.commit()
                logger.info("Committed batch of %d (total processed=%d)", len(batch), processed)
                batch = []

        # Final partial batch
        if batch:
            await db.commit()
            logger.info("Committed final batch of %d", len(batch))

    logger.info(
        "Backfill complete: processed=%d skipped=%d failed=%d",
        processed,
        skipped,
        failed,
    )

    if failed:
        logger.warning("%d items failed — re-run to retry.", failed)
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print plan without modifying the database")
    parser.add_argument("--batch-size", type=int, default=50, metavar="N", help="Items per DB commit (default: 50)")
    parser.add_argument("--stop-after", type=int, default=None, metavar="N", help="Process at most N items")
    parser.add_argument("--user-id", default=None, metavar="ID", help="Restrict to a specific user ID")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        backfill(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            stop_after=args.stop_after,
            user_id=args.user_id,
        )
    )
