"""Цикл обробки має переживати збої, а не завершувати процес."""

from __future__ import annotations

import asyncio
import logging
from typing import List

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import ErrorEvent, Update

from bot.__main__ import _heartbeat, _run_polling_forever, build_dispatcher


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Backoff тестуємо за фактом викликів, а не реальним очікуванням."""
    slept: List[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("bot.__main__.asyncio.sleep", fake_sleep)
    return slept


class FlakyDispatcher:
    """Падає задану кількість разів, потім завершується штатно."""

    def __init__(self, failures: int, error: Exception = None) -> None:
        self.remaining = failures
        self.error = error or RuntimeError("polling помер")
        self.starts = 0

    async def start_polling(self, bot, **kwargs):
        self.starts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.error
        return None


async def test_polling_restarts_after_crash(no_real_sleep, caplog):
    dispatcher = FlakyDispatcher(failures=3)

    with caplog.at_level(logging.ERROR):
        await _run_polling_forever(dispatcher, bot=None)

    assert dispatcher.starts == 4  # три падіння + успішний запуск
    assert len(caplog.records) == 3


async def test_backoff_grows_but_is_capped(no_real_sleep):
    await _run_polling_forever(FlakyDispatcher(failures=8), bot=None)
    assert no_real_sleep == [1, 2, 4, 8, 16, 32, 60, 60]


async def test_network_errors_do_not_stop_polling(no_real_sleep):
    dispatcher = FlakyDispatcher(
        failures=2, error=TelegramNetworkError(method=None, message="timeout")
    )
    await _run_polling_forever(dispatcher, bot=None)
    assert dispatcher.starts == 3


async def test_cancellation_is_not_swallowed(no_real_sleep):
    """Зупинка контейнера має саме зупиняти, а не крутити цикл далі."""

    class Cancelling:
        starts = 0

        async def start_polling(self, bot, **kwargs):
            Cancelling.starts += 1
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _run_polling_forever(Cancelling(), bot=None)
    assert Cancelling.starts == 1


async def test_clean_stop_does_not_restart(no_real_sleep):
    dispatcher = FlakyDispatcher(failures=0)
    await _run_polling_forever(dispatcher, bot=None)
    assert dispatcher.starts == 1
    assert no_real_sleep == []


async def test_heartbeat_writes_timestamp(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "heartbeat"
    calls = []

    async def stop_after_first(delay):
        calls.append(delay)
        raise asyncio.CancelledError()

    monkeypatch.setattr("bot.__main__.asyncio.sleep", stop_after_first)

    with pytest.raises(asyncio.CancelledError):
        await _heartbeat(path, interval=30)

    assert path.exists()
    assert int(path.read_text()) > 0
    assert calls == [30]


async def test_error_handler_keeps_dispatcher_alive(settings, database, monkeypatch, caplog):
    """Помилка в хендлері не має спливати вище диспетчера."""
    import bot.db.session as session_module

    monkeypatch.setattr(session_module, "_database", database)
    dispatcher = build_dispatcher(settings, bot=None)

    handlers = dispatcher.errors.handlers
    assert handlers, "глобальний обробник помилок не зареєстровано"
    handler = handlers[0].callback

    event = ErrorEvent(
        update=Update(update_id=1),
        exception=TelegramBadRequest(method=None, message="Bad Request: TOPIC_CLOSED"),
    )
    with caplog.at_level(logging.WARNING):
        assert await handler(event) is True

    # Відмову Telegram логуємо коротко, без traceback.
    assert any("TOPIC_CLOSED" in record.getMessage() for record in caplog.records)
    assert not any(record.exc_info for record in caplog.records)


async def test_unexpected_error_is_logged_with_traceback(settings, database, monkeypatch, caplog):
    import bot.db.session as session_module

    monkeypatch.setattr(session_module, "_database", database)
    dispatcher = build_dispatcher(settings, bot=None)
    handler = dispatcher.errors.handlers[0].callback

    event = ErrorEvent(update=Update(update_id=1), exception=ValueError("наш баг"))
    with caplog.at_level(logging.ERROR):
        assert await handler(event) is True

    assert any(record.exc_info for record in caplog.records)
