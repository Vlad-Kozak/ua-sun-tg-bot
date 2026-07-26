from __future__ import annotations

import logging
import time
from typing import Optional

#: Ознака того самого конфлікту getUpdates у тексті помилки aiogram.
CONFLICT_MARKER = "terminated by other getupdates"

CONFLICT_EXPLANATION = (
    "Конфлікт getUpdates: з цим самим токеном працює ще один екземпляр бота. "
    "Telegram віддає апдейти то одному, то іншому, тому бот здається мертвим. "
    "Перевірте: інший контейнер (docker ps -a), запуск на іншій машині, "
    "локальний процес для налагодження. Токен має бути рівно в одного."
)


class ConflictNoiseFilter(logging.Filter):
    """Стискає потік однакових повідомлень про конфлікт до одного зрозумілого.

    aiogram повторює спробу кожні ~5 секунд і щоразу пише ERROR. За годину це
    сотні однакових рядків, у яких тоне все інше, а причина так і лишається
    незрозумілою. Лишаємо перше повідомлення з поясненням і далі не частіше
    ніж раз на `repeat_interval` секунд.
    """

    def __init__(self, repeat_interval: int = 60, hint: str = "") -> None:
        super().__init__()
        self._repeat_interval = repeat_interval
        self._hint = hint
        self._last_shown: Optional[float] = None
        self._suppressed = 0

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage().lower()
        except Exception:  # noqa: BLE001 — фільтр не має ламати логування
            return True

        if CONFLICT_MARKER not in text:
            return True

        now = time.monotonic()
        if self._last_shown is not None and now - self._last_shown < self._repeat_interval:
            self._suppressed += 1
            return False

        suffix = f" (приховано схожих повідомлень: {self._suppressed})" if self._suppressed else ""
        record.msg = CONFLICT_EXPLANATION + (f" {self._hint}" if self._hint else "") + suffix
        record.args = ()
        self._last_shown = now
        self._suppressed = 0
        return True
