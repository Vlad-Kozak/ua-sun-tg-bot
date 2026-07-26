"""Наскрізний прогін апдейту через диспетчер.

Юніт-тести перевіряють шматки; тут перевіряємо саме склейку: чи доїжджають
session, db_chat, sender і admin_cache до хендлера і чи розкривається @all.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Tuple

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Chat as TgChat
from aiogram.types import Message as TgMessage
from aiogram.types import Update
from aiogram.types import User as TgUser

import bot.db.session as session_module
from bot.__main__ import build_dispatcher
from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.db.session import Database

CHAT_ID = -1001111111111
AUTHOR_ID = 100

FAKE_TOKEN = "42:AAHfake-token-used-only-in-tests-000000000"


class FakeSender:
    """Замість Telegram API — просто фіксуємо, що і куди пішло б."""

    def __init__(self) -> None:
        self.calls: List[Tuple[int, List[str], bool]] = []

    async def send_batches(
        self,
        chat_id: int,
        texts,
        reply_to_message_id=None,
        message_thread_id=None,
        disable_notification: bool = False,
    ) -> int:
        self.calls.append((chat_id, list(texts), disable_notification))
        return len(texts)

    @property
    def mentioned_ids(self) -> set:
        ids = set()
        for _, texts, _ in self.calls:
            for text in texts:
                for part in text.split('tg://user?id=')[1:]:
                    ids.add(int(part.split('"')[0]))
        return ids


@pytest_asyncio.fixture
async def prepared(database: Database, settings):
    """Чат із трьома учасниками, тегом і дозволеним усім @all."""
    async with database.session() as session:
        await chats_repo.get_or_create_chat(session, CHAT_ID, "Тест", settings)
        await chats_repo.update_settings(
            session,
            CHAT_ID,
            all_policy="members",
            tag_policy="members",
            cooldown_seconds=0,
            quiet_hours_enabled=False,
        )
        for user_id, name in [(AUTHOR_ID, "Автор"), (101, "Оля"), (102, "Петро"), (103, "Ігор")]:
            await members_repo.upsert_user(session, user_id=user_id, first_name=name)
            await members_repo.ensure_membership(session, CHAT_ID, user_id)
        await members_repo.set_muted(session, CHAT_ID, 103, True)

        tag = await tags_repo.create_tag(session, CHAT_ID, "devs")
        await tags_repo.add_tag_member(session, tag.id, 101)
        await tags_repo.add_tag_member(session, tag.id, 103)
        await session.commit()
    return database


@pytest_asyncio.fixture
async def tg_bot():
    instance = Bot(token=FAKE_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    yield instance
    await instance.session.close()


@pytest.fixture
def dispatcher(settings, tg_bot, prepared, monkeypatch):
    # build_dispatcher бере БД через глобальний get_database — підміняємо на тестову.
    monkeypatch.setattr(session_module, "_database", prepared)
    dispatcher = build_dispatcher(settings, tg_bot)
    dispatcher["sender"] = FakeSender()
    return dispatcher


def make_update(text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=TgMessage(
            message_id=10,
            date=datetime.now(timezone.utc),
            chat=TgChat(id=CHAT_ID, type="supergroup", title="Тест"),
            from_user=TgUser(id=AUTHOR_ID, is_bot=False, first_name="Автор"),
            text=text,
        ),
    )


async def feed(dispatcher, tg_bot, text: str, update_id: int = 1) -> FakeSender:
    await dispatcher.feed_update(tg_bot, make_update(text, update_id))
    return dispatcher["sender"]


async def test_all_mentions_everyone_except_author_and_muted(dispatcher, tg_bot, caplog):
    with caplog.at_level(logging.ERROR):
        sender = await feed(dispatcher, tg_bot, "@all підйом")

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert sender.mentioned_ids == {101, 102}


async def test_named_tag_reaches_muted_member(dispatcher, tg_bot):
    sender = await feed(dispatcher, tg_bot, "гляньте, @devs")
    assert sender.mentioned_ids == {101, 103}


async def test_unknown_mention_is_ignored(dispatcher, tg_bot):
    sender = await feed(dispatcher, tg_bot, "написав @vasyl_pupkin, він не тег")
    assert sender.calls == []


async def test_plain_text_triggers_nothing(dispatcher, tg_bot):
    sender = await feed(dispatcher, tg_bot, "звичайне повідомлення без згадок")
    assert sender.calls == []


async def test_two_tags_are_merged_into_one_audience(dispatcher, tg_bot, prepared):
    async with prepared.session() as session:
        tag = await tags_repo.create_tag(session, CHAT_ID, "qa")
        await tags_repo.add_tag_member(session, tag.id, 102)
        await session.commit()

    sender = await feed(dispatcher, tg_bot, "@devs @qa збір")
    assert sender.mentioned_ids == {101, 102, 103}


async def test_tracker_registers_new_author(dispatcher, tg_bot, prepared):
    update = Update(
        update_id=99,
        message=TgMessage(
            message_id=11,
            date=datetime.now(timezone.utc),
            chat=TgChat(id=CHAT_ID, type="supergroup", title="Тест"),
            from_user=TgUser(id=555, is_bot=False, first_name="Новенька", username="nova"),
            text="привіт усім",
        ),
    )
    await dispatcher.feed_update(tg_bot, update)

    async with prepared.session() as session:
        user = await members_repo.get_user(session, 555)
        assert user is not None and user.username == "nova"
        membership = await members_repo.get_membership(session, CHAT_ID, 555)
        assert membership is not None and membership.is_active is True


async def test_cooldown_blocks_repeated_all(dispatcher, tg_bot, prepared):
    async with prepared.session() as session:
        await chats_repo.update_settings(session, CHAT_ID, cooldown_seconds=600)
        await session.commit()

    first = await feed(dispatcher, tg_bot, "@all перший раз", update_id=1)
    assert first.mentioned_ids == {101, 102}

    dispatcher["sender"] = FakeSender()
    second = await feed(dispatcher, tg_bot, "@all другий раз", update_id=2)
    assert second.calls == []


def test_router_can_be_built_twice():
    """Регресія: раніше роутери були глобальні й другий Dispatcher падав."""
    from bot.handlers import build_router

    first, second = build_router(), build_router()
    assert first is not second


async def test_partial_mention_calls_every_matching_tag(dispatcher, tg_bot, prepared):
    """@dev має підняти і @devs, і @devops."""
    async with prepared.session() as session:
        tag = await tags_repo.create_tag(session, CHAT_ID, "devops")
        await tags_repo.add_tag_member(session, tag.id, 102)
        await session.commit()

    sender = await feed(dispatcher, tg_bot, "@dev хто гляне?")
    assert sender.mentioned_ids == {101, 102, 103}
    assert "@devs" in sender.calls[0][1][0] and "@devops" in sender.calls[0][1][0]


async def test_exact_mention_does_not_pull_in_longer_tags(dispatcher, tg_bot, prepared):
    async with prepared.session() as session:
        tag = await tags_repo.create_tag(session, CHAT_ID, "devops")
        await tags_repo.add_tag_member(session, tag.id, 102)
        await session.commit()

    sender = await feed(dispatcher, tg_bot, "@devs тільки ви")
    assert sender.mentioned_ids == {101, 103}


async def test_mention_is_case_insensitive(dispatcher, tg_bot):
    sender = await feed(dispatcher, tg_bot, "@DeVs гляньте")
    assert sender.mentioned_ids == {101, 103}


async def test_too_many_partial_matches_call_nobody(dispatcher, tg_bot, prepared):
    async with prepared.session() as session:
        for index in range(6):
            tag = await tags_repo.create_tag(session, CHAT_ID, f"team{index}")
            await tags_repo.add_tag_member(session, tag.id, 101)
        await session.commit()

    sender = await feed(dispatcher, tg_bot, "@team збір")
    assert sender.calls == []


def make_tagged_update(user_id: int, tag, text: str = "привіт", update_id: int = 500):
    """Повідомлення з полем sender_tag, як його надсилає Bot API 9.5."""
    payload = {
        "message_id": 77,
        "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": CHAT_ID, "type": "supergroup", "title": "Тест"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Хтось"},
        "text": text,
    }
    if tag is not ...:
        payload["sender_tag"] = tag
    return Update.model_validate({"update_id": update_id, "message": payload})


async def test_sender_tag_is_stored_from_a_plain_message(dispatcher, tg_bot, prepared):
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, "Enkys Sun"))

    async with prepared.session() as session:
        membership = await members_repo.get_membership(session, CHAT_ID, 101)
        assert membership.telegram_tag == "Enkys Sun"


async def test_tag_updates_when_it_changes(dispatcher, tg_bot, prepared):
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, "Enkys Sun", update_id=501))
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, "Enkys Moon", update_id=502))

    async with prepared.session() as session:
        membership = await members_repo.get_membership(session, CHAT_ID, 101)
        assert membership.telegram_tag == "Enkys Moon"


async def test_message_without_the_field_keeps_stored_tag(dispatcher, tg_bot, prepared):
    """Найважливіше: старий Bot API не має стирати вже зібрані теги."""
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, "Enkys Sun", update_id=503))
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, ..., update_id=504))

    async with prepared.session() as session:
        membership = await members_repo.get_membership(session, CHAT_ID, 101)
        assert membership.telegram_tag == "Enkys Sun"


async def test_explicit_null_clears_the_tag(dispatcher, tg_bot, prepared):
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, "Enkys Sun", update_id=505))
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, None, update_id=506))

    async with prepared.session() as session:
        membership = await members_repo.get_membership(session, CHAT_ID, 101)
        assert membership.telegram_tag is None


async def test_tags_are_counted_for_stats(dispatcher, tg_bot, prepared):
    await dispatcher.feed_update(tg_bot, make_tagged_update(101, "BanGi Sun", update_id=507))
    await dispatcher.feed_update(tg_bot, make_tagged_update(102, "Igorita Moon", update_id=508))

    async with prepared.session() as session:
        assert await members_repo.count_members_with_telegram_tag(session, CHAT_ID) == 2


async def _set_tag(prepared, user_id: int, tag: str) -> None:
    async with prepared.session() as session:
        await members_repo.ensure_membership(
            session, CHAT_ID, user_id, tag_present=True, telegram_tag=tag
        )
        await session.commit()


async def test_mention_by_telegram_tag(dispatcher, tg_bot, prepared):
    """@sun кличе всіх, у кого в званні Telegram є «Sun»."""
    await _set_tag(prepared, 101, "Enkys Sun")
    await _set_tag(prepared, 102, "BanGi SUN")
    await _set_tag(prepared, 103, "Igorita Moon")

    sender = await feed(dispatcher, tg_bot, "@sun збір", update_id=600)
    assert sender.mentioned_ids == {101, 102}


async def test_telegram_tag_mention_ignores_case(dispatcher, tg_bot, prepared):
    await _set_tag(prepared, 101, "Enkys Sun")

    sender = await feed(dispatcher, tg_bot, "@SUN підйом", update_id=601)
    assert sender.mentioned_ids == {101}


async def test_telegram_tag_mention_matches_part_of_word(dispatcher, tg_bot, prepared):
    await _set_tag(prepared, 102, "Mr Shishka Sun")

    sender = await feed(dispatcher, tg_bot, "@shish агов", update_id=602)
    assert sender.mentioned_ids == {102}


async def test_own_tag_wins_over_telegram_tag(dispatcher, tg_bot, prepared):
    """Власний тег бота створювали свідомо — він має пріоритет."""
    await _set_tag(prepared, 102, "Devs Sun")  # @devs існує як власний тег зі 101 і 103

    sender = await feed(dispatcher, tg_bot, "@devs гляньте", update_id=603)
    assert sender.mentioned_ids == {101, 103}


async def test_telegram_tag_mention_reaches_muted_member(dispatcher, tg_bot, prepared):
    """/mute_me глушить лише @all, адресна згадка має дійти."""
    await _set_tag(prepared, 103, "Ihor Moon")  # 103 має muted_from_all=True

    sender = await feed(dispatcher, tg_bot, "@moon агов", update_id=604)
    assert sender.mentioned_ids == {103}


async def test_telegram_tag_mention_respects_cooldown(dispatcher, tg_bot, prepared):
    await _set_tag(prepared, 101, "Enkys Sun")
    async with prepared.session() as session:
        await chats_repo.update_settings(session, CHAT_ID, cooldown_seconds=600)
        await session.commit()

    first = await feed(dispatcher, tg_bot, "@sun раз", update_id=605)
    assert first.mentioned_ids == {101}

    dispatcher["sender"] = FakeSender()
    second = await feed(dispatcher, tg_bot, "@sun два", update_id=606)
    assert second.calls == []
