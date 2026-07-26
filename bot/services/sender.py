from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Dict, Optional, Sequence

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

logger = logging.getLogger(__name__)

#: Скільки разів повторювати відправку після 429, перш ніж здатися.
MAX_RETRY_AFTER_ATTEMPTS = 3


class ChatUnavailableError(Exception):
    """Бота вигнали з чату або заблокували — чат треба позначити неактивним."""


class MessageSender:
    """Послідовна відправка батчів із паузами й обробкою 429.

    Замок на чат гарантує, що два одночасні @all не перемішають свої батчі
    і не перевищать разом ліміт ~20 повідомлень за хвилину на групу.
    """

    def __init__(self, bot: Bot, batch_delay: float = 0.35) -> None:
        self._bot = bot
        self._batch_delay = batch_delay
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def send_batches(
        self,
        chat_id: int,
        texts: Sequence[str],
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
        disable_notification: bool = False,
    ) -> int:
        """Надсилає всі батчі. Повертає кількість успішно доставлених повідомлень."""
        if not texts:
            return 0

        sent = 0
        async with self._locks[chat_id]:
            for index, text in enumerate(texts):
                if index:
                    await asyncio.sleep(self._batch_delay)
                delivered = await self._send_one(
                    chat_id=chat_id,
                    text=text,
                    # Реплаєм чіпляємо лише перший батч, решта йде окремими повідомленнями.
                    reply_to_message_id=reply_to_message_id if index == 0 else None,
                    message_thread_id=message_thread_id,
                    disable_notification=disable_notification,
                )
                if delivered:
                    sent += 1
        return sent

    async def _send_one(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int],
        message_thread_id: Optional[int],
        disable_notification: bool,
    ) -> bool:
        for attempt in range(MAX_RETRY_AFTER_ATTEMPTS):
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=reply_to_message_id,
                    message_thread_id=message_thread_id,
                    disable_notification=disable_notification,
                    disable_web_page_preview=True,
                )
                return True
            except TelegramRetryAfter as error:
                delay = error.retry_after + 1
                logger.warning(
                    "429 від Telegram у чаті %s, чекаємо %s с (спроба %s/%s)",
                    chat_id,
                    delay,
                    attempt + 1,
                    MAX_RETRY_AFTER_ATTEMPTS,
                )
                await asyncio.sleep(delay)
            except TelegramForbiddenError as error:
                logger.info("Немає доступу до чату %s: %s", chat_id, error)
                raise ChatUnavailableError(str(error)) from error
            except TelegramBadRequest as error:
                message = str(error).lower()
                if reply_to_message_id is not None and "reply" in message:
                    # Повідомлення, на яке відповідаємо, встигли видалити.
                    logger.info("Реплай у чаті %s не вдався, шлемо без нього", chat_id)
                    reply_to_message_id = None
                    continue
                logger.warning("BadRequest у чаті %s: %s", chat_id, error)
                return False
            except TelegramNetworkError as error:
                logger.warning("Мережа підвела на чаті %s: %s", chat_id, error)
                await asyncio.sleep(1)
            except TelegramAPIError as error:
                # Будь-яка інша відмова Telegram не має зривати решту батчів.
                logger.warning("Помилка Telegram у чаті %s: %s", chat_id, error)
                return False
        logger.error("Не вдалося надіслати повідомлення в чат %s після повторів", chat_id)
        return False
