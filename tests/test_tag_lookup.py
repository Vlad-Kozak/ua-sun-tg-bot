from __future__ import annotations

from types import SimpleNamespace
from typing import List

from bot.db.repo import chats as chats_repo
from bot.db.repo import tags as tags_repo
from bot.services.tag_lookup import resolve_tag_or_reply

CHAT_ID = -100555


class FakeMessage:
    """Резолверу потрібні лише chat.id і reply — повний Message тут зайвий."""

    def __init__(self, chat_id: int = CHAT_ID) -> None:
        self.chat = SimpleNamespace(id=chat_id)
        self.replies: List[str] = []

    async def reply(self, text: str, **kwargs) -> None:
        self.replies.append(text)


async def prepare(session, settings, *names):
    await chats_repo.get_or_create_chat(session, CHAT_ID, "Тест", settings)
    for name in names:
        await tags_repo.create_tag(session, CHAT_ID, name)


async def test_exact_name_resolves_silently(session, settings):
    await prepare(session, settings, "devs")
    message = FakeMessage()

    tag = await resolve_tag_or_reply(session, message, "DEVS")
    assert tag is not None and tag.name_lower == "devs"
    assert message.replies == []


async def test_unique_partial_name_resolves(session, settings):
    await prepare(session, settings, "developers", "qa")
    message = FakeMessage()

    tag = await resolve_tag_or_reply(session, message, "devel")
    assert tag is not None and tag.name_lower == "developers"
    assert message.replies == []


async def test_ambiguous_partial_name_asks_to_clarify(session, settings):
    await prepare(session, settings, "devs", "devops")
    message = FakeMessage()

    assert await resolve_tag_or_reply(session, message, "dev") is None
    assert len(message.replies) == 1
    reply = message.replies[0]
    assert "@devs" in reply and "@devops" in reply
    assert "Уточніть" in reply


async def test_missing_tag_reports_absence(session, settings):
    await prepare(session, settings, "devs")
    message = FakeMessage()

    assert await resolve_tag_or_reply(session, message, "qa") is None
    assert "немає в цьому чаті" in message.replies[0]


async def test_reply_escapes_html_in_user_input(session, settings):
    await prepare(session, settings, "devs")
    message = FakeMessage()

    await resolve_tag_or_reply(session, message, "<b>qa</b>")
    assert "<b>" not in message.replies[0]
    assert "&lt;b&gt;" in message.replies[0]
