from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.config import Settings
from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.utils.api_extras import sender_tag

logger = logging.getLogger(__name__)

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


class MemberTrackerMiddleware(BaseMiddleware):
    """Головне джерело бази учасників.

    Bot API не вміє віддати список учасників групи, тож ми запам'ятовуємо кожного,
    хто щось написав. Саме тому боту потрібен вимкнений privacy mode — інакше він
    бачить лише команди й ніколи не дізнається про решту людей у чаті.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        session = data.get("session")
        if session is not None and event.chat.type in GROUP_TYPES:
            try:
                chat = await chats_repo.get_or_create_chat(
                    session, event.chat.id, event.chat.title, self._settings
                )
                data["db_chat"] = chat

                user = event.from_user
                if user is not None and not user.is_bot:
                    await members_repo.upsert_user(
                        session,
                        user_id=user.id,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        username=user.username,
                        is_bot=user.is_bot,
                    )
                    # Bot API 9.5 кладе тег автора просто в повідомлення, тож
                    # збираємо його безкоштовно — без жодного виклику API.
                    tag_present, tag = sender_tag(event)
                    await members_repo.ensure_membership(
                        session,
                        event.chat.id,
                        user.id,
                        tag_present=tag_present,
                        telegram_tag=tag,
                    )
            except Exception:  # noqa: BLE001 — трекінг не має ламати обробку повідомлення
                logger.exception("Не вдалося оновити дані учасника чату %s", event.chat.id)
                await session.rollback()

        return await handler(event, data)
