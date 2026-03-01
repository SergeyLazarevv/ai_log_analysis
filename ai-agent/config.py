"""Конфигурация приложения — читает env-переменные в одном месте.

Структура:
  AppConfig
    ├── graylog:  GraylogConfig   — GRAYLOG_MCP_URL, GRAYLOG_MCP_AUTH
    ├── postgres: PostgresConfig  — POSTGRES_MCP_DSN
    └── ...       YandexConfig    — YANDEX_API_KEY, YANDEX_CATALOG_ID, YANDEX_MODEL

Чтобы добавить новый сервис (GitLab и т.д.):
  1. Создать класс GitLabConfig по образцу ниже.
  2. Добавить поле gitlab: GitLabConfig в AppConfig.
  3. Добавить GitLabConnector в mcp_connector.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GraylogConfig:
    """Настройки подключения к Graylog MCP."""

    url: str
    auth: str

    @classmethod
    def from_env(cls) -> "GraylogConfig":
        return cls(
            url=os.getenv("GRAYLOG_MCP_URL", "http://127.0.0.1:9000/api/mcp"),
            auth=(os.getenv("GRAYLOG_MCP_AUTH") or "").strip(),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.auth)


@dataclass
class PostgresConfig:
    """Настройки подключения к Postgres MCP."""

    dsn: str | None

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        return cls(
            dsn=(os.getenv("POSTGRES_MCP_DSN") or "").strip() or None,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.dsn)


@dataclass
class AppConfig:
    """Корневой конфиг приложения."""

    graylog: GraylogConfig
    postgres: PostgresConfig
    yandex_api_key: str | None
    yandex_catalog_id: str | None
    yandex_model: str = "yandexgpt-lite"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            graylog=GraylogConfig.from_env(),
            postgres=PostgresConfig.from_env(),
            yandex_api_key=os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH"),
            yandex_catalog_id=os.getenv("YANDEX_CATALOG_ID"),
            yandex_model=os.getenv("YANDEX_MODEL", "yandexgpt-lite"),
        )

    def log_summary(self) -> str:
        return (
            f"GRAYLOG_MCP_URL={self.graylog.url}, "
            f"GRAYLOG_MCP_AUTH={'задан' if self.graylog.auth else 'НЕТ'}, "
            f"YANDEX={'ok' if self.yandex_api_key else 'НЕТ'}, "
            f"CATALOG_ID={'ok' if self.yandex_catalog_id else 'НЕТ'}, "
            f"POSTGRES_MCP={'вкл' if self.postgres.is_configured else 'выкл'}"
        )
