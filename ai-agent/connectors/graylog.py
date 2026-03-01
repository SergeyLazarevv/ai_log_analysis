"""Graylog MCP коннектор — подключение по HTTP (Streamable HTTP)."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

import httpx

# Graylog 7.x поддерживает только версию протокола 2025-06-18;
# MCP SDK по умолчанию может отправлять более новую.
import mcp.types as _mcp_types
_mcp_types.LATEST_PROTOCOL_VERSION = "2025-06-18"

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .base import BaseMCPConnector

log = logging.getLogger("logs_ai.connectors.graylog")

# Патч валидации ClientSession: Graylog возвращает ISO-строку там,
# где MCP-схема ожидает object (поле effective_timerange.to).
_orig_validate = ClientSession._validate_tool_result


async def _patched_validate(self, name: str, result) -> None:
    try:
        await _orig_validate(self, name, result)
    except RuntimeError as e:
        if "Invalid structured content" in str(e) or "is not of type" in str(e):
            log.warning("[Graylog] Schema mismatch для %s (игнорируем): %s", name, str(e)[:150])
        else:
            raise


ClientSession._validate_tool_result = _patched_validate


class GraylogConnector(BaseMCPConnector):
    """
    Подключается к Graylog MCP по HTTP.

    Конфиг из env:
      GRAYLOG_MCP_URL  — URL эндпоинта MCP (по умолчанию http://127.0.0.1:9000/api/mcp)
      GRAYLOG_MCP_AUTH — заголовок Authorization (Basic <base64(TOKEN:token)>)
    """

    def __init__(self, url: str, auth: str) -> None:
        self._url = url
        self._auth = auth
        self._session: ClientSession | None = None
        self._tools: list[dict] = []

    @property
    def is_configured(self) -> bool:
        return bool(self._url and self._auth)

    async def connect(self, stack: AsyncExitStack) -> None:
        log.info("[Graylog] Подключение к %s", self._url)
        headers = {"Authorization": self._auth} if self._auth else {}
        http_client = await stack.enter_async_context(
            httpx.AsyncClient(headers=headers, timeout=60.0)
        )
        (read, write, _) = await stack.enter_async_context(
            streamable_http_client(self._url, http_client=http_client)
        )
        self._session = await stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        log.info("[Graylog] Сессия инициализирована")

        result = await self._session.list_tools()
        self._tools = [self._to_schema(t) for t in result.tools]
        log.info("[Graylog] Инструментов: %d", len(self._tools))

    @property
    def tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, args: dict) -> str:
        if not self._session:
            return "Ошибка: Graylog не подключён"
        try:
            log.info("[Graylog] call_tool(%s, %s)", name, args)
            result = await self._session.call_tool(name, args)
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            if result.isError:
                log.warning("[Graylog] %s вернул ошибку: %s", name, text[:300])
                return f"Ошибка: {text}"
            log.info("[Graylog] %s выполнен, результат: %d символов", name, len(text))
            return text
        except Exception as e:
            log.exception("[Graylog] Исключение при вызове %s: %s", name, e)
            return f"Ошибка вызова инструмента: {e}"

    @staticmethod
    def _to_schema(t) -> dict:
        return {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema or {},
        }
