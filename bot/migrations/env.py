from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from bot.db.models import Base
from bot.db.session import _prepare_sqlite_path


class MigrationSettings(BaseSettings):
    """Навмисно окремо від bot.config: міграціям не потрібен BOT_TOKEN."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///data/bot.db"


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
DATABASE_URL = MigrationSettings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite не вміє ALTER для більшості змін — batch-режим обходить це.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    _prepare_sqlite_path(DATABASE_URL)
    engine = create_async_engine(DATABASE_URL, poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
