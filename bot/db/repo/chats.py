from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import Chat, ChatMember, MentionCooldown, Tag
from bot.utils.time import utcnow

logger = logging.getLogger(__name__)


async def get_chat(session: AsyncSession, chat_id: int) -> Optional[Chat]:
    return await session.get(Chat, chat_id)


async def get_or_create_chat(
    session: AsyncSession,
    chat_id: int,
    title: Optional[str],
    settings: Settings,
) -> Chat:
    """Створює запис чату з дефолтами з .env; наявний чат лише оновлює назву."""
    stmt = (
        sqlite_insert(Chat)
        .values(
            chat_id=chat_id,
            title=title,
            all_policy=settings.default_all_policy,
            tag_policy=settings.default_tag_policy,
            cooldown_seconds=settings.default_cooldown_seconds,
            timezone=settings.default_timezone,
            quiet_hours_enabled=settings.default_quiet_hours_enabled,
            quiet_start=settings.default_quiet_start,
            quiet_end=settings.default_quiet_end,
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[Chat.chat_id],
            set_={"title": title, "is_active": True, "updated_at": utcnow()},
        )
    )
    await session.execute(stmt)
    chat = await session.get(Chat, chat_id)
    assert chat is not None  # щойно вставили або оновили
    return chat


async def set_chat_active(session: AsyncSession, chat_id: int, is_active: bool) -> None:
    await session.execute(
        update(Chat)
        .where(Chat.chat_id == chat_id)
        .values(is_active=is_active, updated_at=utcnow())
    )


async def update_settings(session: AsyncSession, chat_id: int, **values: object) -> None:
    if not values:
        return
    await session.execute(
        update(Chat).where(Chat.chat_id == chat_id).values(updated_at=utcnow(), **values)
    )


async def migrate_chat_id(session: AsyncSession, old_chat_id: int, new_chat_id: int) -> bool:
    """Група стала супергрупою — Telegram видає новий chat_id, старі дані треба перенести.

    Повертає True, якщо перенесення відбулося.
    """
    old_chat = await session.get(Chat, old_chat_id)
    if old_chat is None:
        return False

    existing_new = await session.get(Chat, new_chat_id)
    if existing_new is None:
        # Створюємо чат-приймач з тими самими налаштуваннями.
        session.add(
            Chat(
                chat_id=new_chat_id,
                title=old_chat.title,
                all_policy=old_chat.all_policy,
                tag_policy=old_chat.tag_policy,
                cooldown_seconds=old_chat.cooldown_seconds,
                timezone=old_chat.timezone,
                quiet_hours_enabled=old_chat.quiet_hours_enabled,
                quiet_start=old_chat.quiet_start,
                quiet_end=old_chat.quiet_end,
                is_active=True,
            )
        )
        await session.flush()

    # Переносимо тільки те, чого ще немає в новому чаті, щоб не впертися в UNIQUE.
    existing_tag_names = set(
        (
            await session.execute(select(Tag.name_lower).where(Tag.chat_id == new_chat_id))
        ).scalars()
    )
    old_tags = (
        (await session.execute(select(Tag).where(Tag.chat_id == old_chat_id))).scalars().all()
    )
    for tag in old_tags:
        if tag.name_lower not in existing_tag_names:
            tag.chat_id = new_chat_id

    existing_member_ids = set(
        (
            await session.execute(
                select(ChatMember.user_id).where(ChatMember.chat_id == new_chat_id)
            )
        ).scalars()
    )
    old_members = (
        (await session.execute(select(ChatMember).where(ChatMember.chat_id == old_chat_id)))
        .scalars()
        .all()
    )
    for member in old_members:
        if member.user_id not in existing_member_ids:
            member.chat_id = new_chat_id

    await session.flush()

    # Решта (дублі тегів/учасників і кулдауни) піде за старим чатом по ON DELETE CASCADE.
    await session.execute(delete(MentionCooldown).where(MentionCooldown.chat_id == old_chat_id))
    session.expunge(old_chat)
    await session.execute(delete(Chat).where(Chat.chat_id == old_chat_id))
    logger.info("Чат %s мігрував у %s", old_chat_id, new_chat_id)
    return True
