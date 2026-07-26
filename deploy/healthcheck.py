#!/usr/bin/env python3
"""Перевіряє, що живий саме цикл обробки, а не тільки процес.

Бот раз на 30 секунд оновлює файл-мітку. Якщо мітка застаріла — контейнер
працює, але апдейти не обробляються, і `docker compose ps` покаже unhealthy.
"""

import os
import sys
import time

HEARTBEAT_FILE = os.environ.get("HEARTBEAT_FILE", "data/heartbeat")
MAX_AGE_SECONDS = int(os.environ.get("HEARTBEAT_MAX_AGE", "120"))


def main() -> int:
    try:
        with open(HEARTBEAT_FILE, encoding="utf-8") as handle:
            stamp = float(handle.read().strip())
    except (OSError, ValueError) as error:
        print(f"heartbeat недоступний: {error}", file=sys.stderr)
        return 1

    age = time.time() - stamp
    if age > MAX_AGE_SECONDS:
        print(f"heartbeat застарів на {int(age)} с", file=sys.stderr)
        return 1

    print(f"ok, {int(age)} с тому")
    return 0


if __name__ == "__main__":
    sys.exit(main())
