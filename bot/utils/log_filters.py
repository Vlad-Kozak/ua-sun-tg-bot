from __future__ import annotations

import logging
import time
from typing import Optional

#: Ознака конфлікту getUpdates у тексті помилки aiogram.
CONFLICT_MARKER = "terminated by other getupdates"
#: aiogram пише це після кожної невдачі getUpdates — WARNING «Sleep for…».
SLEEP_MARKER = "sleep for"
#: aiogram пише це після першого успішного getUpdates — кінець смуги збоїв.
RECOVERY_MARKER = "connection established"

TRANSIENT_CONFLICT_EXPLANATION = (
    "Конфлікт getUpdates: Telegram ще вважає активним попередній запит цього ж "
    "бота, який обірвався через мережу. За єдиного екземпляра це минає за "
    "лічені секунди, бот відновиться сам. Якщо конфлікт не зникне за кілька "
    "хвилин — токен справді використовує хтось іще (deploy/diagnose.py допоможе)."
)

CONFLICT_EXPLANATION = (
    "Конфлікт getUpdates: з цим самим токеном працює ще один екземпляр бота. "
    "Telegram віддає апдейти то одному, то іншому, тому бот здається мертвим. "
    "Перевірте: інший контейнер (docker ps -a), запуск на іншій машині, "
    "локальний процес для налагодження. Токен має бути рівно в одного."
)


class ConflictNoiseFilter(logging.Filter):
    """Стискає потік повідомлень про конфлікт getUpdates і чесно пояснює причину.

    Конфлікт не завжди означає другу копію бота: коли з'єднання обривається,
    Telegram ще до polling_timeout секунд тримає попередній запит активним, і
    повторний getUpdates конфліктує сам із собою. Тому короткі смуги конфліктів
    (менше `escalate_after` секунд без жодного успіху) описуємо як тимчасові й
    рівнем WARNING, і лише затяжні — як другу копію рівнем ERROR.

    Смугу збоїв обриває «Connection established» від aiogram: фільтр висить на
    тому самому логері й бачить це повідомлення. Схожі конфлікти показуємо не
    частіше ніж раз на `repeat_interval` секунд; «Sleep for…» після прихованого
    конфлікту теж ховаємо, інакше в лозі лишаються сироти без пояснення.
    """

    def __init__(
        self,
        repeat_interval: int = 60,
        hint: str = "",
        escalate_after: int = 180,
    ) -> None:
        super().__init__()
        self._repeat_interval = repeat_interval
        self._hint = hint
        self._escalate_after = escalate_after
        self._last_shown: Optional[float] = None
        self._suppressed = 0
        self._streak_started: Optional[float] = None
        self._swallow_next_sleep = False

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage().lower()
        except Exception:  # noqa: BLE001 — фільтр не має ламати логування
            return True

        if RECOVERY_MARKER in text:
            self._streak_started = None
            self._swallow_next_sleep = False
            return True

        if self._swallow_next_sleep and SLEEP_MARKER in text:
            self._swallow_next_sleep = False
            return False

        if CONFLICT_MARKER not in text:
            return True

        now = time.monotonic()
        if self._streak_started is None:
            self._streak_started = now

        if self._last_shown is not None and now - self._last_shown < self._repeat_interval:
            self._suppressed += 1
            self._swallow_next_sleep = True
            return False

        streak = now - self._streak_started
        if streak >= self._escalate_after:
            message = CONFLICT_EXPLANATION + (f" {self._hint}" if self._hint else "")
            message += f" Конфлікт триває вже {int(streak)} с без жодного успішного запиту."
        else:
            message = TRANSIENT_CONFLICT_EXPLANATION
            record.levelno = logging.WARNING
            record.levelname = logging.getLevelName(logging.WARNING)

        if self._suppressed:
            message += f" (приховано схожих повідомлень: {self._suppressed})"
        record.msg = message
        record.args = ()
        self._last_shown = now
        self._suppressed = 0
        return True
