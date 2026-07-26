from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from aiogram.types import Message, User


@dataclass
class MentionedPeople:
    """Кого автор мав на увазі в команді."""

    #: Користувачі, чий id ми дізналися одразу (реплай або text_mention).
    users: List[User] = field(default_factory=list)
    #: @username без id — їх ще треба пошукати в нашій базі.
    usernames: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.users or self.usernames)


def extract_mentioned_people(message: Message, skip_first_word: bool = True) -> MentionedPeople:
    """Збирає адресатів команди з реплаю, text_mention-ентіті та @username.

    skip_first_word пропускає перший аргумент команди — там зазвичай назва тега,
    яку не можна плутати з @username.
    """
    result = MentionedPeople()
    seen_ids = set()
    seen_usernames = set()

    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        result.users.append(reply.from_user)
        seen_ids.add(reply.from_user.id)

    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    for entity in entities:
        if entity.type == "text_mention" and entity.user is not None:
            if entity.user.is_bot or entity.user.id in seen_ids:
                continue
            result.users.append(entity.user)
            seen_ids.add(entity.user.id)
        elif entity.type == "mention":
            raw = entity.extract_from(text).lstrip("@")
            normalized = raw.lower()
            if not raw or normalized in seen_usernames:
                continue
            if skip_first_word and _is_first_argument(text, entity.offset):
                continue
            result.usernames.append(raw)
            seen_usernames.add(normalized)

    return result


def _is_first_argument(text: str, offset: int) -> bool:
    """Чи стоїть ентіті на місці першого аргументу команди (тобто це назва тега)."""
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        return False
    first_arg_offset = text.index(parts[1], len(parts[0]))
    return offset == first_arg_offset


def command_args(message: Message) -> List[str]:
    """Аргументи команди без самої команди."""
    text = message.text or message.caption or ""
    return text.split()[1:]


def first_arg(message: Message) -> Optional[str]:
    args = command_args(message)
    return args[0] if args else None
