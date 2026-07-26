from __future__ import annotations

import re
from typing import Optional

from bot.constants import MAX_DISPLAY_NAME_LENGTH, MAX_TAG_NAME_LENGTH, RESERVED_TAG_NAMES

#: Дозволяємо латиницю, кирилицю, цифри, _ і - . Це наші власні теги, а не Telegram-юзернейми.
TAG_NAME_RE = re.compile(rf"^[\wЀ-ӿ-]{{2,{MAX_TAG_NAME_LENGTH}}}$", re.UNICODE)

#: Пошук згадок @tag у вільному тексті.
#: (?<![\w@/]) — не чіпаємо e-mail, підряд ідучі @@ і команди виду /cmd@bot.
MENTION_RE = re.compile(rf"(?<![\w@/])@([\wЀ-ӿ-]{{2,{MAX_TAG_NAME_LENGTH}}})", re.UNICODE)


def normalize_tag_name(name: str) -> str:
    return name.strip().lstrip("@").lower()


def validate_tag_name(name: str) -> Optional[str]:
    """Повертає текст помилки або None, якщо назва придатна."""
    normalized = normalize_tag_name(name)
    if not normalized:
        return "Порожня назва тега."
    if len(normalized) < 2:
        return "Назва тега має бути щонайменше з 2 символів."
    if len(normalized) > MAX_TAG_NAME_LENGTH:
        return f"Назва тега задовга — максимум {MAX_TAG_NAME_LENGTH} символів."
    if not TAG_NAME_RE.match(normalized):
        return "У назві дозволені лише літери, цифри, _ і -."
    if normalized in RESERVED_TAG_NAMES:
        return f"Назва @{normalized} зарезервована."
    return None


def extract_mentions(text: str) -> list:
    """Усі @слова з тексту, у нижньому регістрі, без повторів і зі збереженням порядку."""
    seen = []
    for match in MENTION_RE.finditer(text):
        candidate = match.group(1).lower()
        if candidate not in seen:
            seen.append(candidate)
    return seen


#: Розбиття тега-фрази на слова: «Mr Shishka Sun» -> mr, shishka, sun.
WORD_RE = re.compile(r"[\wЀ-ӿ]+", re.UNICODE)

#: Рівні збігу запиту з тегом-фразою, від найточнішого до найширшого.
MATCH_EXACT_WORD = 1
MATCH_WORD_PREFIX = 2
MATCH_SUBSTRING = 3


def phrase_match_level(query: str, phrase: str) -> Optional[int]:
    """Наскільки добре запит збігається з тегом-фразою; None — не збігається.

    Ті самі три рівні, що й у пошуку власних тегів, лише застосовані до слів
    усередині фрази: `@sun` спершу шукає слово «sun», далі слово, що з нього
    починається, і аж потім будь-яке входження в рядок.
    """
    normalized = query.strip().lstrip("@").lower()
    if not normalized or not phrase:
        return None

    words = [word.lower() for word in WORD_RE.findall(phrase)]
    if normalized in words:
        return MATCH_EXACT_WORD
    if any(word.startswith(normalized) for word in words):
        return MATCH_WORD_PREFIX
    if normalized in phrase.lower():
        return MATCH_SUBSTRING
    return None


def display_name(
    first_name: Optional[str],
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    user_id: Optional[int] = None,
) -> str:
    """Як підписати людину в згадці."""
    parts = [part for part in (first_name, last_name) if part]
    name = " ".join(parts).strip()
    if not name and username:
        name = username
    if not name:
        name = f"user{user_id}" if user_id else "user"
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        name = name[: MAX_DISPLAY_NAME_LENGTH - 1].rstrip() + "…"
    return name
