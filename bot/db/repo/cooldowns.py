from __future__ import annotations

from typing import Optional

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import MentionCooldown
from bot.utils.time import ensure_utc, utcnow


async def try_acquire(
    session: AsyncSession,
    chat_id: int,
    tag_key: str,
    cooldown_seconds: int,
    user_id: Optional[int] = None,
) -> Optional[float]:
    """Позначає тег як щойно використаний.

    Повертає None, якщо виклик дозволено, або кількість секунд, які ще треба чекати.
    """
    if cooldown_seconds <= 0:
        return None

    now = utcnow()
    existing = await session.get(MentionCooldown, {"chat_id": chat_id, "tag_key": tag_key})
    if existing is not None:
        last_used = ensure_utc(existing.last_used_at)
        if last_used is not None:
            elapsed = (now - last_used).total_seconds()
            if elapsed < cooldown_seconds:
                return cooldown_seconds - elapsed

    stmt = (
        sqlite_insert(MentionCooldown)
        .values(chat_id=chat_id, tag_key=tag_key, last_used_at=now, last_used_by=user_id)
        .on_conflict_do_update(
            index_elements=[MentionCooldown.chat_id, MentionCooldown.tag_key],
            set_={"last_used_at": now, "last_used_by": user_id},
        )
    )
    await session.execute(stmt)
    return None


async def reset(session: AsyncSession, chat_id: int, tag_key: Optional[str] = None) -> None:
    stmt = delete(MentionCooldown).where(MentionCooldown.chat_id == chat_id)
    if tag_key is not None:
        stmt = stmt.where(MentionCooldown.tag_key == tag_key)
    await session.execute(stmt)
