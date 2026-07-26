from __future__ import annotations

import pytest

from bot.config import Settings


def make(**env) -> Settings:
    return Settings(_env_file=None, bot_token="1:x", **env)  # type: ignore[arg-type]


def test_empty_owner_ids_does_not_break_startup():
    """Регресія: .env.example містить порожній OWNER_IDS=, і на ньому бот падав."""
    assert make(owner_ids="").owner_id_list == []


def test_owner_ids_are_parsed_from_csv():
    assert make(owner_ids="1, 2,3").owner_id_list == [1, 2, 3]


def test_owner_ids_default_is_empty():
    assert make().owner_id_list == []


def test_env_file_values_are_read(tmp_path, monkeypatch):
    """Той самий вміст, що й у .env.example, має підніматися без помилок."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT_TOKEN=123:abc\n"
        "OWNER_IDS=\n"
        "LOG_LEVEL=DEBUG\n"
        "MENTION_BATCH_SIZE=6\n"
        "DEFAULT_QUIET_HOURS_ENABLED=true\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]
    assert settings.bot_token.get_secret_value() == "123:abc"
    assert settings.owner_id_list == []
    assert settings.log_level == "DEBUG"
    assert settings.default_quiet_hours_enabled is True


def test_invalid_policy_is_rejected():
    with pytest.raises(ValueError):
        make(default_all_policy="everyone")


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValueError):
        make(log_level="LOUD")
