"""MCPConnector — оркестратор подключений к MCP-серверам.

Не содержит логики конкретных сервисов — только собирает коннекторы,
запускает их и маршрутизирует вызовы инструментов.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from config import AppConfig
from connectors import BaseMCPConnector, GraylogConnector, PostgresConnector

log = logging.getLogger("logs_ai.mcp")


class MCPConnector:
    """
    Async context manager — подключает все настроенные MCP-серверы
    и предоставляет единый интерфейс для вызова инструментов.

    Пример:
        async with MCPConnector.from_config(config) as mcp:
            result = await mcp.call_tool("query", {"sql": "SELECT 1"})
    """

    def __init__(self, connectors: list[BaseMCPConnector]) -> None:
        self._connectors = connectors
        self._stack = AsyncExitStack()
        self._tool_to_connector: dict[str, BaseMCPConnector] = {}
        self._tools: list[dict] = []

    @classmethod
    def from_config(cls, config: AppConfig) -> "MCPConnector":
        """Собрать список коннекторов из конфига приложения."""
        connectors: list[BaseMCPConnector] = [
            GraylogConnector(config.graylog.url, config.graylog.auth),
        ]
        if config.postgres.is_configured:
            connectors.append(PostgresConnector(config.postgres.dsn))  # type: ignore[arg-type]
        return cls(connectors)

    # ── публичный интерфейс ────────────────────────────────────────────────

    @property
    def tools(self) -> list[dict]:
        """Все инструменты со всех подключённых коннекторов."""
        return self._tools

    @property
    def tool_names(self) -> list[str]:
        return [t["name"] for t in self._tools]

    async def call_tool(self, name: str, args: dict) -> str:
        """Маршрутизировать вызов в нужный коннектор."""
        connector = self._tool_to_connector.get(name)
        if not connector:
            known = ", ".join(self._tool_to_connector.keys())
            return f"Ошибка: неизвестный инструмент {name}. Доступны: {known}"
        return await connector.call_tool(name, args)

    # ── async context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> "MCPConnector":
        for connector in self._connectors:
            if not connector.is_configured:
                log.info("[MCP] %s пропущен (не настроен)", type(connector).__name__)
                continue
            await connector.connect(self._stack)
            for tool in connector.tools:
                self._tools.append(tool)
                self._tool_to_connector[tool["name"]] = connector

        log.info("[MCP] Всего инструментов: %d", len(self._tools))
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()
