from __future__ import annotations

#: Віртуальний тег: у БД не існує, розкривається в усіх активних учасників чату.
ALL_TAG = "all"

#: Синоніми віртуального тега. Створити звичайний тег із такою назвою не можна.
ALL_TAG_ALIASES = frozenset({"all", "everyone", "все", "всі", "усі"})

#: Назви, зарезервовані під команди й службові згадки.
RESERVED_TAG_NAMES = ALL_TAG_ALIASES | frozenset({"here", "channel", "admin", "admins"})

#: Максимальна довжина назви тега.
MAX_TAG_NAME_LENGTH = 32

#: Скільки тегів дозволено на один чат — захист від засмічення бази.
MAX_TAGS_PER_CHAT = 100

#: Скільки тегів максимум може розкрити одна неточна згадка (@dev -> @devs, @devops).
#: Понад це бот просить уточнити назву, щоб `@a` не підняв половину чату.
MAX_FUZZY_TAG_MATCHES = 5

#: Скільки символів імені показувати в згадці.
MAX_DISPLAY_NAME_LENGTH = 32

#: Ліміт Telegram на довжину повідомлення.
TELEGRAM_MESSAGE_LIMIT = 4096

POLICY_ADMINS = "admins"
POLICY_MEMBERS = "members"
