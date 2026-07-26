from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.services.tag_lookup import resolve_tag_or_reply
from bot.utils.entities import first_arg
from bot.utils.replies import safe_reply


async def cmd_join(message: Message, session: AsyncSession) -> None:
    """Самозапис у тег дозволений завжди — політика чату стосується чужих тегів."""
    if message.from_user is None:
        return
    name = first_arg(message)
    if not name:
        await safe_reply(message, "У який тег? <code>/join devs</code>")
        return

    tag = await resolve_tag_or_reply(session, message, name)
    if tag is None:
        return

    added = await tags_repo.add_tag_member(
        session, tag.id, message.from_user.id, added_by=message.from_user.id
    )
    if added:
        await safe_reply(message, f"Ти в <code>@{tag.name}</code>.")
    else:
        await safe_reply(message, f"Ти вже в <code>@{tag.name}</code>.")


async def cmd_leave(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    name = first_arg(message)
    if not name:
        await safe_reply(message, "З якого тега? <code>/leave devs</code>")
        return

    tag = await resolve_tag_or_reply(session, message, name)
    if tag is None:
        return

    removed = await tags_repo.remove_tag_member(session, tag.id, message.from_user.id)
    if removed:
        await safe_reply(message, f"Ти більше не в <code>@{tag.name}</code>.")
    else:
        await safe_reply(message, f"Тебе й не було в <code>@{tag.name}</code>.")


async def cmd_me(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    user_tags = await tags_repo.list_tags_for_user(session, message.chat.id, user_id)
    membership = await members_repo.get_membership(session, message.chat.id, user_id)

    lines = []
    if user_tags:
        lines.append("Твої теги: " + ", ".join(f"<code>@{tag.name}</code>" for tag in user_tags))
    else:
        lines.append("Ти поки в жодному тезі. Вписатись: <code>/join назва</code>")

    if membership is not None and membership.muted_from_all:
        lines.append("<code>@all</code> тебе не чіпає (<code>/unmute_me</code> — повернути).")
    else:
        lines.append("<code>@all</code> тебе кличе (<code>/mute_me</code> — вимкнути).")

    await safe_reply(message, "\n".join(lines))


async def cmd_mute_me(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    await members_repo.ensure_membership(session, message.chat.id, message.from_user.id)
    await members_repo.set_muted(session, message.chat.id, message.from_user.id, True)
    await safe_reply(message, 
        "Готово: <code>@all</code> тебе більше не чіпає.\n"
        "Іменні теги працюють як раніше — це адресне звертання."
    )


async def cmd_unmute_me(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    await members_repo.ensure_membership(session, message.chat.id, message.from_user.id)
    await members_repo.set_muted(session, message.chat.id, message.from_user.id, False)
    await safe_reply(message, "Повернув тебе в <code>@all</code>.")


async def cmd_forget_me(message: Message, session: AsyncSession) -> None:
    """Прибирає користувача з усіх тегів чату й зі списку @all."""
    if message.from_user is None:
        return
    user_id = message.from_user.id
    await members_repo.purge_user_from_chat_tags(session, message.chat.id, user_id)
    await members_repo.set_member_active(session, message.chat.id, user_id, False)
    await safe_reply(message, 
        "Прибрав тебе з усіх тегів цього чату і зі списку <code>@all</code>.\n"
        "Наступне твоє повідомлення поверне тебе в список — тоді краще <code>/mute_me</code>."
    )


def build_router() -> Router:
    router = Router(name="membership")
    router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

    router.message.register(cmd_join, Command("join"))
    router.message.register(cmd_leave, Command("leave"))
    router.message.register(cmd_me, Command("me"))
    router.message.register(cmd_mute_me, Command("mute_me"))
    router.message.register(cmd_unmute_me, Command("unmute_me"))
    router.message.register(cmd_forget_me, Command("forget_me"))
    return router
