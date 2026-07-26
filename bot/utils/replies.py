from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import Message

logger = logging.getLogger(__name__)

#: Причини, після яких повторювати той самий виклик безглуздо: тема закрита,
#: чат недоступний, прав немає. Це нормальний стан світу, а не збій бота.
_PERMANENT_MARKERS = (
    "topic_closed",
    "topic_deleted",
    "chat_write_forbidden",
    "not enough rights",
    "have no rights",
    "chat not found",
    "message thread not found",
    "user_is_blocked",
    "bot was blocked",
    "bot was kicked",
)

#: Не помилка взагалі: ми спробували перезаписати повідомлення тим самим
#: вмістом. Телеграм так робити не дає, і це нормальний хід подій.
_BENIGN_MARKERS = ("message is not modified",)

#: Проблема саме з реплаєм: повідомлення надіслати можна, просто без відповіді.
_REPLY_MARKERS = (
    "reply message not found",
    "message to be replied not found",
    "message to reply not found",
    "replied message not found",
)


def _describe(error: Exception) -> str:
    return str(error).strip()


def _matches(error: Exception, markers: tuple) -> bool:
    text = _describe(error).lower()
    return any(marker in text for marker in markers)


async def _deliver(
    factory: Callable[[], Awaitable[Message]],
    chat_id: Optional[int] = None,
    fallback: Optional[Callable[[], Awaitable[Message]]] = None,
) -> Optional[Message]:
    """Надсилає повідомлення й ніколи не кидає виняток назовні.

    Відповідь бота — не та операція, заради якої варто ронити обробку апдейта:
    закрита тема форуму чи видалене повідомлення трапляються постійно.
    """
    for attempt in range(2):
        try:
            return await factory()
        except TelegramRetryAfter as error:
            if attempt:
                logger.warning("Чат %s: 429 і після очікування, кидаємо", chat_id)
                return None
            delay = error.retry_after + 1
            logger.info("Чат %s: 429, чекаємо %s с", chat_id, delay)
            await asyncio.sleep(delay)
        except TelegramBadRequest as error:
            if _matches(error, _BENIGN_MARKERS):
                logger.debug("Чат %s: вміст не змінився, редагування не потрібне", chat_id)
                return None
            if fallback is not None and _matches(error, _REPLY_MARKERS):
                # Повідомлення, на яке відповідаємо, встигли видалити.
                logger.info("Чат %s: реплай не вдався, шлемо без нього", chat_id)
                return await _deliver(fallback, chat_id=chat_id)
            if _matches(error, _PERMANENT_MARKERS):
                logger.info("Чат %s: не можемо написати — %s", chat_id, _describe(error))
                return None
            logger.warning("Чат %s: BadRequest — %s", chat_id, _describe(error))
            return None
        except TelegramForbiddenError as error:
            logger.info("Чат %s: доступ закрито — %s", chat_id, _describe(error))
            return None
        except TelegramNetworkError as error:
            if attempt:
                logger.warning("Чат %s: мережа не відповідає — %s", chat_id, _describe(error))
                return None
            await asyncio.sleep(1)
        except TelegramAPIError as error:
            logger.warning("Чат %s: помилка Telegram — %s", chat_id, _describe(error))
            return None
    return None


async def safe_reply(message: Message, text: str, **kwargs: Any) -> Optional[Message]:
    """Відповідь реплаєм; якщо вихідне повідомлення зникло — звичайним постом."""
    return await _deliver(
        lambda: message.reply(text, **kwargs),
        chat_id=message.chat.id,
        fallback=lambda: message.answer(text, **kwargs),
    )


async def safe_answer(message: Message, text: str, **kwargs: Any) -> Optional[Message]:
    return await _deliver(lambda: message.answer(text, **kwargs), chat_id=message.chat.id)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs: Any) -> Optional[Message]:
    return await _deliver(lambda: bot.send_message(chat_id, text, **kwargs), chat_id=chat_id)


async def safe_edit(message: Message, text: str, **kwargs: Any) -> Optional[Message]:
    """Редагування тексту. «message is not modified» — не помилка, а норма."""
    return await _deliver(
        lambda: message.edit_text(text, **kwargs), chat_id=message.chat.id
    )


async def safe_callback_answer(callback: Any, text: str = "", **kwargs: Any) -> None:
    """Відповідь на натиск кнопки.

    Callback «протухає» приблизно за хвилину, і відповідь на старий уже не
    пройде — але сама реєстрація користувача до цього моменту вже відбулася,
    тож помилку тут просто ковтаємо.
    """
    try:
        await callback.answer(text, **kwargs)
    except TelegramAPIError as error:
        logger.info("Не вдалося відповісти на callback: %s", error)
