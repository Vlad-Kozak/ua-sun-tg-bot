from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import Chat
from bot.db.repo import chats as chats_repo
from bot.db.repo import members as members_repo
from bot.services.policy import AdminCache, is_admin
from bot.utils.replies import safe_answer, safe_callback_answer, safe_edit, safe_reply

logger = logging.getLogger(__name__)

CALLBACK_DATA = "rollcall:here"

#: Як часто оновлювати лічильник у повідомленні переклички. Без цієї паузи
#: масове натискання кнопки перетворилося б на потік editMessageText.
COUNTER_REFRESH_SECONDS = 5

#: Стан повідомлення переклички: (час останнього оновлення, показаний текст).
#: Текст тримаємо, щоб не переписувати повідомлення тим самим вмістом — на це
#: Telegram відповідає помилкою «message is not modified». Втрата стану при
#: рестарті нічого не ламає: у гіршому разі буде одне зайве редагування.
_message_state: Dict[int, Tuple[float, str]] = {}

INTRO = (
    "✋ <b>Перекличка</b>\n\n"
    "Натисніть кнопку — і я зможу кликати вас через <code>@all</code> та теги.\n"
    "Один клік, писати нічого не треба.\n\n"
    "Telegram не дає ботам списку учасників групи, тому я знаю лише тих, "
    "хто вже якось себе проявив."
)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✋ Я тут", callback_data=CALLBACK_DATA)]]
    )


async def _progress_line(session: AsyncSession, bot: Bot, chat_id: int) -> str:
    known = await members_repo.count_active_members(session, chat_id)
    total = await _total_members(bot, chat_id)
    if total is None:
        return f"\n\nВже знаю: <b>{known}</b>"
    return f"\n\nВже знаю: <b>{known}</b> з {total}"


async def _total_members(bot: Bot, chat_id: int) -> Optional[int]:
    """Скільки людей у чаті за даними Telegram (разом з ботами)."""
    try:
        return await bot.get_chat_member_count(chat_id)
    except Exception as error:  # noqa: BLE001 — довідкове число, не варте падіння
        logger.info("Не вдалося отримати кількість учасників чату %s: %s", chat_id, error)
        return None


async def cmd_rollcall(
    message: Message,
    session: AsyncSession,
    db_chat: Chat,
    bot: Bot,
    admin_cache: AdminCache,
) -> None:
    """Постить повідомлення з кнопкою. Його варто закріпити в чаті."""
    if not await is_admin(bot, admin_cache, message):
        await safe_reply(message, "Перекличку може оголосити лише адмін чату.")
        return

    text = INTRO + await _progress_line(session, bot, message.chat.id)
    sent = await safe_answer(message, text, reply_markup=_keyboard())
    if sent is not None:
        # Запам'ятовуємо показаний текст одразу, щоб перший же натиск не
        # спричинив редагування тим самим вмістом.
        _message_state[sent.message_id] = (time.monotonic(), text)
        logger.info("Перекличка оголошена в чаті %s", message.chat.id)


async def on_here(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    bot: Bot,
) -> None:
    """Натиск кнопки — єдине, що потрібно від учасника, щоб потрапити в базу."""
    user = callback.from_user
    chat = callback.message.chat if callback.message is not None else None
    if user is None or chat is None:
        await safe_callback_answer(callback, "Не вдалося вас записати, спробуйте ще раз.")
        return

    await chats_repo.get_or_create_chat(session, chat.id, chat.title, settings)
    await members_repo.upsert_user(
        session,
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        is_bot=user.is_bot,
    )
    await members_repo.ensure_membership(session, chat.id, user.id)

    await safe_callback_answer(callback, "Записав! Тепер @all вас дістане.")
    await _refresh_counter(callback.message, session, bot)


async def _refresh_counter(message: Message, session: AsyncSession, bot: Bot) -> None:
    now = time.monotonic()
    state = _message_state.get(message.message_id)
    if state is not None and now - state[0] < COUNTER_REFRESH_SECONDS:
        return

    text = INTRO + await _progress_line(session, bot, message.chat.id)
    if state is not None and state[1] == text:
        # Людина натиснула повторно — лічильник не зрушив, переписувати нічого.
        _message_state[message.message_id] = (now, text)
        return

    _message_state[message.message_id] = (now, text)
    await safe_edit(message, text, reply_markup=_keyboard())


def build_router() -> Router:
    router = Router(name="rollcall")

    router.message.register(
        cmd_rollcall,
        Command("rollcall", "gather"),
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    )
    router.callback_query.register(on_here, F.data == CALLBACK_DATA)
    return router
