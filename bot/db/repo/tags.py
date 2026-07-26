from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import MAX_FUZZY_TAG_MATCHES
from bot.db.models import ChatMember, Tag, TagMember, User
from bot.utils.text import normalize_tag_name


async def get_tag(session: AsyncSession, chat_id: int, name: str) -> Optional[Tag]:
    """Точний збіг без урахування регістру."""
    stmt = select(Tag).where(
        Tag.chat_id == chat_id, Tag.name_lower == normalize_tag_name(name)
    )
    return (await session.execute(stmt)).scalars().first()


def _escape_like(value: str) -> str:
    """`_` і `%` у LIKE — шаблонні символи, а в назвах тегів `_` цілком легальний."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def find_tags(
    session: AsyncSession,
    chat_id: int,
    query: str,
    limit: int = MAX_FUZZY_TAG_MATCHES + 1,
) -> List[Tag]:
    """Пошук тегів за назвою або її частиною, без урахування регістру.

    Три рівні, з зупинкою на першому непорожньому:
    точний збіг → збіг за початком назви → збіг за будь-якою частиною.

    Точний збіг має пріоритет навмисно: інакше тег `@dev` неможливо було б
    покликати окремо, якщо в чаті існує ще й `@devs`.

    Ліміт на один більший за MAX_FUZZY_TAG_MATCHES, щоб той, хто викликає,
    міг відрізнити «рівно стільки» від «забагато, треба уточнити».
    """
    normalized = normalize_tag_name(query)
    if not normalized:
        return []

    exact = await get_tag(session, chat_id, normalized)
    if exact is not None:
        return [exact]

    escaped = _escape_like(normalized)
    for pattern in (f"{escaped}%", f"%{escaped}%"):
        stmt = (
            select(Tag)
            .where(Tag.chat_id == chat_id, Tag.name_lower.like(pattern, escape="\\"))
            .order_by(Tag.name_lower)
            .limit(limit)
        )
        found = list((await session.execute(stmt)).scalars().all())
        if found:
            return found
    return []


async def create_tag(
    session: AsyncSession,
    chat_id: int,
    name: str,
    created_by: Optional[int] = None,
    description: Optional[str] = None,
) -> Tag:
    tag = Tag(
        chat_id=chat_id,
        name=name.strip().lstrip("@"),
        name_lower=normalize_tag_name(name),
        description=description,
        created_by=created_by,
    )
    session.add(tag)
    await session.flush()
    return tag


async def delete_tag(session: AsyncSession, chat_id: int, name: str) -> bool:
    result = await session.execute(
        delete(Tag).where(Tag.chat_id == chat_id, Tag.name_lower == normalize_tag_name(name))
    )
    return bool(result.rowcount)


async def count_tags(session: AsyncSession, chat_id: int) -> int:
    stmt = select(func.count()).select_from(Tag).where(Tag.chat_id == chat_id)
    return int((await session.execute(stmt)).scalar_one())


async def list_tags_with_counts(session: AsyncSession, chat_id: int) -> List[Tuple[Tag, int]]:
    """Теги чату разом із кількістю учасників, які досі в цьому чаті."""
    stmt = (
        select(Tag, func.count(ChatMember.user_id))
        .outerjoin(TagMember, TagMember.tag_id == Tag.id)
        .outerjoin(
            ChatMember,
            (ChatMember.user_id == TagMember.user_id)
            & (ChatMember.chat_id == Tag.chat_id)
            & (ChatMember.is_active.is_(True)),
        )
        .where(Tag.chat_id == chat_id)
        .group_by(Tag.id)
        .order_by(Tag.name_lower)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], int(row[1])) for row in rows]


async def add_tag_member(
    session: AsyncSession, tag_id: int, user_id: int, added_by: Optional[int] = None
) -> bool:
    """True — додали, False — вже був у тезі."""
    existing = await session.get(TagMember, {"tag_id": tag_id, "user_id": user_id})
    if existing is not None:
        return False
    session.add(TagMember(tag_id=tag_id, user_id=user_id, added_by=added_by))
    await session.flush()
    return True


async def remove_tag_member(session: AsyncSession, tag_id: int, user_id: int) -> bool:
    result = await session.execute(
        delete(TagMember).where(TagMember.tag_id == tag_id, TagMember.user_id == user_id)
    )
    return bool(result.rowcount)


async def is_tag_member(session: AsyncSession, tag_id: int, user_id: int) -> bool:
    return await session.get(TagMember, {"tag_id": tag_id, "user_id": user_id}) is not None


async def get_tag_users(session: AsyncSession, tag: Tag, only_active: bool = True) -> List[User]:
    """Учасники тега. За замовчуванням — лише ті, хто досі в чаті.

    muted_from_all тут свідомо не враховуємо: /mute_me глушить тільки @all,
    іменний тег — це адресне звертання, від нього ховатись немає сенсу.
    """
    stmt = (
        select(User)
        .join(TagMember, TagMember.user_id == User.user_id)
        .where(TagMember.tag_id == tag.id, User.is_bot.is_(False))
        .order_by(User.first_name, User.user_id)
    )
    if only_active:
        stmt = stmt.join(
            ChatMember,
            (ChatMember.user_id == User.user_id) & (ChatMember.chat_id == tag.chat_id),
        ).where(ChatMember.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def list_tags_for_user(session: AsyncSession, chat_id: int, user_id: int) -> List[Tag]:
    stmt = (
        select(Tag)
        .join(TagMember, TagMember.tag_id == Tag.id)
        .where(Tag.chat_id == chat_id, TagMember.user_id == user_id)
        .order_by(Tag.name_lower)
    )
    return list((await session.execute(stmt)).scalars().all())
