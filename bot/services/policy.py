from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Set, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from bot.constants import POLICY_ADMINS
from bot.db.models import Chat

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]


class AdminCache:
    """Кеш getChatAdministrators. Без нього кожна згадка — зайвий виклик API."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._cache: Dict[int, Tuple[float, Set[int]]] = {}

    async def get_admin_ids(self, bot: Bot, chat_id: int) -> Set[int]:
        cached = self._cache.get(chat_id)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            admins = await bot.get_chat_administrators(chat_id)
        except TelegramAPIError as error:
            logger.warning("Не вдалося отримати адмінів чату %s: %s", chat_id, error)
            # Порожній набір безпечніший за помилку: політика "admins" просто не пустить.
            return cached[1] if cached else set()
        admin_ids = {admin.user.id for admin in admins}
        self._cache[chat_id] = (now + self._ttl, admin_ids)
        return admin_ids

    def invalidate(self, chat_id: int) -> None:
        self._cache.pop(chat_id, None)


async def is_admin(bot: Bot, admin_cache: AdminCache, message: Message) -> bool:
    """Чи має автор повідомлення адмінські права в цьому чаті."""
    # Анонімний адмін пише від імені групи — from_user підмінений на GroupAnonymousBot.
    if message.sender_chat is not None and message.sender_chat.id == message.chat.id:
        return True
    if message.from_user is None:
        return False
    admin_ids = await admin_cache.get_admin_ids(bot, message.chat.id)
    return message.from_user.id in admin_ids


async def check_policy(
    bot: Bot,
    admin_cache: AdminCache,
    message: Message,
    policy: str,
) -> bool:
    """policy == "members" пускає всіх, "admins" — лише адмінів."""
    if policy != POLICY_ADMINS:
        return True
    return await is_admin(bot, admin_cache, message)


def _chat_timezone(chat: Chat):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(chat.timezone)
    except Exception:  # noqa: BLE001 — некоректна tz не має ламати згадку
        logger.warning("Невідома таймзона %r у чаті %s, беремо UTC", chat.timezone, chat.chat_id)
        return timezone.utc


def is_quiet_now(chat: Chat, now: Optional[datetime] = None) -> bool:
    """Чи зараз тихі години — тоді згадка йде з disable_notification."""
    if not chat.quiet_hours_enabled:
        return False
    start, end = chat.quiet_start, chat.quiet_end
    if start == end:
        return False
    moment = (now or datetime.now(timezone.utc)).astimezone(_chat_timezone(chat))
    hour = moment.hour
    if start < end:
        return start <= hour < end
    # Інтервал через північ, наприклад 23 -> 8.
    return hour >= start or hour < end
