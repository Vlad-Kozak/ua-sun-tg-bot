"""Доступ до полів Bot API, яких ще немає в нашій версії aiagram.

Теги учасників додані в Bot API 9.5 (1 березня 2026): поле `tag` у
ChatMemberMember/ChatMemberRestricted і `sender_tag` у Message. Встановлена
aiogram 3.22 знає лише Bot API 9.2, тож типізованих полів у неї немає.

Моделі aiogram оголошені з `extra="allow"`, тому невідомі поля не відкидаються,
а лишаються в `model_extra`. Читаємо їх звідти — але робимо це рівно в одному
місці, щоб перехід на нативні поля після оновлення aiogram був точковим.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

#: Мінімальна довжина, з якої вважаємо значення осмисленим тегом.
MIN_TAG_LENGTH = 1
#: Telegram обмежує звання 16 символами; беремо запас на випадок змін.
MAX_TAG_LENGTH = 64


def read_optional_field(source: Any, name: str) -> Tuple[bool, Optional[str]]:
    """Читає поле, якого може не бути в моделі.

    Повертає (present, value). Розрізняти ці два випадки принципово:

    * поля немає взагалі — Telegram ще не надсилає його цьому боту, і наявне
      значення в базі чіпати не можна;
    * поле є, але порожнє — тег справді зняли, і його треба стерти.
    """
    if source is None:
        return False, None

    value: Any = getattr(source, name, None)
    if value is None:
        extra = getattr(source, "model_extra", None) or {}
        if name not in extra:
            return False, None
        value = extra[name]

    if value is None:
        return True, None
    if not isinstance(value, str):
        return True, None

    cleaned = value.strip()
    if len(cleaned) < MIN_TAG_LENGTH:
        return True, None
    return True, cleaned[:MAX_TAG_LENGTH]


def sender_tag(message: Any) -> Tuple[bool, Optional[str]]:
    """Тег автора повідомлення (`Message.sender_tag`, Bot API 9.5).

    Telegram описує його як «Tag or custom title of the sender of the message;
    for supergroups only», тобто одне поле і для тегів учасників, і для
    адмінських звань.
    """
    return read_optional_field(message, "sender_tag")


def member_tag(chat_member: Any) -> Tuple[bool, Optional[str]]:
    """Тег учасника з ChatMember: `tag` у звичайних, `custom_title` в адмінів."""
    present, value = read_optional_field(chat_member, "tag")
    if present:
        return present, value
    return read_optional_field(chat_member, "custom_title")
