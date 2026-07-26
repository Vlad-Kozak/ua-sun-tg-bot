#!/usr/bin/env python3
"""Знаходить, хто саме займає токен бота.

Запускати на хості, де розгорнуто бота:

    python3 deploy/diagnose.py

Скрипт нічого не змінює — лише опитує Telegram і дивиться на локальні процеси.
Залежностей немає, працює на голому Python 3.

Перед перевіркою getUpdates зупиніть свого бота (`docker compose down`),
інакше він сам і буде тим «другим екземпляром».
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

API = "https://api.telegram.org"
TIMEOUT = 15


def load_token(env_file: Optional[Path] = None) -> Optional[str]:
    token = os.environ.get("BOT_TOKEN")
    if token:
        return token.strip()

    if env_file is None:
        env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


def call(token: str, method: str, **params) -> Tuple[int, dict]:
    """Повертає (http_status, тіло). Помилки Telegram теж повертаємо як тіло."""
    url = f"{API}/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "ua-sun-tg-bot-diagnose"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except Exception:  # noqa: BLE001
            return error.code, {"description": str(error)}
    except Exception as error:  # noqa: BLE001
        return 0, {"description": f"мережа недоступна: {error}"}


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check_identity(token: str) -> bool:
    section("Токен")
    status, body = call(token, "getMe")
    if not body.get("ok"):
        print(f"  ✗ токен не працює: {body.get('description')} (HTTP {status})")
        return False
    me = body["result"]
    print(f"  ✓ @{me.get('username')} (id={me.get('id')})")
    print(f"    privacy mode вимкнено: {'так' if me.get('can_read_all_group_messages') else 'НІ'}")
    return True


def check_webhook(token: str) -> None:
    section("Webhook")
    _, body = call(token, "getWebhookInfo")
    if not body.get("ok"):
        print(f"  ? не вдалося перевірити: {body.get('description')}")
        return
    info = body["result"]
    url = info.get("url") or ""
    if url:
        print(f"  ✗ налаштований webhook: {url}")
        print("    Він конфліктує з getUpdates. Прибрати: deleteWebhook")
    else:
        print("  ✓ webhook не налаштований — очікувано для polling")
    if info.get("pending_update_count"):
        print(f"    апдейтів у черзі: {info['pending_update_count']}")
    if info.get("last_error_message"):
        print(f"    остання помилка доставки: {info['last_error_message']}")


def check_conflict(token: str) -> Optional[bool]:
    """True — токен зайнятий кимось іще, False — вільний."""
    section("Хто тримає getUpdates")
    status, body = call(token, "getUpdates", timeout=0, limit=1)
    if body.get("ok"):
        print("  ✓ токен вільний — зараз ніхто інший апдейти не забирає")
        return False
    if status == 409 or "conflict" in str(body.get("description", "")).lower():
        print("  ✗ 409 Conflict — апдейти вже забирає інший екземпляр")
        print(f"    {body.get('description')}")
        return True
    print(f"  ? несподівана відповідь: HTTP {status}, {body.get('description')}")
    return None


def run(command: list) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def check_local() -> None:
    section("Що запущено на цій машині")
    found = False

    if shutil.which("docker"):
        containers = run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"])
        rows = [row for row in containers.splitlines() if "ua-sun" in row or "tg-bot" in row]
        if rows:
            found = True
            for row in rows:
                name, status, image = (row.split("|") + ["", ""])[:3]
                mark = "▶" if status.startswith("Up") else "·"
                print(f"  {mark} контейнер {name} [{status}] {image}")
        else:
            print("  · контейнерів бота не знайдено")

    processes = run(["ps", "-eo", "pid,args"])
    for line in processes.splitlines():
        if re.search(r"python.*-m\s+bot\b", line) and "diagnose" not in line:
            found = True
            print(f"  ▶ процес поза Docker: {line.strip()}")

    if shutil.which("systemctl"):
        state = run(["systemctl", "is-active", "ua-sun-tg-bot"])
        if state and state != "inactive":
            found = True
            print(f"  ▶ systemd-юніт ua-sun-tg-bot: {state}")

    if not found:
        print("  · нічого схожого на бота на цій машині не працює")


def verdict(occupied: Optional[bool]) -> int:
    section("Висновок")
    if occupied is None:
        print("  Не вдалося визначити стан. Перевірте мережу й токен.")
        return 2
    if not occupied:
        print("  Токен вільний. Піднімайте бота: docker compose up -d")
        return 0

    print("  Токен зайнятий іншим екземпляром.")
    print("  Якщо вище показано запущений контейнер чи процес — зупиніть його.")
    print("  Якщо на цій машині чисто, копія працює деінде: інший сервер,")
    print("  чужий хостинг, ноутбук колеги.")
    print()
    print("  Гарантоване рішення, коли знайти копію не вдається:")
    print("  @BotFather -> /mybots -> ваш бот -> API Token -> Revoke current token.")
    print("  Старий токен миттєво стає недійсним, і чужа копія відвалюється.")
    print("  Далі впишіть новий токен у .env і перезапустіть бота.")
    return 1


def main() -> int:
    token = load_token()
    if not token:
        print("Не знайшов BOT_TOKEN — ні в оточенні, ні в .env поруч із проєктом.")
        return 2

    print("Діагностика конфлікту getUpdates")
    print("Порада: спершу зупиніть свого бота (docker compose down),")
    print("інакше він сам і буде тим «другим екземпляром».")

    if not check_identity(token):
        return 2
    check_webhook(token)
    occupied = check_conflict(token)
    check_local()
    return verdict(occupied)


if __name__ == "__main__":
    sys.exit(main())
