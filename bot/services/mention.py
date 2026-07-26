from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable, List, Sequence

from bot.constants import TELEGRAM_MESSAGE_LIMIT
from bot.db.models import User
from bot.utils.text import display_name


@dataclass(frozen=True)
class MentionTarget:
    user_id: int
    name: str

    @classmethod
    def from_user(cls, user: User) -> MentionTarget:
        return cls(
            user_id=user.user_id,
            name=display_name(user.first_name, user.last_name, user.username, user.user_id),
        )


def render_mention(target: MentionTarget) -> str:
    """Клікабельна згадка без @username.

    tg://user?id=... — це те саме, що MessageEntity типу text_mention, тільки
    без ручного рахування offset у UTF-16, на якому легко помилитися з емодзі.
    """
    return f'<a href="tg://user?id={target.user_id}">{escape(target.name)}</a>'


def targets_from_users(users: Iterable[User]) -> List[MentionTarget]:
    return [MentionTarget.from_user(user) for user in users]


def build_mention_messages(
    targets: Sequence[MentionTarget],
    header: str = "",
    batch_size: int = 6,
) -> List[str]:
    """Ріже список згадок на повідомлення.

    Дрібні батчі — не примха: у повідомленні з десятками згадок клієнти Telegram
    часом не показують нотифікацію всім згаданим. 5–8 працює стабільно.
    """
    if not targets:
        return []

    batch_size = max(1, batch_size)
    messages: List[str] = []
    for index in range(0, len(targets), batch_size):
        chunk = targets[index : index + batch_size]
        body = ", ".join(render_mention(target) for target in chunk)
        prefix = f"{header}\n" if header and index == 0 else ""
        text = f"{prefix}{body}"
        if len(text) > TELEGRAM_MESSAGE_LIMIT:
            # Захист від патологічно довгих імен: віддаємо кожного окремо.
            messages.extend(render_mention(target) for target in chunk)
        else:
            messages.append(text)
    return messages
