from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover — Windows, у проді не використовується
    fcntl = None  # type: ignore[assignment]


class InstanceLock:
    """Не дає двом копіям бота працювати на спільній теці даних.

    Два процеси з одним токеном крадуть один в одного апдейти: Telegram
    відповідає на getUpdates помилкою Conflict, і бот виглядає мертвим.
    Найчастіший сценарій — старий контейнер, який забули зупинити.

    Блокування знімає сама ОС, коли процес завершується, тож зависла копія
    після kill -9 не залишить по собі мертвий лок.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def acquire(self) -> bool:
        if fcntl is None:
            logger.warning("Блокування недоступне на цій платформі — пропускаємо перевірку")
            return True

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self._path, "a+", encoding="utf-8")
        except OSError as error:
            logger.warning("Не вдалося відкрити файл блокування %s: %s", self._path, error)
            return True  # краще запуститися, ніж не запуститися через дрібницю

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.seek(0)
            owner = handle.read().strip() or "невідомий процес"
            handle.close()
            logger.error(
                "Бот уже запущений (%s) і тримає %s. Другий екземпляр із тим самим "
                "токеном лише відбирав би апдейти в першого, тому зупиняємось.",
                owner,
                self._path,
            )
            return False

        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}")
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
        except OSError as error:
            logger.debug("Не вдалося зняти блокування: %s", error)
        finally:
            self._handle = None

    def __enter__(self) -> InstanceLock:
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
