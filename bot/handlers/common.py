from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.utils.replies import safe_answer, safe_reply

HELP_TEXT = """<b>Теги замість @username</b>

Додай мене в групу, і можна кликати людей за ролями, а не за нікнеймами.
Працює навіть для тих, у кого юзернейма взагалі немає.

<b>Виклик</b>
• <code>@all</code> — усі, кого я знаю в цьому чаті
• <code>@назва_тега</code> — просто напиши в будь-якому повідомленні
• регістр не важливий, і достатньо частини назви:
  <code>@dev</code> покличе і <code>@devs</code>, і <code>@devops</code>
• <code>@звання</code> — за рідним тегом Telegram: якщо в людей у званні
  є «Sun», їх покличе <code>@sun</code>. Створювати нічого не треба

<b>Теги</b>
• <code>/tags</code> — список тегів чату
• <code>/tag_info назва</code> — хто в тезі
• <code>/tag_create назва [опис]</code>
• <code>/tag_delete назва</code>
• <code>/tag_add назва @хто</code> — або реплаєм на повідомлення
• <code>/tag_remove назва @хто</code>

<b>Про себе</b>
• <code>/join назва</code> / <code>/leave назва</code> — вписатись у тег або вийти
• <code>/me</code> — у яких я тегах
• <code>/mute_me</code> / <code>/unmute_me</code> — виключити себе з <code>@all</code>

<b>Налаштування</b> (адміни)
• <code>/settings</code> — поточні значення й підказки

<b>Зібрати учасників</b> (адміни)
• <code>/rollcall</code> — повідомлення з кнопкою «Я тут». Закріпіть його:
  один клік — і людина в базі, писати нічого не треба
• <code>/stats</code> покаже, скількох я ще не знаю

<b>Важливо</b>
Telegram не дає ботам списку учасників групи, тож я знаю лише тих, хто себе
проявив: написав повідомлення, поставив реакцію або натиснув кнопку переклички."""

START_PRIVATE = """Привіт! Я допомагаю кликати людей у групах за тегами, а не за нікнеймами.

Додай мене в групу — і там уже працюватиме <code>@all</code> та власні теги.

Щоб я бачив усіх учасників, вимкни мені privacy mode у @BotFather
(<code>/setprivacy</code> → Disable) і зроби адміном групи.

<code>/help</code> — усі команди."""


async def cmd_start(message: Message) -> None:
    if message.chat.type == "private":
        await safe_answer(message, START_PRIVATE)
    else:
        await safe_reply(message, HELP_TEXT)


async def cmd_help(message: Message) -> None:
    await safe_reply(message, HELP_TEXT)


def build_router() -> Router:
    router = Router(name="common")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    return router
