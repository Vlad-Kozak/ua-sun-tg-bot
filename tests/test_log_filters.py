from __future__ import annotations

import logging

import pytest

from bot.utils.log_filters import (
    CONFLICT_EXPLANATION,
    TRANSIENT_CONFLICT_EXPLANATION,
    ConflictNoiseFilter,
)

CONFLICT_TEXT = (
    "Failed to fetch updates - TelegramConflictError: Telegram server says - "
    "Conflict: terminated by other getUpdates request; make sure that only one "
    "bot instance is running"
)
SLEEP_TEXT = "Sleep for 1.000000 seconds and try again... (tryings = 0, bot id = 42)"
RECOVERY_TEXT = "Connection established (tryings = 3, bot id = 42)"


def make_record(message: str, level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord(
        name="aiogram.dispatcher",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


@pytest.fixture()
def clock(monkeypatch):
    state = {"now": 1000.0}
    monkeypatch.setattr("bot.utils.log_filters.time.monotonic", lambda: state["now"])
    return state


def test_first_conflict_is_explained_as_transient():
    """Короткий конфлікт — це найчастіше власний обірваний запит, а не друга копія."""
    log_filter = ConflictNoiseFilter()
    record = make_record(CONFLICT_TEXT)

    assert log_filter.filter(record) is True
    assert record.getMessage() == TRANSIENT_CONFLICT_EXPLANATION
    assert record.levelno == logging.WARNING


def test_long_streak_escalates_to_second_instance(clock):
    log_filter = ConflictNoiseFilter(repeat_interval=60, escalate_after=180)
    log_filter.filter(make_record(CONFLICT_TEXT))

    clock["now"] += 200
    record = make_record(CONFLICT_TEXT)
    assert log_filter.filter(record) is True
    text = record.getMessage()
    assert text.startswith(CONFLICT_EXPLANATION)
    assert "200 с" in text
    assert record.levelno == logging.ERROR


def test_recovery_resets_streak(clock):
    """«Connection established» обриває смугу — наступний конфлікт знову тимчасовий."""
    log_filter = ConflictNoiseFilter(repeat_interval=0, escalate_after=180)
    log_filter.filter(make_record(CONFLICT_TEXT))

    clock["now"] += 200
    assert log_filter.filter(make_record(RECOVERY_TEXT, level=logging.INFO)) is True

    clock["now"] += 1
    record = make_record(CONFLICT_TEXT)
    assert log_filter.filter(record) is True
    assert record.getMessage() == TRANSIENT_CONFLICT_EXPLANATION


def test_repeats_are_suppressed():
    log_filter = ConflictNoiseFilter(repeat_interval=3600)
    assert log_filter.filter(make_record(CONFLICT_TEXT)) is True

    for _ in range(20):
        assert log_filter.filter(make_record(CONFLICT_TEXT)) is False


def test_sleep_after_suppressed_conflict_is_swallowed():
    """Без цього в лозі лишаються «Sleep for…» без пояснення, до чого вони."""
    log_filter = ConflictNoiseFilter(repeat_interval=3600)
    log_filter.filter(make_record(CONFLICT_TEXT))
    assert log_filter.filter(make_record(SLEEP_TEXT, level=logging.WARNING)) is True

    assert log_filter.filter(make_record(CONFLICT_TEXT)) is False
    assert log_filter.filter(make_record(SLEEP_TEXT, level=logging.WARNING)) is False
    # Ковтаємо лише один «Sleep» на один прихований конфлікт.
    assert log_filter.filter(make_record(SLEEP_TEXT, level=logging.WARNING)) is True


def test_sleep_after_network_error_passes_through():
    log_filter = ConflictNoiseFilter()
    record = make_record(SLEEP_TEXT, level=logging.WARNING)

    assert log_filter.filter(record) is True
    assert record.getMessage() == SLEEP_TEXT


def test_suppressed_count_is_reported_after_interval(clock):
    log_filter = ConflictNoiseFilter(repeat_interval=60)
    log_filter.filter(make_record(CONFLICT_TEXT))
    for _ in range(5):
        log_filter.filter(make_record(CONFLICT_TEXT))

    clock["now"] += 61
    record = make_record(CONFLICT_TEXT)
    assert log_filter.filter(record) is True
    assert "приховано схожих повідомлень: 5" in record.getMessage()


def test_unrelated_records_pass_through_untouched():
    log_filter = ConflictNoiseFilter()
    record = make_record("Звичайне повідомлення")

    assert log_filter.filter(record) is True
    assert record.getMessage() == "Звичайне повідомлення"


def test_filter_survives_broken_record():
    """Фільтр логів не має ламати логування, навіть якщо запис кривий."""
    log_filter = ConflictNoiseFilter()
    record = make_record("%d невідповідні аргументи")
    record.args = ("не число",)

    assert log_filter.filter(record) is True


def test_hint_is_appended_when_escalated(clock):
    """Підказка звужує пошук: якщо ми тримаємо лок — друга копія поза цією текою."""
    log_filter = ConflictNoiseFilter(
        repeat_interval=60,
        hint="Цей екземпляр тримає data/bot.lock (host=srv, pid=7).",
        escalate_after=180,
    )
    log_filter.filter(make_record(CONFLICT_TEXT))
    for _ in range(3):
        log_filter.filter(make_record(CONFLICT_TEXT))

    clock["now"] += 200
    record = make_record(CONFLICT_TEXT)
    log_filter.filter(record)
    text = record.getMessage()
    assert "host=srv, pid=7" in text
    assert "приховано схожих повідомлень: 3" in text


def test_hint_is_not_shown_for_transient_conflict():
    log_filter = ConflictNoiseFilter(hint="host=srv")
    record = make_record(CONFLICT_TEXT)

    log_filter.filter(record)
    assert "host=srv" not in record.getMessage()
