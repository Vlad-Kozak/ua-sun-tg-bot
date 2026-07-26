from __future__ import annotations

from html import escape
from typing import Iterable, List, Optional

from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Tag, User
from bot.db.repo import members as members_repo
from bot.db.repo import tags as tags_repo
from bot.utils.replies import safe_reply
from bot.utils.text import normalize_tag_name, phrase_match_level


async def find_users_by_telegram_tag(
    session: AsyncSession,
    chat_id: int,
    query: str,
    exclude_user_ids: Optional[Iterable[int]] = None,
) -> List[User]:
    """Люди, чий рідний тег Telegram збігається із запитом.

    Правила ті самі, що для власних тегів бота: без урахування регістру й з
    пошуком за частиною. Беремо лише найточніший рівень, який дав результат —
    інакше `@sun` тягнув би за собою випадкові підрядкові збіги разом із тими,
    у кого «Sun» стоїть окремим словом.
    """
    excluded = set(exclude_user_ids or ())
    best_level: Optional[int] = None
    matched: List[User] = []

    for user, tag in await members_repo.list_members_with_telegram_tags(session, chat_id):
        if user.user_id in excluded:
            continue
        level = phrase_match_level(query, tag)
        if level is None:
            continue
        if best_level is None or level < best_level:
            best_level, matched = level, [user]
        elif level == best_level:
            matched.append(user)

    return matched


async def resolve_tag_or_reply(
    session: AsyncSession,
    message: Message,
    name: str,
) -> Optional[Tag]:
    """Знаходить рівно один тег за назвою або її частиною.

    Команди керування працюють з одним тегом, тому на кілька збігів тут не
    здогадуємось, а показуємо список і просимо уточнити: помилитися тегом у
    `/tag_delete` дорожче, ніж набрати назву повністю.

    Повертає None і сама відповідає в чат, якщо тега немає або збігів кілька.
    """
    matches = await tags_repo.find_tags(session, message.chat.id, name)
    if len(matches) == 1:
        return matches[0]

    safe_name = escape(normalize_tag_name(name))
    if not matches:
        await safe_reply(message, f"Тега <code>@{safe_name}</code> немає в цьому чаті.")
        return None

    listed = ", ".join(f"<code>@{escape(tag.name)}</code>" for tag in matches)
    await safe_reply(
        message, f"Під «{safe_name}» підходить кілька тегів: {listed}.\nУточніть назву."
    )
    return None
