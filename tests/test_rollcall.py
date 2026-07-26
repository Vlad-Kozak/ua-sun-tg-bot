"""Перекличка кнопкою і збір через реакції.

Обидва канали існують заради одного: дати людині потрапити в базу, не пишучи
в чат. Telegram не віддає списку учасників, тож інакше мовчуни лишаються
невидимими для @all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional

import pytest
import pytest_asyncio
from aiogram.types import Chat as TgChat
from aiogram.types import User as TgUser

from bot.config import Settings
from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.handlers.chat_events import reaction_seen
from bot.handlers.rollcall import CALLBACK_DATA, _message_state, on_here
from bot.handlers.settings import _render_coverage

CHAT_ID = -1002222222222


class FakeBot:
    def __init__(self, total: Optional[int] = 50, error: Exception = None) -> None:
        self._total = total
        self._error = error

    async def get_chat_member_count(self, chat_id: int) -> int:
        if self._error is not None:
            raise self._error
        return self._total


class FakeCallbackMessage:
    def __init__(self) -> None:
        self.chat = TgChat(id=CHAT_ID, type="supergroup", title="Тест")
        self.message_id = 555
        self.edits: List[str] = []

    async def edit_text(self, text: str, **kwargs):
        self.edits.append(text)
        return self


class FakeCallback:
    def __init__(self, user: Optional[TgUser], message=None) -> None:
        self.from_user = user
        self.message = message if message is not None else FakeCallbackMessage()
        self.data = CALLBACK_DATA
        self.answers: List[str] = []

    async def answer(self, text: str = "", **kwargs) -> None:
        self.answers.append(text)


@pytest.fixture(autouse=True)
def clean_refresh_cache():
    _message_state.clear()
    yield
    _message_state.clear()


@pytest_asyncio.fixture
async def prepared(database, settings: Settings):
    async with database.session() as session:
        await chats_repo.get_or_create_chat(session, CHAT_ID, "Тест", settings)
        await session.commit()
    return database


async def test_button_registers_a_silent_member(prepared, settings):
    """Головний сценарій: людина ніколи не писала, але тепер у базі."""
    user = TgUser(id=9001, is_bot=False, first_name="Мовчун", username="silent")
    callback = FakeCallback(user)

    async with prepared.session() as session:
        await on_here(callback, session, settings, FakeBot())
        await session.commit()

        membership = await members_repo.get_membership(session, CHAT_ID, 9001)
        stored = await members_repo.get_user(session, 9001)

    assert membership is not None and membership.is_active is True
    assert stored.username == "silent"
    assert callback.answers and "Записав" in callback.answers[0]


async def test_button_is_idempotent(prepared, settings):
    user = TgUser(id=9002, is_bot=False, first_name="Двічі")

    async with prepared.session() as session:
        for _ in range(3):
            await on_here(FakeCallback(user), session, settings, FakeBot())
        await session.commit()
        assert await members_repo.count_active_members(session, CHAT_ID) == 1


async def test_counter_refresh_is_throttled(prepared, settings):
    """Масове натискання не має перетворюватися на потік editMessageText."""
    shared_message = FakeCallbackMessage()

    async with prepared.session() as session:
        for index in range(5):
            user = TgUser(id=9100 + index, is_bot=False, first_name=f"Гість{index}")
            await on_here(FakeCallback(user, shared_message), session, settings, FakeBot())
        await session.commit()

    assert len(shared_message.edits) == 1
    assert "Вже знаю" in shared_message.edits[0]


async def test_callback_without_message_is_handled(prepared, settings):
    callback = FakeCallback(TgUser(id=9003, is_bot=False, first_name="Х"), message=False)
    callback.message = None

    async with prepared.session() as session:
        await on_here(callback, session, settings, FakeBot())

    assert callback.answers and "не вдалося" in callback.answers[0].lower()


def make_reaction(user: Optional[TgUser], chat_type: str = "supergroup"):
    return SimpleNamespace(
        user=user,
        chat=TgChat(id=CHAT_ID, type=chat_type, title="Тест"),
        message_id=1,
        date=datetime.now(timezone.utc),
    )


async def test_reaction_registers_member(prepared, settings):
    user = TgUser(id=9200, is_bot=False, first_name="Реагує")

    async with prepared.session() as session:
        await reaction_seen(make_reaction(user), session, settings)
        await session.commit()
        membership = await members_repo.get_membership(session, CHAT_ID, 9200)

    assert membership is not None and membership.is_active is True


async def test_anonymous_reaction_is_ignored(prepared, settings):
    """Реакція від імені групи приходить без user — реєструвати нікого."""
    async with prepared.session() as session:
        await reaction_seen(make_reaction(None), session, settings)
        await session.commit()
        assert await members_repo.count_active_members(session, CHAT_ID) == 0


async def test_bot_reaction_is_ignored(prepared, settings):
    bot_user = TgUser(id=9201, is_bot=True, first_name="Робот")

    async with prepared.session() as session:
        await reaction_seen(make_reaction(bot_user), session, settings)
        await session.commit()
        assert await members_repo.count_active_members(session, CHAT_ID) == 0


async def test_private_chat_reaction_is_ignored(prepared, settings):
    user = TgUser(id=9202, is_bot=False, first_name="Приват")

    async with prepared.session() as session:
        await reaction_seen(make_reaction(user, chat_type="private"), session, settings)
        await session.commit()
        assert await members_repo.count_active_members(session, CHAT_ID) == 0


async def test_coverage_counts_unknown_people():
    """47 у чаті, з них один — сам бот, 12 відомі → 34 невідомих."""
    lines = await _render_coverage(FakeBot(total=47), CHAT_ID, known=12)
    text = "\n".join(lines)

    assert "усього в чаті за даними Telegram: 47" in text
    assert "ще не знаю: 34" in text
    assert "/rollcall" in text


async def test_coverage_reports_full_knowledge():
    lines = await _render_coverage(FakeBot(total=13), CHAT_ID, known=12)
    assert "знаю всіх" in "\n".join(lines)


async def test_coverage_never_goes_negative():
    """Інші боти в чаті можуть зробити known більшим за total-1."""
    lines = await _render_coverage(FakeBot(total=5), CHAT_ID, known=10)
    assert "знаю всіх" in "\n".join(lines)


async def test_coverage_is_skipped_when_telegram_fails():
    from aiogram.exceptions import TelegramBadRequest

    error = TelegramBadRequest(method=None, message="chat not found")
    assert await _render_coverage(FakeBot(error=error), CHAT_ID, known=1) == []


async def test_repeat_press_does_not_rewrite_the_same_text(prepared, settings, monkeypatch):
    """Регресія: повторний натиск давав «message is not modified» у логах.

    Лічильник не змінюється, бо людина вже в базі — переписувати нічого.
    """
    import bot.handlers.rollcall as rollcall

    clock = {"now": 1000.0}
    monkeypatch.setattr(rollcall.time, "monotonic", lambda: clock["now"])

    shared_message = FakeCallbackMessage()
    user = TgUser(id=9300, is_bot=False, first_name="Наполегливий")

    async with prepared.session() as session:
        await on_here(FakeCallback(user, shared_message), session, settings, FakeBot())
        assert len(shared_message.edits) == 1

        # Пауза минула, але текст той самий — запиту до Telegram бути не має.
        clock["now"] += 3600
        await on_here(FakeCallback(user, shared_message), session, settings, FakeBot())
        await session.commit()

    assert len(shared_message.edits) == 1


async def test_new_person_after_pause_updates_counter(prepared, settings, monkeypatch):
    """А от коли лічильник справді зрушив — редагування має відбутися."""
    import bot.handlers.rollcall as rollcall

    clock = {"now": 1000.0}
    monkeypatch.setattr(rollcall.time, "monotonic", lambda: clock["now"])

    shared_message = FakeCallbackMessage()

    async with prepared.session() as session:
        first = TgUser(id=9301, is_bot=False, first_name="Перший")
        await on_here(FakeCallback(first, shared_message), session, settings, FakeBot())

        clock["now"] += 3600
        second = TgUser(id=9302, is_bot=False, first_name="Другий")
        await on_here(FakeCallback(second, shared_message), session, settings, FakeBot())
        await session.commit()

    assert len(shared_message.edits) == 2
    assert shared_message.edits[0] != shared_message.edits[1]
