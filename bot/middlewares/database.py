from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.db.session import Database

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Одна сесія на апдейт: коміт після успішної обробки, ролбек — після винятку."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with self._database.session() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            return result
