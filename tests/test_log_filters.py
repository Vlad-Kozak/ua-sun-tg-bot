from __future__ import annotations

import logging

from bot.utils.log_filters import CONFLICT_EXPLANATION, ConflictNoiseFilter

CONFLICT_TEXT = (
    "Failed to fetch updates - TelegramConflictError: Telegram server says - "
    "Conflict: terminated by other getUpdates request; make sure that only one "
    "bot instance is running"
)


def make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="aiogram.dispatcher",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_first_conflict_is_replaced_with_explanation():
    log_filter = ConflictNoiseFilter()
    record = make_record(CONFLICT_TEXT)

    assert log_filter.filter(record) is True
    assert record.getMessage() == CONFLICT_EXPLANATION


def test_repeats_are_suppressed():
    log_filter = ConflictNoiseFilter(repeat_interval=3600)
    assert log_filter.filter(make_record(CONFLICT_TEXT)) is True

    for _ in range(20):
        assert log_filter.filter(make_record(CONFLICT_TEXT)) is False


def test_suppressed_count_is_reported_after_interval(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("bot.utils.log_filters.time.monotonic", lambda: clock["now"])

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


def test_hint_is_appended_to_explanation():
    """Підказка звужує пошук: якщо ми тримаємо лок — друга копія поза цією текою."""
    log_filter = ConflictNoiseFilter(hint="Цей екземпляр тримає data/bot.lock (host=srv, pid=7).")
    record = make_record(CONFLICT_TEXT)

    assert log_filter.filter(record) is True
    text = record.getMessage()
    assert text.startswith(CONFLICT_EXPLANATION)
    assert "host=srv, pid=7" in text


def test_hint_and_suppressed_count_coexist(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr("bot.utils.log_filters.time.monotonic", lambda: clock["now"])

    log_filter = ConflictNoiseFilter(repeat_interval=60, hint="host=srv")
    log_filter.filter(make_record(CONFLICT_TEXT))
    for _ in range(3):
        log_filter.filter(make_record(CONFLICT_TEXT))

    clock["now"] += 61
    record = make_record(CONFLICT_TEXT)
    log_filter.filter(record)
    text = record.getMessage()
    assert "host=srv" in text
    assert "приховано схожих повідомлень: 3" in text
