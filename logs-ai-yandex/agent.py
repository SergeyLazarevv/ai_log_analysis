"""LogsAgent — оркестратор ReAct-цикла: Yandex GPT + Graylog/Postgres MCP."""

from __future__ import annotations

import logging

from config import AppConfig
from mcp_connector import MCPConnector
from prompt_builder import PromptBuilder
from tool_normalizer import ToolArgsNormalizer
from tool_parser import ToolCallParser
from yandex_client import YandexClient

log = logging.getLogger("logs_ai.agent")

MAX_ITERATIONS = 20
MAX_TOOL_RESULT_CHARS = 12_000


class LogsAgent:
    """
    Запускает ReAct-цикл:
      1. Подключается к MCP (Graylog + опционально Postgres).
      2. Строит system prompt с описанием инструментов.
      3. В цикле: отправляет сообщения в LLM → парсит TOOL_CALL →
         нормализует аргументы → вызывает инструмент → добавляет результат в контекст.
      4. Возвращает финальный текстовый ответ.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._llm = self._build_llm(config)
        self._prompt_builder = PromptBuilder()
        self._normalizer = ToolArgsNormalizer()

    async def run(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        log.info("[AGENT] ========== СТАРТ АГЕНТА ==========")
        log.info("[AGENT] message=%d симв., history=%d, postgres=%s",
                 len(user_message), len(history or []),
                 "вкл" if self._config.postgres_dsn else "выкл")

        try:
            async with MCPConnector(
                self._config.graylog_url,
                self._config.graylog_auth,
                self._config.postgres_dsn,
            ) as mcp:
                return await self._react_loop(user_message, history or [], mcp)
        except Exception as e:
            return self._build_error_response(e)

    # ── внутренние методы ──────────────────────────────────────────────────

    async def _react_loop(
        self,
        user_message: str,
        history: list[dict[str, str]],
        mcp: MCPConnector,
    ) -> str:
        use_postgres = any("query" in t["name"] or "table" in t["name"].lower()
                           for t in mcp.tools if "postgres" not in t["name"].lower()) and self._config.postgres_dsn

        system_prompt = self._prompt_builder.build_system_prompt(mcp.tools, bool(self._config.postgres_dsn))
        messages = self._prompt_builder.build_messages(system_prompt, user_message, history)
        parser = ToolCallParser(mcp.tool_names)

        log.info("[AGENT] Инструментов: %d, контекст: %d сообщений", len(mcp.tools), len(messages))

        for iteration in range(MAX_ITERATIONS):
            log.info("[AGENT] Итерация %d/%d (%d сообщений)", iteration + 1, MAX_ITERATIONS, len(messages))

            response_text = await self._llm.complete(messages)
            preview = (response_text[:120] + "...") if len(response_text) > 120 else response_text
            log.info("[AGENT] LLM ответил: %d симв. Начало: %s", len(response_text), preview)

            tool_name, tool_args = parser.parse(response_text)

            if tool_name and tool_args is not None:
                log.info("[AGENT] TOOL_CALL: %s args=%s", tool_name, tool_args)
                tool_args = self._normalizer.normalize(tool_name, tool_args, user_message)
                result_text = await mcp.call_tool(tool_name, tool_args)
                result_text = self._truncate_result(tool_name, result_text)
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"[Результат вызова {tool_name}]:\n{result_text}"})
            else:
                log.info("[AGENT] Финальный ответ (итерация %d)", iteration + 1)
                return response_text.strip() or "Модель не вернула текст. Попробуйте переформулировать запрос."

        log.warning("[AGENT] Достигнут лимит итераций (%d)", MAX_ITERATIONS)
        return "Достигнут лимит итераций. Попробуйте переформулировать вопрос."

    def _truncate_result(self, tool_name: str, result_text: str) -> str:
        if len(result_text) > MAX_TOOL_RESULT_CHARS:
            log.info("[AGENT] Результат %s обрезан до %d символов", tool_name, MAX_TOOL_RESULT_CHARS)
            return (
                result_text[:MAX_TOOL_RESULT_CHARS]
                + f"\n\n... (обрезано: показаны первые {MAX_TOOL_RESULT_CHARS} из {len(result_text)} символов)"
            )
        return result_text

    def _build_error_response(self, exc: BaseException) -> str:
        real = _unwrap_exception(exc)
        err_msg = str(real).strip() or type(real).__name__
        hint = _error_hint(real)
        log.warning("[AGENT] MCP недоступен: %s — %s", type(real).__name__, err_msg[:200])
        if hint:
            log.info("[AGENT] Возможная причина: %s", hint)
        return (
            "⚠️ **Инструменты Graylog и/или БД недоступны.**\n\n"
            f"**Ошибка:** {err_msg[:400]}\n\n"
            + (f"**Вероятная причина:** {hint}\n\n" if hint else "")
            + "**Что проверить:**\n"
            "• **Graylog:** запущен ли контейнер? Включён ли MCP: System → Configurations → MCP? "
            "Заданы GRAYLOG_MCP_URL и GRAYLOG_MCP_AUTH?\n"
            "• **Postgres MCP:** задан POSTGRES_MCP_DSN? Установлен Node.js (`npx --version`)? "
            "Postgres доступен по DSN?\n"
            "• Откройте http://127.0.0.1:3020/api/status для диагностики."
        )

    @staticmethod
    def _build_llm(config: AppConfig) -> YandexClient:
        if not config.yandex_api_key or not config.yandex_catalog_id:
            raise ValueError("YANDEX_API_KEY и YANDEX_CATALOG_ID не заданы в .env")
        return YandexClient(config.yandex_api_key, config.yandex_catalog_id, config.yandex_model)


# ── вспомогательные функции ────────────────────────────────────────────────

def _unwrap_exception(exc: BaseException) -> BaseException:
    out = exc
    while True:
        if hasattr(out, "exceptions") and getattr(out, "exceptions", None):
            out = out.exceptions[0]
            continue
        if getattr(out, "__cause__", None):
            out = out.__cause__
            continue
        break
    return out


def _error_hint(exc: BaseException) -> str:
    msg = (str(exc) or "").lower()
    if "connection refused" in msg:
        return "Сервис не запущен или не слушает порт. Graylog: docker compose up, порт 9000."
    if "connection reset" in msg or "reset" in msg:
        return "Соединение разорвано. Graylog мог перезапуститься или MCP отключён."
    if "invalid credentials" in msg or "401" in msg or "unauthorized" in msg:
        return "Неверный GRAYLOG_MCP_AUTH. Пересоберите Basic: echo -n 'TOKEN:token' | base64 -w0."
    if type(exc).__name__ == "FileNotFoundError" or "npx" in msg or "enoent" in msg:
        return "Не найден npx (Node.js). Установите Node.js для Postgres MCP."
    if "timeout" in msg or "timed out" in msg:
        return "Таймаут. Graylog или Postgres долго не отвечают."
    if "protocol" in msg or "version" in msg:
        return "Несовпадение версии MCP. Убедитесь, что Graylog 7.x."
    return ""


async def run_agent(
    user_message: str,
    graylog_url: str,
    graylog_auth_header: str,
    conversation_history: list[dict[str, str]] | None = None,
    postgres_dsn: str | None = None,
) -> str:
    """Обратная совместимость с вызовом из app.py."""
    import os
    config = AppConfig(
        graylog_url=graylog_url,
        graylog_auth=graylog_auth_header,
        postgres_dsn=postgres_dsn,
        yandex_api_key=os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH"),
        yandex_catalog_id=os.getenv("YANDEX_CATALOG_ID"),
        yandex_model=os.getenv("YANDEX_MODEL", "yandexgpt-lite"),
    )
    return await LogsAgent(config).run(user_message, conversation_history)
