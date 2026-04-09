"""Backfill OriginAssetRef and PreviewAsset rows for pre-P9-003 MediaItems.

For each MediaItem without an OriginAssetRef:
  - Infer provider_type from Source.source_type and SourceConnector.connector_type
  - Find its linked SourceObject (if any) via last_imported_media_item_id
  - Create OriginAssetRef with appropriate field values

For each MediaItem with thumbnail_path but without a PreviewAsset(variant_type='thumbnail'):
  - Create PreviewAsset(variant_type='thumbnail')

This script is idempotent: running it multiple times is safe because both
OriginAssetRef and PreviewAsset have UNIQUE constraints on (media_item_id) and
(media_item_id, variant_type) respectively — duplicate rows are skipped.

Usage:
    python -m scripts.backfill_p9_003_origin_preview [OPTIONS]

Options:
    --dry-run              Count candidates without modifying anything.
    --batch-size N         Items per DB commit batch (default: 100).
    --stop-after N         Stop after processing N items.
    --user-id ID           Restrict to a single user.
    --sleep-seconds S      Sleep S seconds between batches (default: 0).

Examples:
    python -m scripts.backfill_p9_003_origin_preview --dry-run
    python -m scripts.backfill_p9_003_origin_preview --batch-size 50 --sleep-seconds 1
    python -m scripts.backfill_p9_003_origin_preview --user-id <uuid> --stop-after 500
"""

import argparse
import asyncio
import logging
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.database import async_session, create_tables
from src.models import MediaItem, OriginAssetRef, PreviewAsset, Source, SourceConnector, SourceObject

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _infer_provider_type(source: Source | None, connector: SourceConnector | None) -> str:
    """Return the correct provider_type string for a MediaItem given its source context."""
    if connector is not None:
        return connector.connector_type  # 'google_drive' or 's3_compatible'
    if source is not None and source.source_type == "local_folder":
        return "local_folder"
    return "app_upload"


async def backfill(
    dry_run: bool = False,
    batch_size: int = 100,
    stop_after: int | None = None,
    user_id: str | None = None,
    sleep_seconds: float = 0.0,
    _db_factory: Any = None,
) -> dict:
    """Run the backfill.  Returns a counters dict (useful for testing)."""
    if _db_factory is None:
        await create_tables()

    session_factory = _db_factory or async_session

    # -----------------------------------------------------------------------
    # Build candidate query: MediaItems missing an OriginAssetRef
    # -----------------------------------------------------------------------
    missing_origin_query = (
        select(MediaItem)
        .outerjoin(OriginAssetRef, OriginAssetRef.media_item_id == MediaItem.id)
        .where(OriginAssetRef.id.is_(None))
        .order_by(MediaItem.created_at.asc(), MediaItem.id.asc())
    )
    if user_id:
        missing_origin_query = missing_origin_query.where(MediaItem.user_id == user_id)
    if stop_after:
        missing_origin_query = missing_origin_query.limit(stop_after)

    # Preview backfill query: MediaItems with thumbnail_path but no PreviewAsset thumbnail
    missing_preview_query = (
        select(MediaItem)
        .outerjoin(
            PreviewAsset,
            (PreviewAsset.media_item_id == MediaItem.id) & (PreviewAsset.variant_type == "thumbnail"),
        )
        .where(
            MediaItem.thumbnail_path.is_not(None),
            PreviewAsset.id.is_(None),
        )
        .order_by(MediaItem.created_at.asc(), MediaItem.id.asc())
    )
    if user_id:
        missing_preview_query = missing_preview_query.where(MediaItem.user_id == user_id)
    if stop_after:
        missing_preview_query = missing_preview_query.limit(stop_after)

    # -----------------------------------------------------------------------
    # Dry-run mode
    # -----------------------------------------------------------------------
    if dry_run:
        async with session_factory() as db:
            origin_result = await db.execute(missing_origin_query)
            origin_candidates = origin_result.scalars().all()
            preview_result = await db.execute(missing_preview_query)
            preview_candidates = preview_result.scalars().all()

        logger.info(
            "[DRY-RUN] %d items missing OriginAssetRef; %d items missing PreviewAsset thumbnail",
            len(origin_candidates),
            len(preview_candidates),
        )
        for item in origin_candidates[:20]:
            logger.info("[DRY-RUN]  origin candidate id=%s user_id=%s source_id=%s", item.id, item.user_id, item.source_id)
        return {
            "dry_run": True,
            "origin_backfilled": 0,
            "preview_backfilled": 0,
            "origin_skipped_integrity": 0,
            "preview_skipped_integrity": 0,
            "failed": 0,
            "origin_candidates": len(origin_candidates),
            "preview_candidates": len(preview_candidates),
        }

    # -----------------------------------------------------------------------
    # Live run — Phase 1: OriginAssetRef backfill
    # -----------------------------------------------------------------------
    origin_backfilled = 0
    origin_skipped_integrity = 0
    failed = 0

    async with session_factory() as db:
        origin_result = await db.execute(missing_origin_query)
        items = origin_result.scalars().all()

        logger.info("Phase 1: %d MediaItems need OriginAssetRef", len(items))

        for idx, item in enumerate(items):
            try:
                # Load Source and SourceConnector for this item
                source: Source | None = None
                connector: SourceConnector | None = None

                if item.source_id:
                    src_result = await db.execute(
                        select(Source).where(Source.id == item.source_id)
                    )
                    source = src_result.scalar_one_or_none()

                    if source is not None:
                        conn_result = await db.execute(
                            select(SourceConnector).where(
                                SourceConnector.source_id == source.id,
                                SourceConnector.user_id == item.user_id,
                            )
                        )
                        connector = conn_result.scalar_one_or_none()

                provider_type = _infer_provider_type(source, connector)

                # Find linked SourceObject (connector-backed items only)
                source_object: SourceObject | None = None
                if connector is not None:
                    so_result = await db.execute(
                        select(SourceObject).where(
                            SourceObject.last_imported_media_item_id == item.id
                        )
                    )
                    source_object = so_result.scalar_one_or_none()

                # Determine provider_object_id and app_storage_path
                provider_object_id: str | None = None
                revision_marker: str | None = None
                app_storage_path: str | None = None
                local_file_fingerprint: str | None = None

                if source_object is not None:
                    provider_object_id = source_object.external_object_key
                    revision_marker = source_object.external_version

                if provider_type == "app_upload":
                    app_storage_path = item.storage_path
                elif provider_type == "local_folder":
                    local_file_fingerprint = item.source_file_fingerprint

                origin_ref = OriginAssetRef(
                    media_item_id=item.id,
                    user_id=item.user_id,
                    source_id=item.source_id,
                    source_object_id=source_object.id if source_object else None,
                    provider_type=provider_type,
                    provider_object_id=provider_object_id,
                    locator_snapshot=provider_object_id,
                    revision_marker=revision_marker,
                    app_storage_path=app_storage_path,
                    local_file_fingerprint=local_file_fingerprint,
                )
                db.add(origin_ref)

                if (idx + 1) % batch_size == 0:
                    try:
                        await db.commit()
                        logger.info("  Committed batch up to item %d (origin_backfilled so far: %d)", idx + 1, origin_backfilled + (idx % batch_size) + 1)
                    except IntegrityError:
                        await db.rollback()
                        origin_skipped_integrity += batch_size
                        logger.warning("  IntegrityError in batch ending at item %d — skipping batch", idx + 1)
                        continue
                    origin_backfilled += batch_size

                if sleep_seconds > 0 and (idx + 1) % batch_size == 0:
                    await asyncio.sleep(sleep_seconds)

            except Exception as exc:
                logger.warning("Failed to process item %s for OriginAssetRef: %s", item.id, exc)
                failed += 1

        # Flush any remaining items (partial last batch)
        remainder = len(items) % batch_size
        if remainder > 0:
            try:
                await db.commit()
                origin_backfilled += remainder
                logger.info("Committed final partial batch (%d items)", remainder)
            except IntegrityError:
                await db.rollback()
                origin_skipped_integrity += remainder
                logger.warning("IntegrityError flushing final partial batch — skipping")

    logger.info("Phase 1 complete: %d OriginAssetRef rows created, %d skipped (integrity), %d failed", origin_backfilled, origin_skipped_integrity, failed)

    # -----------------------------------------------------------------------
    # Live run — Phase 2: PreviewAsset backfill
    # -----------------------------------------------------------------------
    preview_backfilled = 0
    preview_skipped_integrity = 0

    async with session_factory() as db:
        preview_result = await db.execute(missing_preview_query)
        preview_items = preview_result.scalars().all()

        logger.info("Phase 2: %d MediaItems need PreviewAsset thumbnail", len(preview_items))

        for idx, item in enumerate(preview_items):
            try:
                db.add(PreviewAsset(
                    media_item_id=item.id,
                    user_id=item.user_id,
                    variant_type="thumbnail",
                    storage_path=item.thumbnail_path,
                    mime_type="image/jpeg",
                ))

                if (idx + 1) % batch_size == 0:
                    try:
                        await db.commit()
                        preview_backfilled += batch_size
                        logger.info("  Committed preview batch up to item %d", idx + 1)
                    except IntegrityError:
                        await db.rollback()
                        preview_skipped_integrity += batch_size
                        logger.warning("  IntegrityError in preview batch ending at item %d — skipping", idx + 1)

                    if sleep_seconds > 0:
                        await asyncio.sleep(sleep_seconds)

            except Exception as exc:
                logger.warning("Failed to process item %s for PreviewAsset: %s", item.id, exc)
                failed += 1

        remainder = len(preview_items) % batch_size
        if remainder > 0:
            try:
                await db.commit()
                preview_backfilled += remainder
                logger.info("Committed final preview partial batch (%d items)", remainder)
            except IntegrityError:
                await db.rollback()
                preview_skipped_integrity += remainder
                logger.warning("IntegrityError flushing final preview partial batch — skipping")

    logger.info(
        "Phase 2 complete: %d PreviewAsset rows created, %d skipped (integrity)",
        preview_backfilled,
        preview_skipped_integrity,
    )

    return {
        "dry_run": False,
        "origin_backfilled": origin_backfilled,
        "preview_backfilled": preview_backfilled,
        "origin_skipped_integrity": origin_skipped_integrity,
        "preview_skipped_integrity": preview_skipped_integrity,
        "failed": failed,
        "origin_candidates": len(items),
        "preview_candidates": len(preview_items),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Count candidates without modifying anything")
    parser.add_argument("--batch-size", type=int, default=100, metavar="N", help="Items per DB commit batch (default: 100)")
    parser.add_argument("--stop-after", type=int, default=None, metavar="N", help="Stop after processing N items per phase")
    parser.add_argument("--user-id", type=str, default=None, metavar="ID", help="Restrict to a single user")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, metavar="S", help="Sleep S seconds between batches (default: 0)")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    counters = await backfill(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        stop_after=args.stop_after,
        user_id=args.user_id,
        sleep_seconds=args.sleep_seconds,
    )
    logger.info("Done: %s", counters)
    if counters.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
