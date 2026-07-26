"""Виклик людей за рідним тегом Telegram: @sun кличе всіх зі «Sun» у званні.

Правила ті самі, що для власних тегів бота: без урахування регістру й з
пошуком за частиною.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.services.tag_lookup import find_users_by_telegram_tag
from bot.utils.text import phrase_match_level

CHAT_ID = -1003333333333

PEOPLE = [
    (1, "Dimon", "Mr Shishka Sun"),
    (2, "Andrusha", "Enkys Sun"),
    (3, "Yura", "BanGi SUN"),
    (4, "Alexey", "Aroschka Moon"),
    (5, "Nazar", "rydia ЛІДЕР MOON"),
    (6, "MaRk", None),
]


@pytest_asyncio.fixture
async def chat(session, settings):
    await chats_repo.get_or_create_chat(session, CHAT_ID, "Клан", settings)
    for user_id, name, tag in PEOPLE:
        await members_repo.upsert_user(session, user_id=user_id, first_name=name)
        await members_repo.ensure_membership(
            session, CHAT_ID, user_id, tag_present=tag is not None, telegram_tag=tag
        )
    return CHAT_ID


async def names(session, query, **kwargs):
    users = await find_users_by_telegram_tag(session, CHAT_ID, query, **kwargs)
    return sorted(user.first_name for user in users)


async def test_calls_everyone_with_the_word(session, chat):
    assert await names(session, "sun") == ["Andrusha", "Dimon", "Yura"]
    assert await names(session, "moon") == ["Alexey", "Nazar"]


async def test_case_is_ignored(session, chat):
    assert await names(session, "SUN") == await names(session, "sun")
    assert await names(session, "SuN") == await names(session, "sun")
    assert await names(session, "@Sun") == await names(session, "sun")


async def test_partial_word_works(session, chat):
    assert await names(session, "shish") == ["Dimon"]
    assert await names(session, "enky") == ["Andrusha"]


async def test_cyrillic_tags_are_searchable(session, chat):
    assert await names(session, "лідер") == ["Nazar"]


async def test_author_is_excluded(session, chat):
    assert await names(session, "sun", exclude_user_ids=[1]) == ["Andrusha", "Yura"]


async def test_people_without_tags_are_never_matched(session, chat):
    assert "MaRk" not in await names(session, "mark")


async def test_unknown_query_returns_nobody(session, chat):
    assert await names(session, "jupiter") == []


async def test_departed_member_drops_out(session, chat):
    await members_repo.set_member_active(session, CHAT_ID, 2, False)
    assert await names(session, "sun") == ["Dimon", "Yura"]


async def test_exact_word_wins_over_substring(session, settings):
    """@sun не має тягнути «Sunrise», поки є люди зі словом «Sun»."""
    await chats_repo.get_or_create_chat(session, CHAT_ID, "Клан", settings)
    for user_id, name, tag in [(10, "Точний", "Team Sun"), (11, "Ширший", "Sunrise Crew")]:
        await members_repo.upsert_user(session, user_id=user_id, first_name=name)
        await members_repo.ensure_membership(
            session, CHAT_ID, user_id, tag_present=True, telegram_tag=tag
        )

    assert await names(session, "sun") == ["Точний"]


@pytest.mark.parametrize(
    ("query", "phrase", "expected"),
    [
        ("sun", "Mr Shishka Sun", 1),
        ("SUN", "BanGi SUN", 1),
        ("shish", "Mr Shishka Sun", 2),
        ("ry", "rydia ЛІДЕР MOON", 2),
        ("дер", "rydia ЛІДЕР MOON", 3),
        ("jupiter", "Mr Shishka Sun", None),
        ("sun", "", None),
        ("", "Mr Shishka Sun", None),
    ],
)
def test_match_levels(query, phrase, expected):
    assert phrase_match_level(query, phrase) == expected
