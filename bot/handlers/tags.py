from __future__ import annotations

import logging
from typing import List, Tuple

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import MAX_TAGS_PER_CHAT
from bot.db.models import Chat
from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.services.policy import AdminCache, check_policy
from bot.services.tag_lookup import resolve_tag_or_reply
from bot.utils.entities import command_args, extract_mentioned_people, first_arg
from bot.utils.replies import safe_reply
from bot.utils.text import display_name, normalize_tag_name, validate_tag_name

logger = logging.getLogger(__name__)


NO_RIGHTS = (
    "Керувати тегами в цьому чаті можуть лише адміни.\n"
    "Змінити: <code>/settings tag_policy members</code>"
)


async def _ensure_can_manage(
    bot: Bot, admin_cache: AdminCache, message: Message, chat: Chat
) -> bool:
    if await check_policy(bot, admin_cache, message, chat.tag_policy):
        return True
    await safe_reply(message, NO_RIGHTS)
    return False


async def _resolve_targets(
    session: AsyncSession, message: Message
) -> Tuple[List[Tuple[int, str]], List[str]]:
    """Повертає (знайдені як (user_id, ім'я), невідомі @username)."""
    mentioned = extract_mentioned_people(message)
    resolved: List[Tuple[int, str]] = []
    unknown: List[str] = []
    seen = set()

    for user in mentioned.users:
        if user.id in seen:
            continue
        seen.add(user.id)
        await members_repo.upsert_user(
            session,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            is_bot=user.is_bot,
        )
        await members_repo.ensure_membership(session, message.chat.id, user.id, touch=False)
        resolved.append(
            (user.id, display_name(user.first_name, user.last_name, user.username, user.id))
        )

    for username in mentioned.usernames:
        user = await members_repo.find_user_by_username(session, username)
        if user is None:
            unknown.append(username)
            continue
        if user.user_id in seen:
            continue
        seen.add(user.user_id)
        await members_repo.ensure_membership(session, message.chat.id, user.user_id, touch=False)
        resolved.append(
            (
                user.user_id,
                display_name(user.first_name, user.last_name, user.username, user.user_id),
            )
        )

    return resolved, unknown


async def cmd_tags(message: Message, session: AsyncSession) -> None:
    rows = await tags_repo.list_tags_with_counts(session, message.chat.id)
    if not rows:
        await safe_reply(message, 
            "Тегів поки немає. Створити: <code>/tag_create devs Розробники</code>\n"
            "А <code>@all</code> працює й без налаштувань."
        )
        return

    lines = ["<b>Теги цього чату</b>"]
    for tag, count in rows:
        suffix = f" — {tag.description}" if tag.description else ""
        lines.append(f"• <code>@{tag.name}</code> ({count}){suffix}")
    lines.append("\nХто в тезі: <code>/tag_info назва</code>")
    await safe_reply(message, "\n".join(lines))


async def cmd_tag_info(message: Message, session: AsyncSession) -> None:
    name = first_arg(message)
    if not name:
        await safe_reply(message, "Вкажи назву: <code>/tag_info devs</code>")
        return

    tag = await resolve_tag_or_reply(session, message, name)
    if tag is None:
        return

    users = await tags_repo.get_tag_users(session, tag)
    if not users:
        await safe_reply(message, 
            f"У тезі <code>@{tag.name}</code> поки нікого.\n"
            f"Додати: <code>/tag_add {tag.name} @хтось</code> або реплаєм на повідомлення."
        )
        return

    lines = [f"<b>@{tag.name}</b> — {len(users)}"]
    if tag.description:
        lines.append(f"<i>{tag.description}</i>")
    for user in users:
        lines.append(
            f"• {display_name(user.first_name, user.last_name, user.username, user.user_id)}"
        )
    await safe_reply(message, "\n".join(lines))


async def cmd_tag_create(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
) -> None:
    if not await _ensure_can_manage(bot, admin_cache, message, db_chat):
        return

    args = command_args(message)
    if not args:
        await safe_reply(message, "Вкажи назву: <code>/tag_create devs Розробники</code>")
        return

    name = args[0]
    error = validate_tag_name(name)
    if error:
        await safe_reply(message, error)
        return

    if await tags_repo.count_tags(session, message.chat.id) >= MAX_TAGS_PER_CHAT:
        await safe_reply(message, f"Досягнуто ліміту в {MAX_TAGS_PER_CHAT} тегів на чат.")
        return

    if await tags_repo.get_tag(session, message.chat.id, name) is not None:
        await safe_reply(message, f"Тег <code>@{normalize_tag_name(name)}</code> уже існує.")
        return

    description = " ".join(args[1:])[:256] or None
    author_id = message.from_user.id if message.from_user else None
    try:
        tag = await tags_repo.create_tag(
            session, message.chat.id, name, created_by=author_id, description=description
        )
    except IntegrityError:
        # Хтось створив такий самий тег між перевіркою і вставкою.
        await session.rollback()
        await safe_reply(message, f"Тег <code>@{normalize_tag_name(name)}</code> уже існує.")
        return

    await safe_reply(message, 
        f"Створено <code>@{tag.name}</code>.\n"
        f"Тепер додай людей: <code>/tag_add {tag.name} @хтось</code> "
        f"або реплаєм на їхнє повідомлення."
    )


async def cmd_tag_delete(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
) -> None:
    if not await _ensure_can_manage(bot, admin_cache, message, db_chat):
        return

    name = first_arg(message)
    if not name:
        await safe_reply(message, "Вкажи назву: <code>/tag_delete devs</code>")
        return

    tag = await resolve_tag_or_reply(session, message, name)
    if tag is None:
        return

    await tags_repo.delete_tag(session, message.chat.id, tag.name_lower)
    await safe_reply(message, f"Тег <code>@{tag.name}</code> видалено.")


async def cmd_tag_add(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
) -> None:
    if not await _ensure_can_manage(bot, admin_cache, message, db_chat):
        return

    name = first_arg(message)
    if not name:
        await safe_reply(message, 
            "Вкажи тег і кого додати:\n"
            "<code>/tag_add devs @vasyl</code>\n"
            "або реплаєм на повідомлення: <code>/tag_add devs</code>"
        )
        return

    tag = await resolve_tag_or_reply(session, message, name)
    if tag is None:
        return

    resolved, unknown = await _resolve_targets(session, message)
    if not resolved and not unknown:
        await safe_reply(message, 
            "Не зрозумів, кого додати. Або реплаєм на повідомлення людини, "
            "або <code>@username</code> у команді."
        )
        return

    author_id = message.from_user.id if message.from_user else None
    added, already = [], []
    for user_id, name_display in resolved:
        if await tags_repo.add_tag_member(session, tag.id, user_id, added_by=author_id):
            added.append(name_display)
        else:
            already.append(name_display)

    lines = []
    if added:
        lines.append(f"Додано в <code>@{tag.name}</code>: {', '.join(added)}")
    if already:
        lines.append(f"Уже були: {', '.join(already)}")
    if unknown:
        lines.append(
            "Не знаю таких: "
            + ", ".join(f"@{name}" for name in unknown)
            + ". Хай напишуть щось у чат — і я їх запам'ятаю."
        )
    await safe_reply(message, "\n".join(lines))


async def cmd_tag_remove(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
) -> None:
    if not await _ensure_can_manage(bot, admin_cache, message, db_chat):
        return

    name = first_arg(message)
    if not name:
        await safe_reply(message, "Вкажи тег і кого прибрати: <code>/tag_remove devs @vasyl</code>")
        return

    tag = await resolve_tag_or_reply(session, message, name)
    if tag is None:
        return

    resolved, unknown = await _resolve_targets(session, message)
    if not resolved and not unknown:
        await safe_reply(
            message, "Не зрозумів, кого прибрати. Вкажи <code>@username</code> або реплай."
        )
        return

    removed, missing = [], []
    for user_id, name_display in resolved:
        if await tags_repo.remove_tag_member(session, tag.id, user_id):
            removed.append(name_display)
        else:
            missing.append(name_display)

    lines = []
    if removed:
        lines.append(f"Прибрано з <code>@{tag.name}</code>: {', '.join(removed)}")
    if missing:
        lines.append(f"Не були в тезі: {', '.join(missing)}")
    if unknown:
        lines.append("Не знаю таких: " + ", ".join(f"@{name}" for name in unknown))
    await safe_reply(message, "\n".join(lines))


def build_router() -> Router:
    router = Router(name="tags")
    router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

    router.message.register(cmd_tags, Command("tags"))
    router.message.register(cmd_tag_info, Command("tag_info"))
    router.message.register(cmd_tag_create, Command("tag_create"))
    router.message.register(cmd_tag_delete, Command("tag_delete", "tag_del"))
    router.message.register(cmd_tag_add, Command("tag_add"))
    router.message.register(cmd_tag_remove, Command("tag_remove", "tag_rm"))
    return router
