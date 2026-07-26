from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, ErrorEvent

from bot.config import Settings, get_settings
from bot.db.session import get_database
from bot.handlers import build_router
from bot.middlewares import DatabaseMiddleware, MemberTrackerMiddleware
from bot.services.policy import AdminCache
from bot.services.sender import MessageSender
from bot.utils.log_filters import ConflictNoiseFilter
from bot.utils.singleton import InstanceLock

logger = logging.getLogger(__name__)

#: chat_member Telegram не надсилає, поки його не попросити явно — без цього
#: бот не дізнається, що людина вийшла з групи.
ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "callback_query",
    "chat_member",
    "my_chat_member",
    # Теж не надсилається за замовчуванням і теж потребує адмінства. Дає
    # найдешевший для людини спосіб потрапити в базу — просто поставити реакцію.
    "message_reaction",
]

#: Пауза перед перезапуском polling після збою — росте вдвічі до стелі.
POLLING_RESTART_MIN_DELAY = 1
POLLING_RESTART_MAX_DELAY = 60
#: Скільки секунд роботи вважати ознакою того, що збій був разовий.
POLLING_STABLE_UPTIME = 60
#: Як часто оновлювати мітку живого циклу обробки.
HEARTBEAT_INTERVAL = 30

GROUP_COMMANDS = [
    BotCommand(command="tags", description="Список тегів чату"),
    BotCommand(command="tag_info", description="Хто в тезі"),
    BotCommand(command="tag_create", description="Створити тег"),
    BotCommand(command="tag_delete", description="Видалити тег"),
    BotCommand(command="tag_add", description="Додати людину в тег"),
    BotCommand(command="tag_remove", description="Прибрати людину з тега"),
    BotCommand(command="join", description="Вписатись у тег"),
    BotCommand(command="leave", description="Вийти з тега"),
    BotCommand(command="me", description="Мої теги"),
    BotCommand(command="mute_me", description="Виключити себе з @all"),
    BotCommand(command="unmute_me", description="Повернутись у @all"),
    BotCommand(command="rollcall", description="Перекличка: зібрати учасників кнопкою"),
    BotCommand(command="stats", description="Що бот знає про чат"),
    BotCommand(command="settings", description="Налаштування чату"),
    BotCommand(command="help", description="Довідка"),
]


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def install_conflict_filter(lock_path: Path) -> None:
    """aiogram повторює getUpdates кожні ~5 с і щоразу пише про конфлікт.

    До пояснення додаємо відбиток цього екземпляра. Якщо ми тримаємо
    блокування — а сюди ми доходимо лише в такому разі, — то друга копія
    працює поза цією текою: інший сервер, інший каталог або процес поза Docker.
    Це одразу звужує пошук.
    """
    hint = (
        f"Цей екземпляр тримає {lock_path} (host={socket.gethostname()}, "
        f"pid={os.getpid()}), тож друга копія — поза цією текою: інший сервер, "
        f"інший каталог або процес поза Docker."
    )
    logging.getLogger("aiogram.dispatcher").addFilter(ConflictNoiseFilter(hint=hint))


def build_dispatcher(settings: Settings, bot: Bot) -> Dispatcher:
    database = get_database(settings.database_url)
    dispatcher = Dispatcher(
        settings=settings,
        admin_cache=AdminCache(),
        sender=MessageSender(bot, batch_delay=settings.mention_batch_delay),
    )
    dispatcher.update.outer_middleware(DatabaseMiddleware(database))
    dispatcher.message.outer_middleware(MemberTrackerMiddleware(settings))
    dispatcher.include_router(build_router())

    @dispatcher.error()
    async def on_error(event: ErrorEvent) -> bool:
        """Остання лінія оборони: жодна помилка апдейта не спиняє бота.

        Відмови Telegram (закрита тема, немає прав, 429) — очікуваний стан
        світу, тож логуємо їх коротко. Усе інше — наш баг, і тут потрібен
        повний traceback.
        """
        error = event.exception
        if isinstance(error, (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter)):
            logger.warning("Telegram відмовив: %s", error)
        elif isinstance(error, TelegramNetworkError):
            logger.warning("Мережева помилка Telegram: %s", error)
        else:
            logger.exception("Необроблена помилка в апдейті", exc_info=error)
        return True

    return dispatcher


async def _run_polling_forever(dispatcher: Dispatcher, bot: Bot) -> None:
    """Тримає polling живим попри будь-які збої.

    aiogram сам переживає мережеві негаразди в getUpdates, але несподіваний
    виняток завершив би корутину — і бот мовчав би до ручного рестарту.
    """
    delay = POLLING_RESTART_MIN_DELAY
    while True:
        started = time.monotonic()
        try:
            await dispatcher.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
            return  # штатна зупинка
        except asyncio.CancelledError:
            raise
        except Exception:
            uptime = time.monotonic() - started
            if uptime > POLLING_STABLE_UPTIME:
                # Довго працював — збій разовий, не треба довгих пауз.
                delay = POLLING_RESTART_MIN_DELAY
            logger.exception("Polling обірвався, перезапуск через %s с", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, POLLING_RESTART_MAX_DELAY)


async def _heartbeat(path: Path, interval: int = HEARTBEAT_INTERVAL) -> None:
    """Пише мітку часу у файл — щоб healthcheck бачив різницю між
    «процес живий» і «цикл обробки живий»."""
    while True:
        try:
            # Синхронний запис свідомо: десяток байт на локальний диск раз на
            # 30 секунд не вартий окремого потоку.
            path.parent.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
            path.write_text(str(int(time.time())), encoding="utf-8")  # noqa: ASYNC240
        except OSError as error:
            logger.warning("Не вдалося оновити heartbeat: %s", error)
        await asyncio.sleep(interval)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    lock_path = Path(settings.lock_file)
    lock = InstanceLock(lock_path)
    if not lock.acquire():
        return
    install_conflict_filter(lock_path)
    logger.info(
        "Екземпляр: host=%s pid=%s data=%s",
        socket.gethostname(),
        os.getpid(),
        lock_path.parent.resolve(),
    )

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(settings, bot)

    try:
        try:
            me = await bot.me()
        except TelegramUnauthorizedError:
            logger.error(
                "Telegram відхилив BOT_TOKEN. Перевір значення в .env — "
                "токен видає @BotFather командою /mybots."
            )
            return

        logger.info("Стартуємо як @%s (id=%s)", me.username, me.id)
        if not me.can_read_all_group_messages:
            logger.warning(
                "Privacy mode увімкнено: бот бачитиме лише команди й не збере список "
                "учасників. Вимкнути: @BotFather -> /setprivacy -> Disable, "
                "потім перезайти в групи."
            )

        try:
            # Якщо колись налаштовували webhook, він мовчки конфліктує з
            # getUpdates — Telegram віддаватиме Conflict на кожен запит.
            await bot.delete_webhook(drop_pending_updates=False)
        except TelegramAPIError as error:
            logger.warning("Не вдалося зняти webhook: %s", error)

        try:
            await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
        except TelegramAPIError as error:
            # Не критично: команди — це лише підказки в меню Telegram.
            logger.warning("Не вдалося оновити список команд: %s", error)

        heartbeat = asyncio.ensure_future(_heartbeat(Path(settings.heartbeat_file)))
        try:
            await _run_polling_forever(dispatcher, bot)
        finally:
            heartbeat.cancel()
    finally:
        await bot.session.close()
        await get_database().dispose()
        lock.release()
        logger.info("Зупинено")


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Отримано сигнал завершення")


if __name__ == "__main__":
    run()
