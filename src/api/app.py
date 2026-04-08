"""FastAPI application setup, lifespan, and router registration."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import create_tables, run_migrations, async_session
from src.models import User, QuotaEvent, MediaItem
from src.api.dependencies import DEV_USER_ID
from src.api.routes import upload, media, analysis, search, auth, download, health, quota, sources, admin, billing, connectors, google_auth, collections, google_drive_connector
from src.api.error_handlers import register_error_handlers
from src.analysis.processor import analyze_media_item
from src.analysis.drive_mutation_service import attempt_drive_rename_after_analysis
from src.ingestion.job_manager import get_pending_jobs

from sqlalchemy import select, update

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

    yield


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
    app.include_router(admin.router)
    app.include_router(billing.router)
    app.include_router(google_auth.router)
    app.include_router(collections.router)
    app.include_router(google_drive_connector.router)
    return app


app = create_app()
