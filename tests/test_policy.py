from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.db.models import Chat
from bot.services.policy import is_quiet_now
from bot.utils.time import format_duration


def make_chat(**kwargs) -> Chat:
    defaults = dict(
        chat_id=-100,
        timezone="Europe/Kyiv",
        quiet_hours_enabled=True,
        quiet_start=23,
        quiet_end=8,
    )
    defaults.update(kwargs)
    return Chat(**defaults)


def utc(hour: int) -> datetime:
    return datetime(2026, 1, 15, hour, 0, tzinfo=timezone.utc)


def test_quiet_disabled_is_never_quiet():
    assert is_quiet_now(make_chat(quiet_hours_enabled=False), utc(1)) is False


def test_overnight_interval_covers_both_sides_of_midnight():
    chat = make_chat()  # Київ узимку = UTC+2
    assert is_quiet_now(chat, utc(22)) is True  # 00:00 за Києвом
    assert is_quiet_now(chat, utc(4)) is True  # 06:00 за Києвом
    assert is_quiet_now(chat, utc(12)) is False  # 14:00 за Києвом


def test_daytime_interval():
    chat = make_chat(quiet_start=9, quiet_end=18, timezone="UTC")
    assert is_quiet_now(chat, utc(10)) is True
    assert is_quiet_now(chat, utc(20)) is False


def test_equal_bounds_mean_no_quiet_hours():
    assert is_quiet_now(make_chat(quiet_start=5, quiet_end=5), utc(5)) is False


def test_unknown_timezone_falls_back_to_utc():
    chat = make_chat(timezone="Middle/Earth", quiet_start=9, quiet_end=18)
    assert is_quiet_now(chat, utc(10)) is True


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(5, "5 с"), (60, "1 хв"), (90, "1 хв 30 с"), (3600, "1 год"), (5400, "1 год 30 хв")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected
