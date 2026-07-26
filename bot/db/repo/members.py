from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ChatMember, TagMember, User
from bot.utils.time import utcnow


async def upsert_user(
    session: AsyncSession,
    user_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    is_bot: bool = False,
) -> None:
    """Оновлює профіль користувача. Ім'я міняється часто — тримаємо свіжим."""
    stmt = (
        sqlite_insert(User)
        .values(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            is_bot=is_bot,
            updated_at=utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[User.user_id],
            set_={
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "is_bot": is_bot,
                "updated_at": utcnow(),
            },
        )
    )
    await session.execute(stmt)


async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def find_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    """Пошук за @username серед уже відомих боту людей (регістронезалежний)."""
    normalized = username.lstrip("@").lower()
    stmt = select(User).where(func.lower(User.username) == normalized).limit(1)
    return (await session.execute(stmt)).scalars().first()


async def ensure_membership(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    touch: bool = True,
    tag_present: bool = False,
    telegram_tag: Optional[str] = None,
) -> None:
    """Фіксує присутність у чаті. muted_from_all свідомо не чіпаємо.

    tag_present відрізняє «Telegram не надсилає тег» від «тега справді немає»:
    у першому випадку збережене значення чіпати не можна, у другому — треба
    стерти.
    """
    now = utcnow()
    updates: dict = {"is_active": True}
    if touch:
        updates["last_seen_at"] = now
    if tag_present:
        updates["telegram_tag"] = telegram_tag
    stmt = (
        sqlite_insert(ChatMember)
        .values(
            chat_id=chat_id,
            user_id=user_id,
            is_active=True,
            muted_from_all=False,
            joined_at=now,
            last_seen_at=now if touch else None,
            telegram_tag=telegram_tag if tag_present else None,
        )
        .on_conflict_do_update(
            index_elements=[ChatMember.chat_id, ChatMember.user_id],
            set_=updates,
        )
    )
    await session.execute(stmt)


async def set_member_active(
    session: AsyncSession, chat_id: int, user_id: int, is_active: bool
) -> None:
    await session.execute(
        update(ChatMember)
        .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
        .values(is_active=is_active)
    )


async def get_membership(
    session: AsyncSession, chat_id: int, user_id: int
) -> Optional[ChatMember]:
    return await session.get(ChatMember, {"chat_id": chat_id, "user_id": user_id})


async def set_muted(session: AsyncSession, chat_id: int, user_id: int, muted: bool) -> None:
    await session.execute(
        update(ChatMember)
        .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
        .values(muted_from_all=muted)
    )


async def list_active_users(
    session: AsyncSession,
    chat_id: int,
    exclude_muted: bool = True,
    exclude_bots: bool = True,
    exclude_user_ids: Optional[Iterable[int]] = None,
) -> List[User]:
    """Учасники для розкриття @all."""
    stmt = (
        select(User)
        .join(ChatMember, ChatMember.user_id == User.user_id)
        .where(ChatMember.chat_id == chat_id, ChatMember.is_active.is_(True))
        .order_by(User.first_name, User.user_id)
    )
    if exclude_muted:
        stmt = stmt.where(ChatMember.muted_from_all.is_(False))
    if exclude_bots:
        stmt = stmt.where(User.is_bot.is_(False))
    excluded = set(exclude_user_ids or ())
    if excluded:
        stmt = stmt.where(User.user_id.notin_(excluded))
    return list((await session.execute(stmt)).scalars().all())


async def count_active_members(session: AsyncSession, chat_id: int) -> int:
    stmt = select(func.count()).select_from(ChatMember).where(
        ChatMember.chat_id == chat_id, ChatMember.is_active.is_(True)
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_muted_members(session: AsyncSession, chat_id: int) -> int:
    stmt = select(func.count()).select_from(ChatMember).where(
        ChatMember.chat_id == chat_id,
        ChatMember.is_active.is_(True),
        ChatMember.muted_from_all.is_(True),
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_members_with_telegram_tag(session: AsyncSession, chat_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(ChatMember)
        .where(
            ChatMember.chat_id == chat_id,
            ChatMember.is_active.is_(True),
            ChatMember.telegram_tag.is_not(None),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def list_members_with_telegram_tags(
    session: AsyncSession,
    chat_id: int,
    exclude_bots: bool = True,
) -> List[Tuple[User, str]]:
    """Активні учасники, у яких є рідний тег Telegram, разом із самим тегом.

    Теги — це довільні фрази («Mr Shishka Sun»), тож пословний пошук зручніше
    робити в Python, ніж вигадувати SQL. Учасників з тегами — десятки, максимум
    сотні, тож тягнути їх у пам'ять дешевше за складний запит.
    """
    stmt = (
        select(User, ChatMember.telegram_tag)
        .join(ChatMember, ChatMember.user_id == User.user_id)
        .where(
            ChatMember.chat_id == chat_id,
            ChatMember.is_active.is_(True),
            ChatMember.telegram_tag.is_not(None),
        )
        .order_by(User.first_name, User.user_id)
    )
    if exclude_bots:
        stmt = stmt.where(User.is_bot.is_(False))
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all() if row[1]]


async def filter_active_in_chat(
    session: AsyncSession, chat_id: int, user_ids: Sequence[int]
) -> set:
    """З переданих id лишає тих, хто зараз активний у чаті."""
    if not user_ids:
        return set()
    stmt = select(ChatMember.user_id).where(
        ChatMember.chat_id == chat_id,
        ChatMember.is_active.is_(True),
        ChatMember.user_id.in_(list(user_ids)),
    )
    return set((await session.execute(stmt)).scalars().all())


async def purge_user_from_chat_tags(
    session: AsyncSession, chat_id: int, user_id: int
) -> None:
    """Людина вийшла з чату — прибираємо її з тегів саме цього чату."""
    from bot.db.models import Tag  # локальний імпорт, щоб не плодити циклічні залежності

    tag_ids = select(Tag.id).where(Tag.chat_id == chat_id)
    await session.execute(
        TagMember.__table__.delete().where(
            TagMember.user_id == user_id, TagMember.tag_id.in_(tag_ids)
        )
    )
