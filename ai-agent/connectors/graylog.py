"""Graylog MCP коннектор — подключение по HTTP (Streamable HTTP)."""

from __future__ import annotations

import json
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

    # Поля которые всегда запрашиваем при поиске сообщений
    _SEARCH_FIELDS = [
        "source", "timestamp", "message", "full_message", "level",
        "_exception_class", "_exception_message", "_stack_trace",
        "_component", "_event", "_order_id",
    ]

    async def call_tool(self, name: str, args: dict) -> str:
        if not self._session:
            return "Ошибка: Graylog не подключён"
        try:
            # Для search_messages всегда запрашиваем нужные поля
            if name == "search_messages" and "fields" not in args:
                args = {**args, "fields": self._SEARCH_FIELDS}

            log.info("[Graylog] call_tool(%s, %s)", name, args)
            result = await self._session.call_tool(name, args)
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            if result.isError:
                log.warning("[Graylog] %s вернул ошибку: %s", name, text[:300])
                return f"Ошибка: {text}"
            log.info("[Graylog] %s выполнен, результат: %d символов", name, len(text))

            if name == "search_messages":
                formatted = self._format_messages(text)
                if formatted:
                    log.info("[Graylog] search_messages отформатирован: %d символов", len(formatted))
                    return formatted

            return text
        except Exception as e:
            log.exception("[Graylog] Исключение при вызове %s: %s", name, e)
            return f"Ошибка вызова инструмента: {e}"

    @staticmethod
    def _format_messages(raw: str) -> str | None:
        """
        Парсит JSON-ответ search_messages и форматирует сообщения
        с акцентом на full_message / _stack_trace для анализа ошибок.

        Graylog MCP возвращает табличный формат:
          {"schema": [{"field": "source"}, ...], "datarows": [["val1", ...], ...], "metadata": {...}}
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        # ── Табличный формат Graylog MCP (schema + datarows) ───────────────
        if "schema" in data and "datarows" in data:
            schema = data["schema"]
            datarows = data["datarows"]
            # Имена колонок из схемы
            columns = [col.get("field") or col.get("name", f"col{i}") for i, col in enumerate(schema)]

            if not datarows:
                return "Найдено 0 сообщений."

            # Один раз логируем имена полей ответа (для отладки, если трейс не находится)
            log.debug("[Graylog] Поля ответа search_messages: %s", columns)

            _LEVELS = {3: "Error", 4: "Warning", 5: "Notice", 6: "Info", 7: "Debug"}
            _LABELS = {
                "timestamp":          "Время",
                "source":             "Источник",
                "level":              "Уровень",
                "message":            "Сообщение",
                "_exception_class":   "Исключение",
                "_exception_message": "Текст исклч",
                "_component":         "Компонент",
                "_event":             "Событие",
                "_order_id":          "Заказ",
            }

            lines = [f"Найдено сообщений: {len(datarows)}\n"]

            for i, row in enumerate(datarows, 1):
                msg = dict(zip(columns, row))
                lines.append(f"── Запись {i} " + "─" * 40)

                # Обычные поля
                for col in ["timestamp", "source", "level", "message",
                            "_exception_class", "_exception_message",
                            "_component", "_event", "_order_id"]:
                    val = msg.get(col)
                    if val is None:
                        continue
                    if col == "level":
                        try:
                            val = _LEVELS.get(int(val), str(val))
                        except (ValueError, TypeError):
                            pass
                    label = _LABELS.get(col, col)
                    lines.append(f"{label}: {val}")

                # Стектрейс — самое важное для анализа ошибок (Graylog может отдавать поле с _ или без)
                stack = msg.get("_stack_trace") or msg.get("stack_trace")
                full_msg = msg.get("full_message")
                short_msg = msg.get("message", "")
                if not stack and not full_msg:
                    for k, v in msg.items():
                        if v and isinstance(v, str) and ("stack" in k.lower() or "trace" in k.lower() or k == "full_message"):
                            stack = stack or v
                            break
                # Если по имени поля не нашли — ищем по содержимому (типичный PHP/ Laravel трейс)
                if not stack and not full_msg:
                    for v in msg.values():
                        if isinstance(v, str) and len(v) > 100 and ("#0 " in v or "Stack trace:" in v) and (".php(" in v or "/app/" in v):
                            stack = v
                            break
                full_msg = full_msg or stack

                trace_text = stack or (full_msg if (full_msg and full_msg != short_msg) else None)
                if trace_text:
                    root = GraylogConnector._extract_root_cause(str(trace_text))
                    if root:
                        lines.append(f"Корневая причина: {root}")
                    lines.append(f"Стектрейс:\n{str(trace_text)[:3000]}")
                elif i == 1:
                    log.warning(
                        "[Graylog] В первой записи нет трейса. Поля ответа: %s. Проверьте, что в fields переданы full_message и _stack_trace.",
                        columns,
                    )

                lines.append("")

            return "\n".join(lines)

        # ── Старый формат: {"messages": [...]} ─────────────────────────────
        messages = (
            data.get("messages") or data.get("results")
            or data.get("data") or data.get("hits") or []
        )
        if not messages:
            return "Найдено 0 сообщений."

        _LEVELS = {3: "Error", 4: "Warning", 5: "Notice", 6: "Info", 7: "Debug"}
        lines = [f"Найдено сообщений: {len(messages)}\n"]

        for i, entry in enumerate(messages, 1):
            msg = entry.get("message", entry) if isinstance(entry, dict) else {}
            if not isinstance(msg, dict):
                continue

            lines.append(f"── Запись {i} " + "─" * 40)

            for col, label in [("timestamp", "Время"), ("source", "Источник")]:
                val = msg.get(col, "")
                if val:
                    lines.append(f"{label}: {val}")

            raw_level = msg.get("level")
            if raw_level is not None:
                lines.append(f"Уровень: {_LEVELS.get(int(raw_level), str(raw_level))}")

            short_msg = msg.get("message") or msg.get("short_message") or ""
            if short_msg:
                lines.append(f"Сообщение: {short_msg}")

            for key, label in [
                ("_exception_class",   "Исключение"),
                ("_exception_message", "Текст исклч"),
                ("_component",         "Компонент"),
                ("_event",             "Событие"),
                ("_order_id",          "Заказ"),
            ]:
                val = msg.get(key) or msg.get(key.lstrip("_"), "")
                if val:
                    lines.append(f"{label}: {val}")

            stack = msg.get("_stack_trace") or msg.get("stack_trace", "")
            full_msg = msg.get("full_message", "")
            trace_text = stack or (full_msg if full_msg != short_msg else "")
            if trace_text:
                root = GraylogConnector._extract_root_cause(trace_text)
                if root:
                    lines.append(f"Корневая причина: {root}")
                lines.append(f"Стектрейс:\n{trace_text[:3000]}")

            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _extract_root_cause(stack: str) -> str:
        """
        Извлекает первый фрейм кода приложения из стектрейса.
        Строки /vendor/ и /framework/ — это фреймворк, пропускаем.
        Первая строка с /app/ — корневая точка ошибки в коде приложения.
        Формат стектрейса: #N /path/to/File.php(line): Class->method(args)
        """
        import re
        for line in stack.splitlines():
            line = line.strip()
            if not line.startswith("#"):
                continue
            # Поддержка путей с /app/ или \app\ (Windows-стиль в трейсе)
            if "/app/" not in line and "\\app\\" not in line:
                continue
            if "/vendor/" in line or "/framework/" in line or "\\vendor\\" in line or "\\framework\\" in line:
                continue
            # Извлекаем путь и метод: #2 /var/www/html/app/.../File.php(57): Class->method()
            match = re.match(r"#\d+\s+(.+\.php\(\d+\)):\s+(.+)", line)
            if match:
                file_loc = match.group(1)  # /var/www/html/app/Repo.php(124)
                method = match.group(2)    # Repo->find()
                # Сокращаем путь: убираем /var/www/html
                short_path = re.sub(r"^.*/app/", "app/", file_loc)
                return f"{short_path} → {method}"
            return line  # Fallback: строка как есть
        return ""

    @staticmethod
    def _to_schema(t) -> dict:
        return {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema or {},
        }
