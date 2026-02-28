"""MCP session manager — подключение к Graylog MCP и опционально Postgres MCP."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

import httpx

# Graylog 7.x поддерживает только 2025-06-18; MCP SDK по умолчанию шлёт более новую
import mcp.types as _mcp_types
_mcp_types.LATEST_PROTOCOL_VERSION = "2025-06-18"

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

try:
    from mcp.client.stdio import StdioServerParameters, stdio_client
    _STDIO_AVAILABLE = True
except ImportError:
    _STDIO_AVAILABLE = False

log = logging.getLogger("logs_ai.mcp")

# Патчим валидацию ClientSession: Graylog возвращает ISO-строку там,
# где MCP-schema ожидает object (effective_timerange.to).
_orig_validate = ClientSession._validate_tool_result


async def _patched_validate(self, name: str, result) -> None:
    try:
        await _orig_validate(self, name, result)
    except RuntimeError as e:
        if "Invalid structured content" in str(e) or "is not of type" in str(e):
            log.warning("[MCP] Graylog schema mismatch для %s (игнорируем): %s", name, str(e)[:150])
        else:
            raise


ClientSession._validate_tool_result = _patched_validate


class MCPConnector:
    """
    Async context manager для одновременного подключения к Graylog MCP
    и (опционально) Postgres MCP.

    Пример:
        async with MCPConnector(graylog_url, auth, postgres_dsn) as conn:
            result = await conn.call_tool("aggregate_messages", {...})
    """

    def __init__(
        self,
        graylog_url: str,
        graylog_auth_header: str,
        postgres_dsn: str | None = None,
    ) -> None:
        self._graylog_url = graylog_url
        self._auth_header = graylog_auth_header
        self._postgres_dsn = postgres_dsn
        self._stack = AsyncExitStack()
        self._tool_to_session: dict[str, Any] = {}
        self._tools: list[dict] = []

    # ── публичный интерфейс ────────────────────────────────────────────────

    @property
    def tools(self) -> list[dict]:
        """Все инструменты со всех подключённых MCP-серверов."""
        return self._tools

    @property
    def tool_names(self) -> list[str]:
        return [t["name"] for t in self._tools]

    async def call_tool(self, tool_name: str, tool_args: dict) -> str:
        """Вызывает инструмент в правильной MCP-сессии, возвращает текст результата."""
        session = self._tool_to_session.get(tool_name)
        if not session:
            known = ", ".join(self._tool_to_session.keys())
            return f"Ошибка: неизвестный инструмент {tool_name}. Доступны: {known}"

        try:
            log.info("[MCP] call_tool(%s, %s)", tool_name, tool_args)
            result = await session.call_tool(tool_name, tool_args)
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            if result.isError:
                log.warning("[MCP] %s вернул ОШИБКУ: %s", tool_name, text[:300])
                return f"Ошибка: {text}"
            log.info("[MCP] %s выполнен, результат: %d символов", tool_name, len(text))
            return text
        except Exception as e:
            log.exception("[MCP] Исключение при вызове %s: %s", tool_name, e)
            return f"Ошибка вызова инструмента: {e}"

    # ── async context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> "MCPConnector":
        log.info("[MCP] Подключение к Graylog MCP: %s", self._graylog_url)
        headers = {"Authorization": self._auth_header} if self._auth_header else {}
        http_client = await self._stack.enter_async_context(
            httpx.AsyncClient(headers=headers, timeout=60.0)
        )
        (read, write, _) = await self._stack.enter_async_context(
            streamable_http_client(self._graylog_url, http_client=http_client)
        )
        gray_session = await self._stack.enter_async_context(ClientSession(read, write))
        await gray_session.initialize()
        log.info("[MCP] Graylog MCP сессия инициализирована")

        gray_tools = await gray_session.list_tools()
        self._tools = [self._tool_schema(t) for t in gray_tools.tools]
        self._tool_to_session = {t.name: gray_session for t in gray_tools.tools}

        if self._postgres_dsn:
            await self._connect_postgres()

        log.info("[MCP] Всего инструментов: %d", len(self._tools))
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    # ── приватные методы ───────────────────────────────────────────────────

    async def _connect_postgres(self) -> None:
        if not _STDIO_AVAILABLE:
            log.warning("[MCP] POSTGRES_MCP_DSN задан, но mcp.client.stdio недоступен — только Graylog")
            return
        try:
            params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-postgres", (self._postgres_dsn or "").strip()],
                env=None,
            )
            (pg_read, pg_write) = await self._stack.enter_async_context(stdio_client(params))
            pg_session = await self._stack.enter_async_context(ClientSession(pg_read, pg_write))
            await pg_session.initialize()
            log.info("[MCP] Postgres MCP сессия инициализирована")
            pg_tools = await pg_session.list_tools()
            self._tools.extend(self._tool_schema(t) for t in pg_tools.tools)
            self._tool_to_session.update({t.name: pg_session for t in pg_tools.tools})
        except FileNotFoundError as e:
            log.warning("[MCP] Postgres MCP пропущен (npx не найден): %s. Только Graylog.", e)
        except Exception as e:
            log.warning("[MCP] Postgres MCP недоступен (только Graylog): %s", e)

    @staticmethod
    def _tool_schema(t) -> dict:
        return {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema or {}}
