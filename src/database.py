"""Database engine, session factory, and table management."""

import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database.url, echo=settings.app.debug)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def create_tables() -> None:
    """Create all tables. Used for dev/testing — production uses migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables. Used for testing only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def run_migrations() -> None:
    """Run Alembic migrations to head. Used in production (non-debug) mode.

    Alembic's env.py calls asyncio.run() internally, so we run it in a thread
    executor to avoid a nested-event-loop error.
    """
    from alembic import command as alembic_command
    from alembic.config import Config

    alembic_cfg_path = str(Path(__file__).resolve().parent.parent / "alembic.ini")

    def _run() -> None:
        cfg = Config(alembic_cfg_path)
        alembic_command.upgrade(cfg, "head")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)
    logger.info("Alembic migrations applied (upgrade head complete).")
