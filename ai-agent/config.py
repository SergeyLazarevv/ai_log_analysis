"""Конфигурация приложения — читает env-переменные в одном месте.

Структура:
  AppConfig
    ├── graylog:  GraylogConfig  — GRAYLOG_MCP_URL, GRAYLOG_MCP_AUTH
    ├── postgres: PostgresConfig — POSTGRES_MCP_DSN
    ├── gitlab:   GitLabConfig   — GITLAB_URL, GITLAB_TOKEN
    └── ...

Чтобы добавить новый сервис:
  1. Создать класс XxxConfig по образцу ниже.
  2. Добавить поле xxx: XxxConfig в AppConfig.
  3. Создать connectors/xxx.py с классом XxxConnector(BaseMCPConnector).
  4. Добавить коннектор в MCPConnector.from_config().
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
class GitLabConfig:
    """Настройки подключения к GitLab REST API v4.

    Токен необязателен — без него доступны только публичные проекты.
    Personal Access Token (права: read_api) нужен для приватных проектов.
    """

    url: str
    token: str

    @classmethod
    def from_env(cls) -> "GitLabConfig":
        return cls(
            url=(os.getenv("GITLAB_URL") or "").strip().rstrip("/"),
            token=(os.getenv("GITLAB_TOKEN") or "").strip(),
        )

    @property
    def is_configured(self) -> bool:
        # Токен необязателен: без него работаем анонимно (только публичные проекты)
        return bool(self.url)


@dataclass
class AppConfig:
    """Корневой конфиг приложения."""

    graylog: GraylogConfig
    postgres: PostgresConfig
    gitlab: GitLabConfig
    yandex_api_key: str | None
    yandex_catalog_id: str | None
    yandex_model: str = "yandexgpt-lite"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            graylog=GraylogConfig.from_env(),
            postgres=PostgresConfig.from_env(),
            gitlab=GitLabConfig.from_env(),
            yandex_api_key=os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH"),
            yandex_catalog_id=os.getenv("YANDEX_CATALOG_ID"),
            yandex_model=os.getenv("YANDEX_MODEL", "yandexgpt-lite"),
        )

    def log_summary(self) -> str:
        return (
            f"GRAYLOG_MCP_URL={self.graylog.url}, "
            f"GRAYLOG_MCP_AUTH={'задан' if self.graylog.auth else 'НЕТ'}, "
            f"GITLAB={'вкл' if self.gitlab.is_configured else 'выкл'}, "
            f"YANDEX={'ok' if self.yandex_api_key else 'НЕТ'}, "
            f"CATALOG_ID={'ok' if self.yandex_catalog_id else 'НЕТ'}, "
            f"POSTGRES_MCP={'вкл' if self.postgres.is_configured else 'выкл'}"
        )
