"""Відповідь бота не має ронити обробку апдейта.

Реальний випадок із продакшену: команду написали в закритій темі форуму,
Telegram відповів TOPIC_CLOSED, і виняток пройшов крізь усі шари нагору.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from bot.utils.replies import safe_answer, safe_reply, safe_send

CHAT_ID = -100777


class FakeMessage:
    """Message, у якого reply/answer поводяться так, як накажемо."""

    def __init__(self, reply_error=None, answer_error=None) -> None:
        self.chat = SimpleNamespace(id=CHAT_ID)
        self._reply_error = reply_error
        self._answer_error = answer_error
        self.reply_calls: List[str] = []
        self.answer_calls: List[str] = []

    async def reply(self, text: str, **kwargs):
        self.reply_calls.append(text)
        if self._reply_error is not None:
            error, self._reply_error = self._reply_error, None
            raise error
        return SimpleNamespace(text=text)

    async def answer(self, text: str, **kwargs):
        self.answer_calls.append(text)
        if self._answer_error is not None:
            raise self._answer_error
        return SimpleNamespace(text=text)


def bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=None, message=text)


async def test_successful_reply_returns_message():
    message = FakeMessage()
    result = await safe_reply(message, "привіт")
    assert result is not None
    assert message.reply_calls == ["привіт"]


async def test_topic_closed_is_swallowed():
    """Саме та помилка, після якої бот замовкав."""
    message = FakeMessage(reply_error=bad_request("Bad Request: TOPIC_CLOSED"))

    assert await safe_reply(message, "текст") is None
    # Друга спроба безглузда — тема не відкриється.
    assert message.answer_calls == []


@pytest.mark.parametrize(
    "description",
    [
        "Bad Request: CHAT_WRITE_FORBIDDEN",
        "Bad Request: not enough rights to send text messages",
        "Bad Request: chat not found",
        "Bad Request: message thread not found",
        "Bad Request: TOPIC_DELETED",
    ],
)
async def test_permanent_failures_never_raise(description):
    message = FakeMessage(reply_error=bad_request(description))
    assert await safe_reply(message, "текст") is None


async def test_missing_reply_target_falls_back_to_plain_message():
    message = FakeMessage(reply_error=bad_request("Bad Request: reply message not found"))

    result = await safe_reply(message, "текст")
    assert result is not None
    assert message.answer_calls == ["текст"]


async def test_forbidden_is_swallowed():
    message = FakeMessage(reply_error=TelegramForbiddenError(method=None, message="bot kicked"))
    assert await safe_reply(message, "текст") is None


async def test_retry_after_is_retried_once(monkeypatch):
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("bot.utils.replies.asyncio.sleep", fake_sleep)
    message = FakeMessage(
        reply_error=TelegramRetryAfter(method=None, message="too many", retry_after=3)
    )

    result = await safe_reply(message, "текст")
    assert result is not None
    assert slept == [4]
    assert len(message.reply_calls) == 2


async def test_network_error_is_retried_then_given_up(monkeypatch):
    async def fake_sleep(delay):
        return None

    monkeypatch.setattr("bot.utils.replies.asyncio.sleep", fake_sleep)

    class AlwaysFailing(FakeMessage):
        async def reply(self, text: str, **kwargs):
            self.reply_calls.append(text)
            raise TelegramNetworkError(method=None, message="timeout")

    message = AlwaysFailing()
    assert await safe_reply(message, "текст") is None
    assert len(message.reply_calls) == 2


async def test_safe_answer_swallows_errors():
    message = FakeMessage(answer_error=bad_request("Bad Request: TOPIC_CLOSED"))
    assert await safe_answer(message, "текст") is None


async def test_safe_send_swallows_errors():
    class FakeBot:
        def __init__(self) -> None:
            self.calls: List[str] = []

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append(text)
            raise bad_request("Bad Request: TOPIC_CLOSED")

    bot = FakeBot()
    assert await safe_send(bot, CHAT_ID, "текст") is None
    assert bot.calls == ["текст"]


async def test_not_modified_is_swallowed_quietly():
    """Спроба переписати повідомлення тим самим вмістом — не помилка."""
    message = FakeMessage(
        reply_error=bad_request(
            "Bad Request: message is not modified: specified new message content and "
            "reply markup are exactly the same as a current content and reply markup"
        )
    )

    assert await safe_reply(message, "текст") is None
    assert message.answer_calls == []
