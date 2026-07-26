from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import MentionCooldown
from bot.db.repo import chats as chats_repo
from bot.db.repo import cooldowns as cooldowns_repo
from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.utils.time import utcnow

CHAT_ID = -1001234567890


async def add_person(
    session: AsyncSession,
    user_id: int,
    name: str,
    chat_id: int = CHAT_ID,
    is_bot: bool = False,
    username: str = None,
) -> None:
    await members_repo.upsert_user(
        session, user_id=user_id, first_name=name, username=username, is_bot=is_bot
    )
    await members_repo.ensure_membership(session, chat_id, user_id)


@pytest.fixture
async def chat(session: AsyncSession, settings):
    return await chats_repo.get_or_create_chat(session, CHAT_ID, "Тестова група", settings)


async def test_get_or_create_is_idempotent_and_updates_title(session, settings):
    first = await chats_repo.get_or_create_chat(session, CHAT_ID, "Стара назва", settings)
    second = await chats_repo.get_or_create_chat(session, CHAT_ID, "Нова назва", settings)
    assert first.chat_id == second.chat_id
    await session.refresh(second)
    assert second.title == "Нова назва"


async def test_upsert_user_refreshes_profile(session, chat):
    await add_person(session, 1, "Влад", username="vlad")
    await members_repo.upsert_user(session, user_id=1, first_name="Владислав", username="vlad2")
    user = await members_repo.get_user(session, 1)
    assert user.first_name == "Владислав"
    assert user.username == "vlad2"


async def test_all_excludes_bots_muted_and_author(session, chat):
    await add_person(session, 1, "Влад")
    await add_person(session, 2, "Оля")
    await add_person(session, 3, "Тихоня")
    await add_person(session, 4, "Робот", is_bot=True)
    await members_repo.set_muted(session, CHAT_ID, 3, True)

    users = await members_repo.list_active_users(session, CHAT_ID, exclude_user_ids=[1])
    assert {user.user_id for user in users} == {2}


async def test_member_who_left_drops_out_of_all(session, chat):
    await add_person(session, 1, "Влад")
    await add_person(session, 2, "Оля")
    await members_repo.set_member_active(session, CHAT_ID, 2, False)

    users = await members_repo.list_active_users(session, CHAT_ID)
    assert {user.user_id for user in users} == {1}


async def test_ensure_membership_keeps_mute_flag(session, chat):
    await add_person(session, 1, "Влад")
    await members_repo.set_muted(session, CHAT_ID, 1, True)
    # Людина написала повідомлення — трекер знову апсертить membership.
    await members_repo.ensure_membership(session, CHAT_ID, 1)

    membership = await members_repo.get_membership(session, CHAT_ID, 1)
    await session.refresh(membership)
    assert membership.muted_from_all is True


async def test_find_user_by_username_is_case_insensitive(session, chat):
    await add_person(session, 1, "Влад", username="VladK")
    found = await members_repo.find_user_by_username(session, "@vladk")
    assert found is not None and found.user_id == 1


async def test_tag_crud(session, chat):
    tag = await tags_repo.create_tag(session, CHAT_ID, "@DevS", created_by=1)
    assert tag.name == "DevS"
    assert tag.name_lower == "devs"

    assert await tags_repo.get_tag(session, CHAT_ID, "devs") is not None
    assert await tags_repo.get_tag(session, CHAT_ID, "DEVS") is not None
    assert await tags_repo.count_tags(session, CHAT_ID) == 1

    assert await tags_repo.delete_tag(session, CHAT_ID, "devs") is True
    assert await tags_repo.delete_tag(session, CHAT_ID, "devs") is False


async def test_tag_membership(session, chat):
    await add_person(session, 1, "Влад")
    await add_person(session, 2, "Оля")
    tag = await tags_repo.create_tag(session, CHAT_ID, "devs")

    assert await tags_repo.add_tag_member(session, tag.id, 1) is True
    assert await tags_repo.add_tag_member(session, tag.id, 1) is False
    await tags_repo.add_tag_member(session, tag.id, 2)

    users = await tags_repo.get_tag_users(session, tag)
    assert {user.user_id for user in users} == {1, 2}

    assert await tags_repo.remove_tag_member(session, tag.id, 2) is True
    users = await tags_repo.get_tag_users(session, tag)
    assert {user.user_id for user in users} == {1}


async def test_tag_users_skip_people_who_left_the_chat(session, chat):
    await add_person(session, 1, "Влад")
    await add_person(session, 2, "Оля")
    tag = await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.add_tag_member(session, tag.id, 1)
    await tags_repo.add_tag_member(session, tag.id, 2)

    await members_repo.set_member_active(session, CHAT_ID, 2, False)
    users = await tags_repo.get_tag_users(session, tag)
    assert {user.user_id for user in users} == {1}


async def test_muted_user_still_reachable_by_named_tag(session, chat):
    await add_person(session, 1, "Тихоня")
    await members_repo.set_muted(session, CHAT_ID, 1, True)
    tag = await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.add_tag_member(session, tag.id, 1)

    users = await tags_repo.get_tag_users(session, tag)
    assert {user.user_id for user in users} == {1}


async def test_purge_user_from_chat_tags(session, chat):
    await add_person(session, 1, "Влад")
    tag = await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.add_tag_member(session, tag.id, 1)

    await members_repo.purge_user_from_chat_tags(session, CHAT_ID, 1)
    assert await tags_repo.get_tag_users(session, tag) == []


async def test_list_tags_with_counts_ignores_departed_members(session, chat):
    await add_person(session, 1, "Влад")
    await add_person(session, 2, "Оля")
    tag = await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.add_tag_member(session, tag.id, 1)
    await tags_repo.add_tag_member(session, tag.id, 2)
    await members_repo.set_member_active(session, CHAT_ID, 2, False)

    rows = await tags_repo.list_tags_with_counts(session, CHAT_ID)
    assert [(row[0].name_lower, row[1]) for row in rows] == [("devs", 1)]


async def test_cooldown_blocks_second_call(session, chat):
    assert await cooldowns_repo.try_acquire(session, CHAT_ID, "all", 600) is None
    wait = await cooldowns_repo.try_acquire(session, CHAT_ID, "all", 600)
    assert wait is not None and 0 < wait <= 600


async def test_cooldown_expires(session, chat):
    await cooldowns_repo.try_acquire(session, CHAT_ID, "all", 600)
    record = await session.get(MentionCooldown, {"chat_id": CHAT_ID, "tag_key": "all"})
    record.last_used_at = utcnow() - timedelta(seconds=601)
    await session.flush()

    assert await cooldowns_repo.try_acquire(session, CHAT_ID, "all", 600) is None


async def test_zero_cooldown_never_blocks(session, chat):
    assert await cooldowns_repo.try_acquire(session, CHAT_ID, "all", 0) is None
    assert await cooldowns_repo.try_acquire(session, CHAT_ID, "all", 0) is None


async def test_cooldown_is_per_tag(session, chat):
    await cooldowns_repo.try_acquire(session, CHAT_ID, "devs", 600)
    assert await cooldowns_repo.try_acquire(session, CHAT_ID, "qa", 600) is None


async def test_chat_migration_moves_tags_and_members(session, settings, chat):
    new_chat_id = -1009999999999
    await add_person(session, 1, "Влад")
    tag = await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.add_tag_member(session, tag.id, 1)
    await cooldowns_repo.try_acquire(session, CHAT_ID, "devs", 600)

    assert await chats_repo.migrate_chat_id(session, CHAT_ID, new_chat_id) is True

    assert await chats_repo.get_chat(session, CHAT_ID) is None
    moved_tag = await tags_repo.get_tag(session, new_chat_id, "devs")
    assert moved_tag is not None
    assert {user.user_id for user in await tags_repo.get_tag_users(session, moved_tag)} == {1}
    users = await members_repo.list_active_users(session, new_chat_id)
    assert {user.user_id for user in users} == {1}


async def test_migration_of_unknown_chat_is_noop(session, settings):
    assert await chats_repo.migrate_chat_id(session, -1, -2) is False


async def test_find_tags_is_case_insensitive(session, chat):
    await tags_repo.create_tag(session, CHAT_ID, "DevOps")

    for query in ("DEVOPS", "devops", "@DeVoPs", "DevOps"):
        found = await tags_repo.find_tags(session, CHAT_ID, query)
        assert [tag.name for tag in found] == ["DevOps"], query


async def test_exact_match_wins_over_prefix(session, chat):
    """Інакше @dev неможливо покликати окремо, поки в чаті є @devs."""
    await tags_repo.create_tag(session, CHAT_ID, "dev")
    await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.create_tag(session, CHAT_ID, "devops")

    assert [tag.name_lower for tag in await tags_repo.find_tags(session, CHAT_ID, "dev")] == ["dev"]


async def test_prefix_match_returns_all(session, chat):
    await tags_repo.create_tag(session, CHAT_ID, "devs")
    await tags_repo.create_tag(session, CHAT_ID, "devops")
    await tags_repo.create_tag(session, CHAT_ID, "qa")

    found = await tags_repo.find_tags(session, CHAT_ID, "dev")
    assert [tag.name_lower for tag in found] == ["devops", "devs"]


async def test_substring_match_only_when_no_prefix_match(session, chat):
    await tags_repo.create_tag(session, CHAT_ID, "backend")
    await tags_repo.create_tag(session, CHAT_ID, "frontend")

    # "end" не є початком жодної назви — вмикається пошук за підрядком.
    found = await tags_repo.find_tags(session, CHAT_ID, "end")
    assert {tag.name_lower for tag in found} == {"backend", "frontend"}

    # А "front" є префіксом, тож підрядковий рівень не спрацьовує.
    found = await tags_repo.find_tags(session, CHAT_ID, "front")
    assert [tag.name_lower for tag in found] == ["frontend"]


async def test_underscore_is_not_a_like_wildcard(session, chat):
    await tags_repo.create_tag(session, CHAT_ID, "qa_team")
    await tags_repo.create_tag(session, CHAT_ID, "qaxteam")

    found = await tags_repo.find_tags(session, CHAT_ID, "a_t")
    assert [tag.name_lower for tag in found] == ["qa_team"]


async def test_find_tags_is_scoped_to_chat(session, settings, chat):
    other_chat = -100999
    await chats_repo.get_or_create_chat(session, other_chat, "Інший", settings)
    await tags_repo.create_tag(session, other_chat, "devs")

    assert await tags_repo.find_tags(session, CHAT_ID, "dev") == []


async def test_find_tags_respects_limit(session, chat):
    for index in range(8):
        await tags_repo.create_tag(session, CHAT_ID, f"dev{index}")

    assert len(await tags_repo.find_tags(session, CHAT_ID, "dev", limit=3)) == 3


async def test_find_tags_on_empty_query(session, chat):
    await tags_repo.create_tag(session, CHAT_ID, "devs")
    assert await tags_repo.find_tags(session, CHAT_ID, "  @ ") == []
