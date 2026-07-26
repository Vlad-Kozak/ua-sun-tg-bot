from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated, Message, MessageReactionUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.services.policy import AdminCache
from bot.utils.replies import safe_send

logger = logging.getLogger(__name__)

GROUP_FILTER = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})

WELCOME = """Привіт! Тепер тут можна кликати людей тегами: <code>@all</code> або власними.

<b>Щоб я працював як слід, потрібні дві речі:</b>
1. Вимкнути мені privacy mode: @BotFather → <code>/setprivacy</code> → Disable,
   потім видалити мене з групи й додати знову. Без цього я бачу лише команди
   і не зможу зібрати список учасників.
2. Зробити мене адміном — тоді я знатиму, хто зайшов і вийшов, і бачитиму реакції.

Список для <code>@all</code> наповнюється сам: повідомлення, реакція або кнопка.
Щоб зібрати всіх швидко — <code>/rollcall</code> і закріпіть те повідомлення.

<code>/help</code> — усі команди."""

PRIVACY_WARNING = """⚠️ Зараз у мене увімкнений privacy mode — я бачу лише команди,
тому <code>@all</code> знатиме далеко не всіх.

Виправити: @BotFather → <code>/setprivacy</code> → Disable, потім видалити мене
з групи й додати заново."""


async def bot_added(
    event: ChatMemberUpdated,
    session: AsyncSession,
    settings: Settings,
    bot: Bot,
) -> None:
    if event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    await chats_repo.get_or_create_chat(session, event.chat.id, event.chat.title, settings)
    logger.info("Бота додано в чат %s (%s)", event.chat.id, event.chat.title)

    await safe_send(bot, event.chat.id, WELCOME)

    me = await bot.me()  # кешується aiogram, зайвого виклику API не буде
    if not me.can_read_all_group_messages:
        await safe_send(bot, event.chat.id, PRIVACY_WARNING)


async def bot_removed(
    event: ChatMemberUpdated,
    session: AsyncSession,
    admin_cache: AdminCache,
) -> None:
    await chats_repo.set_chat_active(session, event.chat.id, False)
    admin_cache.invalidate(event.chat.id)
    logger.info("Бота прибрано з чату %s", event.chat.id)


async def member_joined(
    event: ChatMemberUpdated,
    session: AsyncSession,
    settings: Settings,
) -> None:
    user = event.new_chat_member.user
    if user.is_bot:
        return
    await chats_repo.get_or_create_chat(session, event.chat.id, event.chat.title, settings)
    await members_repo.upsert_user(
        session,
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        is_bot=user.is_bot,
    )
    await members_repo.ensure_membership(session, event.chat.id, user.id, touch=False)


async def member_left(event: ChatMemberUpdated, session: AsyncSession) -> None:
    user = event.new_chat_member.user
    await members_repo.set_member_active(session, event.chat.id, user.id, False)
    await members_repo.purge_user_from_chat_tags(session, event.chat.id, user.id)


async def service_members_added(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Резервний шлях: service-повідомлення приходять і тоді, коли бот не адмін."""
    await chats_repo.get_or_create_chat(session, message.chat.id, message.chat.title, settings)
    for user in message.new_chat_members or []:
        if user.is_bot:
            continue
        await members_repo.upsert_user(
            session,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            is_bot=user.is_bot,
        )
        await members_repo.ensure_membership(session, message.chat.id, user.id, touch=False)


async def service_member_left(message: Message, session: AsyncSession) -> None:
    user = message.left_chat_member
    if user is None or user.is_bot:
        return
    await members_repo.set_member_active(session, message.chat.id, user.id, False)
    await members_repo.purge_user_from_chat_tags(session, message.chat.id, user.id)


async def reaction_seen(
    event: MessageReactionUpdated,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Реакція — теж слід присутності, і найдешевший для людини.

    Апдейт приходить лише якщо бот адміністратор і "message_reaction" явно
    вказано в allowed_updates. Коли реакцію ставлять анонімно від імені групи,
    Telegram надсилає actor_chat замість user — такий випадок пропускаємо.
    """
    user = event.user
    if user is None or user.is_bot:
        return
    if event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    await chats_repo.get_or_create_chat(session, event.chat.id, event.chat.title, settings)
    await members_repo.upsert_user(
        session,
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        is_bot=user.is_bot,
    )
    await members_repo.ensure_membership(session, event.chat.id, user.id)


async def chat_migrated(message: Message, session: AsyncSession) -> None:
    """Група стала супергрупою — переносимо теги й учасників на новий chat_id."""
    new_chat_id = message.migrate_to_chat_id
    if new_chat_id is None:
        return
    moved = await chats_repo.migrate_chat_id(session, message.chat.id, new_chat_id)
    if moved:
        logger.info("Перенесено дані чату %s -> %s", message.chat.id, new_chat_id)


def build_router() -> Router:
    router = Router(name="chat_events")

    joined = ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION)
    left = ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION)

    router.my_chat_member.register(bot_added, joined)
    router.my_chat_member.register(bot_removed, left)
    router.chat_member.register(member_joined, joined)
    router.chat_member.register(member_left, left)
    router.message.register(service_members_added, GROUP_FILTER, F.new_chat_members)
    router.message.register(service_member_left, GROUP_FILTER, F.left_chat_member)
    router.message.register(chat_migrated, F.migrate_to_chat_id)
    router.message_reaction.register(reaction_seen)
    return router
