from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: SecretStr
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    log_level: str = "INFO"
    #: Файл-мітка «цикл обробки живий», який перевіряє healthcheck контейнера.
    heartbeat_file: str = "data/heartbeat"
    #: Файл блокування: не дає двом копіям бота ділити один токен.
    lock_file: str = "data/bot.lock"
    #: Рядок "1,2,3". Свідомо не List[int]: pydantic-settings пробує json.loads
    #: для складених типів ще до валідаторів, і порожній OWNER_IDS= ламав старт.
    owner_ids: str = ""

    mention_batch_size: int = Field(default=6, ge=1, le=20)
    mention_batch_delay: float = Field(default=0.35, ge=0.0, le=10.0)

    default_all_policy: str = "admins"
    default_tag_policy: str = "admins"
    default_cooldown_seconds: int = Field(default=600, ge=0)
    default_timezone: str = "Europe/Kyiv"
    default_quiet_hours_enabled: bool = True
    default_quiet_start: int = Field(default=23, ge=0, le=23)
    default_quiet_end: int = Field(default=8, ge=0, le=23)

    @property
    def owner_id_list(self) -> List[int]:
        return [int(part.strip()) for part in self.owner_ids.split(",") if part.strip()]

    @field_validator("default_all_policy", "default_tag_policy")
    @classmethod
    def _check_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"admins", "members"}:
            raise ValueError("політика має бути 'admins' або 'members'")
        return normalized

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"невідомий рівень логування: {value}")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # значення підтягуються з .env
