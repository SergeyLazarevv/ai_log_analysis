"""Application configuration — reads env vars in one place."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class AppConfig:
    graylog_url: str
    graylog_auth: str
    postgres_dsn: str | None
    yandex_api_key: str | None
    yandex_catalog_id: str | None
    yandex_model: str = "yandexgpt-lite"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            graylog_url=os.getenv("GRAYLOG_MCP_URL", "http://127.0.0.1:9000/api/mcp"),
            graylog_auth=(os.getenv("GRAYLOG_MCP_AUTH") or "").strip(),
            postgres_dsn=(os.getenv("POSTGRES_MCP_DSN") or "").strip() or None,
            yandex_api_key=os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH"),
            yandex_catalog_id=os.getenv("YANDEX_CATALOG_ID"),
            yandex_model=os.getenv("YANDEX_MODEL", "yandexgpt-lite"),
        )

    def log_summary(self) -> str:
        return (
            f"GRAYLOG_MCP_URL={self.graylog_url}, "
            f"GRAYLOG_MCP_AUTH={'задан' if self.graylog_auth else 'НЕТ'}, "
            f"YANDEX={'ok' if self.yandex_api_key else 'НЕТ'}, "
            f"CATALOG_ID={'ok' if self.yandex_catalog_id else 'НЕТ'}, "
            f"POSTGRES_MCP={'вкл' if self.postgres_dsn else 'выкл'}"
        )
