"""Backfill SourceCapabilitySnapshot and WriteBackOperation rows for P9-004.

Usage:
    python -m scripts.backfill_p9_004_capabilities_writeback [OPTIONS]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from src.analysis.writeback_operation_service import bootstrap_writeback_operation_from_mirror
from src.auth.google_drive_oauth import scope_has_write
from src.database import async_session, create_tables
from src.models import MediaItem, OriginAssetRef, SourceCapabilitySnapshot, SourceConnector, SourceMutationHistory, WriteBackOperation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _scope_tier(granted_scopes: str | None) -> str:
    if not granted_scopes:
        return "unknown"
    return "writable" if scope_has_write(granted_scopes) else "read_only"


async def _history_count(db, media_item_id: str, operation_type: str) -> int:
    result = await db.execute(
        select(func.count(SourceMutationHistory.id)).where(
            SourceMutationHistory.media_item_id == media_item_id,
            SourceMutationHistory.operation_type == operation_type,
        )
    )
    return int(result.scalar_one() or 0)


async def _latest_history_filename(db, media_item_id: str, operation_type: str) -> str | None:
    result = await db.execute(
        select(SourceMutationHistory.new_filename)
        .where(
            SourceMutationHistory.media_item_id == media_item_id,
            SourceMutationHistory.operation_type == operation_type,
            SourceMutationHistory.new_filename.is_not(None),
        )
        .order_by(SourceMutationHistory.attempted_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def backfill(
    dry_run: bool = False,
    batch_size: int = 100,
    stop_after: int | None = None,
    user_id: str | None = None,
    source_id: str | None = None,
    sleep_seconds: float = 0.0,
    _db_factory: Any = None,
) -> dict:
    if _db_factory is None:
        await create_tables()
    session_factory = _db_factory or async_session

    capability_query = (
        select(SourceConnector)
        .outerjoin(
            SourceCapabilitySnapshot,
            SourceCapabilitySnapshot.source_connector_id == SourceConnector.id,
        )
        .where(
            SourceConnector.connector_type == "google_drive",
            SourceCapabilitySnapshot.id.is_(None),
        )
        .order_by(SourceConnector.created_at.asc(), SourceConnector.id.asc())
    )
    writeback_query = (
        select(MediaItem)
        .join(OriginAssetRef, OriginAssetRef.media_item_id == MediaItem.id)
        .outerjoin(
            WriteBackOperation,
            (WriteBackOperation.media_item_id == MediaItem.id)
            & (WriteBackOperation.operation_type == "rename"),
        )
        .where(
            MediaItem.mutation_state.is_not(None),
            WriteBackOperation.id.is_(None),
        )
        .order_by(MediaItem.created_at.asc(), MediaItem.id.asc())
    )

    if user_id:
        capability_query = capability_query.where(SourceConnector.user_id == user_id)
        writeback_query = writeback_query.where(MediaItem.user_id == user_id)
    if source_id:
        capability_query = capability_query.where(SourceConnector.source_id == source_id)
        writeback_query = writeback_query.where(MediaItem.source_id == source_id)
    if stop_after:
        capability_query = capability_query.limit(stop_after)
        writeback_query = writeback_query.limit(stop_after)

    if dry_run:
        async with session_factory() as db:
            capability_candidates = (await db.execute(capability_query)).scalars().all()
            writeback_candidates = (await db.execute(writeback_query)).scalars().all()
        return {
            "dry_run": True,
            "capability_candidates": len(capability_candidates),
            "writeback_candidates": len(writeback_candidates),
            "capability_backfilled": 0,
            "writeback_backfilled": 0,
            "metadata_write_backfilled": 0,
            "failed": 0,
        }

    capability_backfilled = 0
    writeback_backfilled = 0
    metadata_write_backfilled = 0
    failed = 0

    async with session_factory() as db:
        connectors = (await db.execute(capability_query)).scalars().all()
        for idx, connector in enumerate(connectors, start=1):
            has_auth = bool(connector.credentials_encrypted and not connector.last_validation_error)
            db.add(SourceCapabilitySnapshot(
                source_id=connector.source_id,
                source_connector_id=connector.id,
                user_id=connector.user_id,
                provider_type="google_drive",
                can_read=has_auth,
                can_write=scope_has_write(connector.granted_scopes) and has_auth,
                can_refetch=has_auth,
                scope_text=connector.granted_scopes,
                scope_tier=_scope_tier(connector.granted_scopes),
                verification_state="current" if has_auth else "error",
                last_verified_at=datetime.now(timezone.utc),
                last_error_code=None if has_auth else "connector_unavailable",
                last_error_message=None if has_auth else "Connector state is not healthy enough to verify capability.",
            ))
            if idx % batch_size == 0:
                await db.commit()
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
        if connectors:
            await db.commit()
        capability_backfilled = len(connectors)

    async with session_factory() as db:
        items = (await db.execute(writeback_query)).scalars().all()
        for idx, item in enumerate(items, start=1):
            try:
                rename_operation = await bootstrap_writeback_operation_from_mirror(
                    db,
                    media_item=item,
                    operation_type="rename",
                )
                if rename_operation is not None:
                    rename_operation.requested_filename = await _latest_history_filename(db, item.id, "rename")
                    rename_operation.attempt_count = await _history_count(db, item.id, "rename")
                    writeback_backfilled += 1

                metadata_history_count = await _history_count(db, item.id, "metadata_write")
                if item.last_writeback_at is not None or metadata_history_count > 0:
                    metadata_operation = await bootstrap_writeback_operation_from_mirror(
                        db,
                        media_item=item,
                        operation_type="metadata_write",
                    )
                    if metadata_operation is not None:
                        metadata_operation.attempt_count = metadata_history_count
                        metadata_write_backfilled += 1

                if idx % batch_size == 0:
                    await db.commit()
                    if sleep_seconds > 0:
                        await asyncio.sleep(sleep_seconds)
            except Exception:
                failed += 1
                await db.rollback()
        if items:
            await db.commit()

    return {
        "dry_run": False,
        "capability_candidates": capability_backfilled,
        "writeback_candidates": writeback_backfilled,
        "capability_backfilled": capability_backfilled,
        "writeback_backfilled": writeback_backfilled,
        "metadata_write_backfilled": metadata_write_backfilled,
        "failed": failed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--stop-after", type=int, default=None)
    parser.add_argument("--user-id", type=str, default=None)
    parser.add_argument("--source-id", type=str, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    counters = await backfill(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        stop_after=args.stop_after,
        user_id=args.user_id,
        source_id=args.source_id,
        sleep_seconds=args.sleep_seconds,
    )
    logger.info("Backfill results: %s", json.dumps(counters, default=str))
    if counters["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
