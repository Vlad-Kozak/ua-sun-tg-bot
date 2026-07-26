from __future__ import annotations

import logging
from typing import Dict, List, Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.constants import ALL_TAG, ALL_TAG_ALIASES, MAX_FUZZY_TAG_MATCHES
from bot.db.models import Chat
from bot.db.repo import chats as chats_repo
from bot.db.repo import cooldowns as cooldowns_repo
from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.services.mention import MentionTarget, build_mention_messages, targets_from_users
from bot.services.policy import AdminCache, check_policy, is_quiet_now
from bot.services.sender import ChatUnavailableError, MessageSender
from bot.services.tag_lookup import find_users_by_telegram_tag
from bot.utils.replies import safe_reply
from bot.utils.text import extract_mentions
from bot.utils.time import format_duration

logger = logging.getLogger(__name__)


#: Скільки різних @згадок обробляти в одному повідомленні. Кожна згадка може
#: розкритися в кілька тегів, але аудиторія все одно дедуплікується.
MAX_MENTIONS_PER_MESSAGE = 3


async def handle_mentions(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    sender: MessageSender,
    admin_cache: AdminCache,
    settings: Settings,
) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return

    text = message.text or message.caption or ""
    candidates = extract_mentions(text)
    if not candidates:
        return

    author_id = message.from_user.id if message.from_user else None
    targets: Dict[int, MentionTarget] = {}
    used_labels: List[str] = []
    notes: List[str] = []
    handled = 0

    for candidate in candidates:
        if handled >= MAX_MENTIONS_PER_MESSAGE:
            break

        if candidate in ALL_TAG_ALIASES:
            resolved = await _collect_all(
                message, session, db_chat, bot, admin_cache, author_id, notes
            )
            if resolved is None:
                continue
            handled += 1
            used_labels.append(f"@{ALL_TAG}")
            targets.update(resolved)
            continue

        # Назва або її частина: @dev знайде і @devs, і @devops — покличемо всіх.
        matches = await tags_repo.find_tags(session, message.chat.id, candidate)
        if not matches:
            # Власного тега немає — пробуємо рідні теги Telegram: @sun покличе
            # всіх, у кого в званні є «Sun».
            if await _collect_by_telegram_tag(
                message, session, db_chat, candidate, author_id, targets, used_labels, notes
            ):
                handled += 1
            # Інакше це звичайний @username або просто слово з @ — не наша справа.
            continue

        if len(matches) > MAX_FUZZY_TAG_MATCHES:
            notes.append(
                f"@{candidate} підходить надто багатьом тегам — уточніть назву"
            )
            continue

        handled += 1
        for tag in matches:
            wait = await cooldowns_repo.try_acquire(
                session, message.chat.id, tag.name_lower, db_chat.cooldown_seconds, author_id
            )
            if wait is not None:
                notes.append(f"@{tag.name} нещодавно вже кликали — ще {format_duration(wait)}")
                continue

            users = await tags_repo.get_tag_users(session, tag)
            resolved = {
                target.user_id: target
                for target in targets_from_users(users)
                if target.user_id != author_id
            }
            used_labels.append(f"@{tag.name}")
            if not resolved:
                notes.append(f"У тезі @{tag.name} немає кого кликати")
                continue
            targets.update(resolved)

    if not targets:
        if notes:
            # Службові відмови не мають самі перетворюватись на спам.
            await safe_reply(message, "; ".join(notes) + ".", disable_notification=True)
        return

    header = "🔔 " + " ".join(used_labels)
    if notes:
        header += "\n<i>" + "; ".join(notes) + "</i>"

    texts = build_mention_messages(
        list(targets.values()), header=header, batch_size=settings.mention_batch_size
    )
    quiet = is_quiet_now(db_chat)

    try:
        await sender.send_batches(
            chat_id=message.chat.id,
            texts=texts,
            reply_to_message_id=message.message_id,
            message_thread_id=message.message_thread_id if message.is_topic_message else None,
            disable_notification=quiet,
        )
    except ChatUnavailableError:
        await chats_repo.set_chat_active(session, message.chat.id, False)
        logger.info("Чат %s позначено неактивним", message.chat.id)


async def _collect_by_telegram_tag(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    candidate: str,
    author_id: Optional[int],
    targets: Dict[int, MentionTarget],
    used_labels: List[str],
    notes: List[str],
) -> bool:
    """Розкриває згадку за рідним тегом Telegram. False — нічого не знайшли.

    Склад такої згадки ніде не зберігається: він щоразу обчислюється з тегів,
    які люди мають у Telegram просто зараз. Змінили звання — змінився і склад.
    """
    users = await find_users_by_telegram_tag(
        session,
        message.chat.id,
        candidate,
        exclude_user_ids=[author_id] if author_id else None,
    )
    if not users:
        return False

    # Ключ окремий від власних тегів: у чаті можуть співіснувати тег @sun і
    # звання «Sun», і паузи в них мають бути незалежні.
    wait = await cooldowns_repo.try_acquire(
        session, message.chat.id, f"tg:{candidate}", db_chat.cooldown_seconds, author_id
    )
    if wait is not None:
        notes.append(f"@{candidate} нещодавно вже кликали — ще {format_duration(wait)}")
        return False

    used_labels.append(f"@{candidate}")
    targets.update({target.user_id: target for target in targets_from_users(users)})
    return True


async def _collect_all(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
    author_id: Optional[int],
    notes: List[str],
) -> Optional[Dict[int, MentionTarget]]:
    """Розкриває віртуальний @all. None — виклик відхилено."""
    if not await check_policy(bot, admin_cache, message, db_chat.all_policy):
        notes.append("@all у цьому чаті доступний лише адмінам")
        return None

    wait = await cooldowns_repo.try_acquire(
        session, message.chat.id, ALL_TAG, db_chat.cooldown_seconds, author_id
    )
    if wait is not None:
        notes.append(f"@all нещодавно вже кликали — ще {format_duration(wait)}")
        return None

    users = await members_repo.list_active_users(
        session,
        message.chat.id,
        exclude_muted=True,
        exclude_bots=True,
        exclude_user_ids=[author_id] if author_id else None,
    )
    if not users:
        notes.append("У списку @all поки нікого — хай учасники щось напишуть у чат")
        return None

    return {target.user_id: target for target in targets_from_users(users)}


def build_router() -> Router:
    router = Router(name="mentions")
    router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

    router.message.register(handle_mentions, F.text | F.caption)
    return router
