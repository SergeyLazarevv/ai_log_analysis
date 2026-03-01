"""Postgres MCP коннектор — подключение через stdio (npx)."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from .base import BaseMCPConnector

log = logging.getLogger("logs_ai.connectors.postgres")


class PostgresConnector(BaseMCPConnector):
    """
    Запускает Postgres MCP сервер как дочерний процесс через npx и общается
    с ним по stdin/stdout протоколу MCP.

    Конфиг из env:
      POSTGRES_MCP_DSN — строка подключения postgresql://user:pass@host:port/db

    Требования:
      Node.js (npx) — для запуска @modelcontextprotocol/server-postgres.
      Если npx не найден — коннектор пропускается без падения всего агента.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._session = None
        self._tools: list[dict] = []

    @property
    def is_configured(self) -> bool:
        return bool(self._dsn)

    async def connect(self, stack: AsyncExitStack) -> None:
        try:
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp import ClientSession
        except ImportError:
            log.warning("[Postgres] mcp.client.stdio недоступен — пропускаем")
            return

        try:
            log.info("[Postgres] Запуск npx @modelcontextprotocol/server-postgres")
            params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-postgres", self._dsn.strip()],
                env=None,
            )
            (read, write) = await stack.enter_async_context(stdio_client(params))
            self._session = await stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            log.info("[Postgres] Сессия инициализирована")

            result = await self._session.list_tools()
            self._tools = [self._to_schema(t) for t in result.tools]
            log.info("[Postgres] Инструментов: %d", len(self._tools))
        except FileNotFoundError as e:
            log.warning("[Postgres] npx не найден — пропускаем: %s", e)
        except Exception as e:
            log.warning("[Postgres] Недоступен — пропускаем: %s", e)

    @property
    def tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, args: dict) -> str:
        if not self._session:
            return "Ошибка: Postgres не подключён"
        try:
            log.info("[Postgres] call_tool(%s, %s)", name, args)
            result = await self._session.call_tool(name, args)
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            if result.isError:
                log.warning("[Postgres] %s вернул ошибку: %s", name, text[:300])
                return f"Ошибка: {text}"
            log.info("[Postgres] %s выполнен, результат: %d символов", name, len(text))
            return text
        except Exception as e:
            log.exception("[Postgres] Исключение при вызове %s: %s", name, e)
            return f"Ошибка вызова инструмента: {e}"

    @staticmethod
    def _to_schema(t) -> dict:
        return {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema or {},
        }
