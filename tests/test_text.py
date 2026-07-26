from __future__ import annotations

import pytest

from bot.utils.text import display_name, extract_mentions, normalize_tag_name, validate_tag_name


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@devs гляньте PR", ["devs"]),
        ("привіт @all", ["all"]),
        ("@devs @qa @devs", ["devs", "qa"]),
        ("@Devs і @DEVS — це один тег", ["devs"]),
        ("@бекенд треба глянути", ["бекенд"]),
        ("пошта vasyl@example.com не згадка", []),
        ("/tag_add@my_bot devs — теж не згадка", []),
        ("подвійна @@devs не рахується", []),
        ("без згадок узагалі", []),
        ("@a закоротко", []),
    ],
)
def test_extract_mentions(text, expected):
    assert extract_mentions(text) == expected


def test_extract_mentions_keeps_order():
    assert extract_mentions("@qa потім @devs потім @ops") == ["qa", "devs", "ops"]


@pytest.mark.parametrize("name", ["devs", "back-end", "qa_team", "бекенд", "team2"])
def test_valid_tag_names(name):
    assert validate_tag_name(name) is None


@pytest.mark.parametrize("name", ["a", "", "all", "everyone", "усі", "has space", "x" * 40])
def test_invalid_tag_names(name):
    assert validate_tag_name(name) is not None


def test_normalize_strips_at_and_case():
    assert normalize_tag_name("  @DevS ") == "devs"


def test_display_name_prefers_full_name():
    assert display_name("Влад", "Козак", "vlad", 1) == "Влад Козак"


def test_display_name_falls_back_to_username_then_id():
    assert display_name(None, None, "vlad", 1) == "vlad"
    assert display_name(None, None, None, 42) == "user42"


def test_display_name_is_truncated():
    result = display_name("В" * 100, None, None, 1)
    assert len(result) <= 32
    assert result.endswith("…")
