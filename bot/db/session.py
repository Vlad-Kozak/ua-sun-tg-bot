from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.db.models import Base

logger = logging.getLogger(__name__)


def _prepare_sqlite_path(url: str) -> None:
    """Створює теку під файл БД — інакше перше підключення впаде на "unable to open"."""
    parsed = make_url(url)
    if not parsed.drivername.startswith("sqlite") or not parsed.database:
        return
    if parsed.database == ":memory:":
        return
    Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """ON DELETE CASCADE у SQLite не працює без foreign_keys=ON, і це per-connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        _prepare_sqlite_path(url)
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            _apply_sqlite_pragmas(self.engine)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    def session(self) -> AsyncSession:
        return self.session_factory()

    async def create_all(self) -> None:
        """Тільки для тестів. У проді схему розкочує Alembic."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


_database: Optional[Database] = None


def get_database(url: Optional[str] = None) -> Database:
    global _database
    if _database is None:
        if url is None:
            raise RuntimeError("Database ще не ініціалізована — передай url при першому виклику")
        _database = Database(url)
        logger.info("Підключення до БД ініціалізовано")
    return _database
