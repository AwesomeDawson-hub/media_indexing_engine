"""FastAPI application setup, lifespan, and router registration."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import create_tables, run_migrations, async_session
from src.models import User, QuotaEvent, MediaItem, Source, SourceConnector, SyncRun
from src.api.dependencies import DEV_USER_ID
from src.api.routes import upload, media, analysis, search, auth, download, health, quota, sources, admin, billing, connectors, google_auth, collections, google_drive_connector, export
from src.api.error_handlers import register_error_handlers
from src.analysis.processor import analyze_media_item
from datetime import datetime, timezone
from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis
from src.ingestion.job_manager import get_pending_jobs

from sqlalchemy import select, update
from datetime import timedelta

logger = logging.getLogger(__name__)


async def _retry_writeback_task(media_item_id: str) -> None:
    """Background task: open a fresh session and retry a pending_writeback item."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(MediaItem).where(MediaItem.id == media_item_id)
            )
            item = result.scalar_one_or_none()
            if item is None or item.mutation_state != "pending_writeback":
                return
            await attempt_drive_rename_after_analysis(db, item)
            await db.commit()
    except Exception:
        logger.exception("Startup writeback retry failed for item %s", media_item_id)


async def _auto_sync_task(source_id: str, user_id: str) -> None:
    """Background task: run one scheduled auto-sync for a source (P7-006)."""
    try:
        from src.connectors.sync_service import trigger_sync
        from src.storage.file_store import get_file_store
        from src.ingestion.upload_service import UploadService

        file_store = get_file_store(settings.storage)
        upload_service = UploadService(file_store)

        async with async_session() as db:
            await trigger_sync(
                source_id=source_id,
                user_id=user_id,
                db=db,
                file_store=file_store,
                upload_service=upload_service,
                trigger_type="auto",
            )
    except Exception:
        logger.exception("Auto-sync task failed for source %s", source_id)


async def _auto_sync_loop() -> None:
    """Periodically fire auto-sync for sources with the scheduler enabled (P7-006).

    Wakes every 60 seconds, queries connectors with ``auto_sync_enabled=True``,
    and fires a background task for each source whose next-sync time has passed.
    Sources with an in-progress sync run are skipped.
    """
    while True:
        try:
            await asyncio.sleep(60)
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)

            async with async_session() as db:
                # Load all auto-sync-enabled connectors joined with their source
                result = await db.execute(
                    select(SourceConnector, Source)
                    .join(Source, SourceConnector.source_id == Source.id)
                    .where(
                        SourceConnector.auto_sync_enabled.is_(True),
                        Source.archived_at.is_(None),
                    )
                )
                rows = result.all()

            for connector_row, source in rows:
                # Decide if it's time to sync
                interval = timedelta(minutes=connector_row.auto_sync_interval_minutes)
                if source.last_synced_at is not None and now - source.last_synced_at < interval:
                    continue  # Not due yet

                # Skip if a sync is already running for this source
                async with async_session() as db:
                    overlap = await db.execute(
                        select(SyncRun).where(
                            SyncRun.source_id == source.id,
                            SyncRun.status.in_(["pending", "running"]),
                        )
                    )
                    if overlap.scalar_one_or_none() is not None:
                        continue

                logger.info(
                    "Auto-sync: scheduling source %s (interval=%dm)",
                    source.id,
                    connector_row.auto_sync_interval_minutes,
                )
                asyncio.create_task(_auto_sync_task(source.id, source.user_id))

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Auto-sync loop encountered an unexpected error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables (dev) or run migrations (prod), then seed dev user."""
    if settings.app.debug:
        await create_tables()
    else:
        await run_migrations()

    if settings.auth.dev_mode:
        logger.warning("AUTH DEV MODE IS ACTIVE — all routes accept unauthenticated requests. Do NOT use in production.")
        # Auto-seed dev user if not present
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == DEV_USER_ID))
            if result.scalar_one_or_none() is None:
                db.add(User(
                    id=DEV_USER_ID,
                    email="dev@example.com",
                    display_name="Dev User",
                ))
                await db.commit()

    if upload._vision_provider is not None:
        async with async_session() as db:
            # Release orphaned 'reserved' quota events for media items that are
            # already completed or errored (left over from interrupted container runs).
            orphan_result = await db.execute(
                update(QuotaEvent)
                .where(
                    QuotaEvent.event_type == "reserved",
                    QuotaEvent.media_item_id.in_(
                        select(MediaItem.id).where(
                            MediaItem.status.in_(["completed", "error"])
                        )
                    ),
                )
                .values(event_type="released")
            )
            orphaned = orphan_result.rowcount
            if orphaned:
                await db.commit()
                logger.info("Released %d orphaned quota reservation(s) on startup", orphaned)

            pending_jobs = await get_pending_jobs(db, limit=1000, statuses=("pending", "running"))

            # Look up reserved quota events for each resuming job so they are
            # properly consumed/released by the processor (not left dangling).
            job_reservations: dict[str, str | None] = {}
            for job in pending_jobs:
                res = await db.execute(
                    select(QuotaEvent.id)
                    .where(
                        QuotaEvent.media_item_id == job.media_item_id,
                        QuotaEvent.event_type == "reserved",
                    )
                    .order_by(QuotaEvent.created_at.desc())
                    .limit(1)
                )
                row = res.scalar_one_or_none()
                job_reservations[job.id] = str(row) if row else None

        for job in pending_jobs:
            # Reference-mode items (local_folder) cannot be resumed on restart —
            # the original bytes are gone. Mark them failed so they don't loop.
            media_item_result = await db.execute(
                select(MediaItem).where(MediaItem.id == job.media_item_id)
            )
            job_media_item = media_item_result.scalar_one_or_none()
            if job_media_item and job_media_item.storage_mode != "full":
                job.status = "failed"
                job.error_message = "Could not resume: original bytes unavailable after restart. Please re-upload."
                job.completed_at = datetime.now(timezone.utc)
                job_media_item.status = "error"
                await db.commit()
                continue
            asyncio.create_task(
                analyze_media_item(
                    job.id,
                    upload._vision_provider,
                    upload._file_store,
                    upload._indexing_service,
                    reservation_id=job_reservations[job.id],
                )
            )

        if pending_jobs:
            logger.info("Resumed %d pending analysis job(s) on startup", len(pending_jobs))

        # Retry pending_writeback items on startup (P7-005)
        async with async_session() as db:
            writeback_result = await db.execute(
                select(MediaItem).where(MediaItem.mutation_state == "pending_writeback")
            )
            writeback_items = writeback_result.scalars().all()

        if writeback_items:
            logger.info(
                "Scheduling startup retry for %d pending_writeback item(s)",
                len(writeback_items),
            )
            for wb_item in writeback_items:
                asyncio.create_task(_retry_writeback_task(wb_item.id))

    # Sweep expired export artifacts left from previous runs (P11-002)
    from src.api.routes.export import _sweep_expired_export_artifacts
    async with async_session() as db:
        await _sweep_expired_export_artifacts(db)

    # Start the auto-sync scheduler loop (P7-006)
    scheduler_task = asyncio.create_task(_auto_sync_loop())
    logger.info("Auto-sync scheduler started")

    yield

    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app.name,
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(media.router)
    app.include_router(analysis.router)
    app.include_router(search.router)
    app.include_router(download.router)
    app.include_router(quota.router)
    app.include_router(sources.router)
    app.include_router(connectors.router)
    app.include_router(connectors.global_router)
    app.include_router(admin.router)
    app.include_router(billing.router)
    app.include_router(google_auth.router)
    app.include_router(collections.router)
    app.include_router(google_drive_connector.router)
    app.include_router(export.router)
    return app


app = create_app()
