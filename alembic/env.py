import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context

# Alembic Config object
config = context.config

# Set up loggers from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import the project ORM Base so autogenerate can diff the schema
from src.database import Base  # noqa: E402
import src.models  # noqa: F401, E402 — registers all ORM models on Base.metadata
target_metadata = Base.metadata


def get_db_url() -> str:
    """Return database URL: DATABASE_URL env var takes priority over settings.yaml."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    project_root = Path(__file__).resolve().parent.parent
    settings_path = project_root / "config" / "settings.yaml"
    with open(settings_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("database", {}).get("url", "sqlite+aiosqlite:///./media_index.db")


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB connection)."""
    url = get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect with the async engine and run migrations via run_sync."""
    url = get_db_url()
    connectable = create_async_engine(url, poolclass=NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using the async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
