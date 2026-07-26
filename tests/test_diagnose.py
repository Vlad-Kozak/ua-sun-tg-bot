"""Скрипт діагностики має правильно розпізнавати стан токена.

Перевіряємо саме логіку висновків: користувач запускає його раз, у стресовій
ситуації, і хибний діагноз коштує години пошуку не там.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "diagnose.py"


def load_module():
    spec = importlib.util.spec_from_file_location("diagnose", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def diagnose():
    return load_module()


def test_conflict_is_detected_by_http_409(diagnose, monkeypatch, capsys):
    monkeypatch.setattr(
        diagnose,
        "call",
        lambda *a, **k: (409, {"ok": False, "description": "Conflict: terminated by other"}),
    )
    assert diagnose.check_conflict("token") is True
    assert "409 Conflict" in capsys.readouterr().out


def test_conflict_is_detected_by_description_alone(diagnose, monkeypatch):
    """Деякі проксі віддають 200 із текстом помилки — теж має спрацювати."""
    monkeypatch.setattr(
        diagnose,
        "call",
        lambda *a, **k: (200, {"ok": False, "description": "Conflict: terminated"}),
    )
    assert diagnose.check_conflict("token") is True


def test_free_token_reports_no_conflict(diagnose, monkeypatch, capsys):
    monkeypatch.setattr(diagnose, "call", lambda *a, **k: (200, {"ok": True, "result": []}))
    assert diagnose.check_conflict("token") is False
    assert "вільний" in capsys.readouterr().out


def test_unexpected_answer_is_inconclusive(diagnose, monkeypatch):
    monkeypatch.setattr(
        diagnose, "call", lambda *a, **k: (500, {"ok": False, "description": "server error"})
    )
    assert diagnose.check_conflict("token") is None


def test_webhook_is_flagged(diagnose, monkeypatch, capsys):
    monkeypatch.setattr(
        diagnose,
        "call",
        lambda *a, **k: (200, {"ok": True, "result": {"url": "https://example.com/hook"}}),
    )
    diagnose.check_webhook("token")
    out = capsys.readouterr().out
    assert "налаштований webhook" in out
    assert "example.com/hook" in out


def test_no_webhook_is_expected_for_polling(diagnose, monkeypatch, capsys):
    monkeypatch.setattr(
        diagnose, "call", lambda *a, **k: (200, {"ok": True, "result": {"url": ""}})
    )
    diagnose.check_webhook("token")
    assert "не налаштований" in capsys.readouterr().out


def test_verdict_suggests_revoking_token_when_occupied(diagnose, capsys):
    assert diagnose.verdict(True) == 1
    out = capsys.readouterr().out
    assert "Revoke current token" in out


def test_verdict_is_clean_when_free(diagnose, capsys):
    assert diagnose.verdict(False) == 0
    assert "Токен вільний" in capsys.readouterr().out


def test_token_is_read_from_environment(diagnose, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "  123:abc  ")
    assert diagnose.load_token() == "123:abc"


def test_token_is_read_from_env_file(diagnose, monkeypatch, tmp_path):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('# коментар\nLOG_LEVEL=INFO\nBOT_TOKEN="777:xyz"\n', encoding="utf-8")

    assert diagnose.load_token(env_file) == "777:xyz"


def test_environment_wins_over_env_file(diagnose, monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_TOKEN", "1:from-env")
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TOKEN=2:from-file\n", encoding="utf-8")

    assert diagnose.load_token(env_file) == "1:from-env"


def test_missing_env_file_returns_none(diagnose, monkeypatch, tmp_path):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    assert diagnose.load_token(tmp_path / "нема.env") is None


def test_local_scan_survives_missing_tools(diagnose, monkeypatch, capsys):
    monkeypatch.setattr(diagnose.shutil, "which", lambda name: None)
    monkeypatch.setattr(diagnose, "run", lambda cmd: "")
    diagnose.check_local()
    assert "нічого схожого" in capsys.readouterr().out


def test_local_scan_reports_running_container(diagnose, monkeypatch, capsys):
    monkeypatch.setattr(diagnose.shutil, "which", lambda name: "/usr/bin/" + name)

    def fake_run(command):
        if command[0] == "docker":
            return "ua-sun-tg-bot|Up 2 hours|ua-sun-tg-bot:latest"
        if command[0] == "systemctl":
            return "inactive"
        return ""

    monkeypatch.setattr(diagnose, "run", fake_run)
    diagnose.check_local()
    out = capsys.readouterr().out
    assert "▶ контейнер ua-sun-tg-bot" in out
