"""FastAPI application setup, lifespan, and router registration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import create_tables, async_session
from src.models import User
from src.api.dependencies import DEV_USER_ID
from src.api.routes import upload, media, analysis, search, auth, download
from src.api.error_handlers import register_error_handlers

from sqlalchemy import select

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and seed dev user on startup."""
    await create_tables()

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
    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(media.router)
    app.include_router(analysis.router)
    app.include_router(search.router)
    app.include_router(download.router)
    return app


app = create_app()
