from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.session import Database


@pytest.fixture
def settings() -> Settings:
    # _env_file=None — щоб локальний .env розробника не впливав на тести.
    return Settings(
        _env_file=None,
        bot_token="123:test",  # type: ignore[arg-type]
        database_url="sqlite+aiosqlite:///:memory:",
        default_cooldown_seconds=600,
    )


@pytest_asyncio.fixture
async def database(tmp_path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await db.create_all()
    yield db
    await db.dispose()


@pytest_asyncio.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.session() as db_session:
        yield db_session
