# ua-sun-tg-bot

Telegram-бот, який дозволяє кликати людей у групі **тегами замість @username** —
`@all`, `@devs`, `@qa`. Працює і для тих, у кого юзернейма немає взагалі.

```
@devs гляньте, будь ласка, PR #42
```
> 🔔 @devs
> **Оля**, **Петро**, **Ігор**

---

## Документація

| Документ | Про що |
|---|---|
| **[Розгортання](docs/deployment.md)** | від BotFather до працюючого бота на вашому сервері, бекапи, типові проблеми |
| **[Як користуватись](docs/usage.md)** | команди, сценарії, налаштування чату, FAQ |
| **[Як це працює](docs/architecture.md)** | архітектура, обмеження Telegram API, схема БД |

---

## Коротко

- `@all` працює одразу після додавання бота — нічого налаштовувати не треба
- `/rollcall` — кнопка «Я тут»: найшвидший спосіб зібрати учасників у базу
- власні теги: `/tag_create devs`, далі `/tag_add devs` реплаєм на повідомлення
- регістр не важливий, і достатньо частини назви: `@dev` покличе і `@devs`, і `@devops`
- звання з Telegram теж працюють як теги: `@sun` покличе всіх, у кого в званні є «Sun»
- згадка йде через `tg://user?id=…`, тому доходить і без `@username`
- за замовчуванням `@all` — лише для адмінів, з паузою 10 хвилин
- `/mute_me` виключає з `@all`, але лишає іменні теги
- long polling: ні домену, ні TLS, ні відкритих портів

**Два кроки, без яких бот майже марний:**

1. `@BotFather` → `/setprivacy` → **Disable** (інакше бот бачить лише команди
   і не збере список учасників)
2. зробити бота адміном групи (інакше не дізнається, хто вийшов, і не бачитиме реакцій)

Чому саме так — [architecture.md](docs/architecture.md#звідки-береться-список-учасників).

---

## Запуск за три команди

```bash
cp .env.example .env          # вписати BOT_TOKEN
mkdir -p data && sudo chown -R 1000:1000 data
docker compose up -d --build
```

Повна інструкція — [docs/deployment.md](docs/deployment.md).

---

## Стек

Python 3.12 (сумісно з 3.9+) · aiogram 3 · SQLAlchemy 2 async · SQLite · Alembic · Docker

## Розробка

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest        # 194 тести
.venv/bin/ruff check .
```

Зміна схеми БД:

```bash
.venv/bin/alembic revision --autogenerate -m "опис"
.venv/bin/alembic upgrade head
```
