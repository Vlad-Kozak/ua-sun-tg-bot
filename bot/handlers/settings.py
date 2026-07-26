from __future__ import annotations

import logging
from typing import List

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import POLICY_ADMINS, POLICY_MEMBERS
from bot.db.models import Chat
from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.services.policy import AdminCache, is_admin, is_quiet_now
from bot.utils.entities import command_args
from bot.utils.replies import safe_reply
from bot.utils.time import format_duration

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


USAGE = """<b>Налаштування чату</b>

<code>/settings all_policy admins|members</code> — хто може кликати <code>@all</code>
<code>/settings tag_policy admins|members</code> — хто може створювати й редагувати теги
<code>/settings cooldown 600</code> — пауза між викликами одного тега, секунди (0 — вимкнути)
<code>/settings timezone Europe/Kyiv</code> — для тихих годин
<code>/settings quiet 23 8</code> — тихі години (згадки без звуку)
<code>/settings quiet off</code> — вимкнути тихі години"""

logger = logging.getLogger(__name__)

POLICY_LABELS = {POLICY_ADMINS: "лише адміни", POLICY_MEMBERS: "усі учасники"}


def _render(chat: Chat) -> str:
    quiet = (
        f"{chat.quiet_start:02d}:00–{chat.quiet_end:02d}:00"
        if chat.quiet_hours_enabled
        else "вимкнено"
    )
    cooldown = format_duration(chat.cooldown_seconds) if chat.cooldown_seconds else "без паузи"
    now_quiet = " (зараз тихо)" if is_quiet_now(chat) else ""
    return (
        "<b>Поточні налаштування</b>\n"
        f"• <code>@all</code> може кликати: {POLICY_LABELS.get(chat.all_policy, chat.all_policy)}\n"
        f"• теги може редагувати: {POLICY_LABELS.get(chat.tag_policy, chat.tag_policy)}\n"
        f"• пауза між викликами тега: {cooldown}\n"
        f"• таймзона: {chat.timezone}\n"
        f"• тихі години: {quiet}{now_quiet}\n\n"
        f"{USAGE}"
    )


async def cmd_settings(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
) -> None:
    args = command_args(message)
    if not args:
        await safe_reply(message, _render(db_chat))
        return

    if not await is_admin(bot, admin_cache, message):
        await safe_reply(message, "Змінювати налаштування можуть лише адміни чату.")
        return

    key = args[0].lower()
    values = args[1:]

    if key in {"all_policy", "tag_policy"}:
        if not values or values[0].lower() not in {POLICY_ADMINS, POLICY_MEMBERS}:
            await safe_reply(message, "Значення: <code>admins</code> або <code>members</code>.")
            return
        await chats_repo.update_settings(session, message.chat.id, **{key: values[0].lower()})
        await safe_reply(message, f"Готово: {key} = {values[0].lower()}")
        return

    if key == "cooldown":
        if not values or not values[0].lstrip("-").isdigit():
            await safe_reply(message, "Вкажи кількість секунд: <code>/settings cooldown 600</code>")
            return
        seconds = int(values[0])
        if seconds < 0 or seconds > 86400:
            await safe_reply(message, "Пауза має бути від 0 до 86400 секунд.")
            return
        await chats_repo.update_settings(session, message.chat.id, cooldown_seconds=seconds)
        await safe_reply(message, 
            f"Готово: пауза {format_duration(seconds) if seconds else 'вимкнена'}."
        )
        return

    if key == "timezone":
        if not values:
            await safe_reply(message, "Приклад: <code>/settings timezone Europe/Kyiv</code>")
            return
        tz_name = values[0]
        if ZoneInfo is not None:
            try:
                ZoneInfo(tz_name)
            except Exception:  # noqa: BLE001
                await safe_reply(message, 
                    f"Не знаю таймзони <code>{tz_name}</code>. Приклад: <code>Europe/Kyiv</code>"
                )
                return
        await chats_repo.update_settings(session, message.chat.id, timezone=tz_name)
        await safe_reply(message, f"Готово: таймзона {tz_name}")
        return

    if key == "quiet":
        if values and values[0].lower() in {"off", "no", "вимк"}:
            await chats_repo.update_settings(
                session, message.chat.id, quiet_hours_enabled=False
            )
            await safe_reply(message, "Тихі години вимкнено.")
            return
        if len(values) != 2 or not all(value.isdigit() for value in values):
            await safe_reply(message, 
                "Вкажи дві години: <code>/settings quiet 23 8</code> або <code>quiet off</code>"
            )
            return
        start, end = int(values[0]), int(values[1])
        if not (0 <= start <= 23 and 0 <= end <= 23):
            await safe_reply(message, "Години мають бути від 0 до 23.")
            return
        await chats_repo.update_settings(
            session,
            message.chat.id,
            quiet_hours_enabled=True,
            quiet_start=start,
            quiet_end=end,
        )
        await safe_reply(message, f"Тихі години: {start:02d}:00–{end:02d}:00 ({db_chat.timezone}).")
        return

    await safe_reply(message, USAGE)


async def cmd_stats(message: Message, session: AsyncSession, bot: Bot) -> None:
    known = await members_repo.count_active_members(session, message.chat.id)
    muted = await members_repo.count_muted_members(session, message.chat.id)
    tag_count = await tags_repo.count_tags(session, message.chat.id)
    reachable = known - muted

    lines = [
        "<b>Що я знаю про цей чат</b>",
        f"• учасників у базі: {known}",
        f"• з них <code>@all</code> дістане: {reachable}",
        f"• виключили себе з <code>@all</code>: {muted}",
        f"• власних тегів бота: {tag_count}",
    ]
    with_tag = await members_repo.count_members_with_telegram_tag(session, message.chat.id)
    lines.append(f"• знаю рідних тегів Telegram: {with_tag}")
    lines.extend(await _render_coverage(bot, message.chat.id, known))
    await safe_reply(message, "\n".join(lines))


async def _render_coverage(bot: Bot, chat_id: int, known: int) -> List[str]:
    """Скільки людей у чаті бот ще не знає.

    getChatMemberCount рахує всіх, разом з ботами, тож віднімаємо самого себе.
    Число орієнтовне: інші боти в чаті теж потраплять у «невідомих».
    """
    try:
        total = await bot.get_chat_member_count(chat_id)
    except TelegramAPIError as error:
        logger.info("Не вдалося дізнатися кількість учасників %s: %s", chat_id, error)
        return []

    unknown = max(0, total - 1 - known)
    lines = [f"• усього в чаті за даними Telegram: {total}"]
    if unknown:
        lines.append(f"• <b>ще не знаю: {unknown}</b> — вони жодного разу себе не проявили")
        lines.append("<i>Зібрати їх: <code>/rollcall</code> — кнопка в один клік.</i>")
    else:
        lines.append("• знаю всіх ✓")
    return lines


def build_router() -> Router:
    router = Router(name="settings")
    router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

    router.message.register(cmd_settings, Command("settings"))
    router.message.register(cmd_stats, Command("stats"))
    return router
