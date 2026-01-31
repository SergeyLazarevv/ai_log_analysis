"""Agent: Yandex GPT + Graylog MCP with ReAct-style tool calling."""

# Graylog 7.x поддерживает только 2025-06-18; MCP SDK по умолчанию шлёт 2025-11-25
import mcp.types as _mcp_types
_mcp_types.LATEST_PROTOCOL_VERSION = "2025-06-18"

import json
import logging
import re
from typing import Any

import httpx

log = logging.getLogger("logs_ai.agent")
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from yandex_client import call_yandex

# Graylog возвращает effective_timerange.to как строку ISO, а MCP schema ожидает object.
# Патчим валидацию, чтобы не падать на этой несовместимости.
_orig_validate = ClientSession._validate_tool_result


async def _patched_validate_tool_result(self, name: str, result) -> None:
    try:
        await _orig_validate(self, name, result)
    except RuntimeError as e:
        if "Invalid structured content" in str(e) or "is not of type" in str(e):
            log.warning("[AGENT] Graylog schema mismatch для %s (игнорируем): %s", name, str(e)[:150])
        else:
            raise


ClientSession._validate_tool_result = _patched_validate_tool_result

# ReAct format: model outputs TOOL_CALL: tool_name\n{"arg": "value"} when it wants to call a tool
TOOL_CALL_PATTERN = re.compile(
    r"TOOL_CALL:\s*(\w+)\s*\n?\s*(\{.*?\})",
    re.DOTALL,
)

MAX_ITERATIONS = 10


def format_tools_for_prompt(tools: list[dict]) -> str:
    """Format MCP tools as text for the system prompt."""
    lines = []
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        schema = t.get("inputSchema", {})
        props = schema.get("properties", {})
        req = schema.get("required", [])
        args = ", ".join(
            f"{k}: {v.get('type', 'string')}" + (" (required)" if k in req else "")
            for k, v in props.items()
        )
        lines.append(f"- {name}: {desc}\n  Args: {args}")
    return "\n".join(lines) if lines else "Нет доступных инструментов"


def parse_tool_call(text: str) -> tuple[str | None, dict | None]:
    """Extract tool name and arguments from model output."""
    match = TOOL_CALL_PATTERN.search(text)
    if not match:
        return None, None
    name = match.group(1).strip()
    raw_args = match.group(2)
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        log.warning("[AGENT] parse_tool_call: не удалось распарсить JSON для %s: %s. raw=%s", name, e, raw_args[:100])
        args = {}
    return name, args


async def run_agent(
    user_message: str,
    graylog_url: str,
    graylog_auth_header: str,
) -> str:
    """
    Run the agent loop: user question -> Yandex (with tools) -> parse tool call ->
    execute via Graylog MCP -> send result back -> repeat until final answer.
    """
    # Connect to Graylog MCP (pass custom httpx client with auth)
    headers = {"Authorization": graylog_auth_header} if graylog_auth_header else {}
    log.info("[AGENT] ========== СТАРТ АГЕНТА ==========")
    log.info("[AGENT] user_message=%d символов, graylog_url=%s, auth=%s",
             len(user_message), graylog_url, "задан" if graylog_auth_header else "НЕТ")

    try:
        log.info("[AGENT] [1/6] Подключение к Graylog MCP: %s", graylog_url)
        async with httpx.AsyncClient(headers=headers, timeout=60.0) as http_client:
            async with streamable_http_client(
                graylog_url,
                http_client=http_client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    log.info("[AGENT] [2/6] Инициализация MCP сессии...")
                    await session.initialize()
                    log.info("[AGENT] [2/6] MCP сессия инициализирована успешно")

                    log.info("[AGENT] [3/6] Запрос списка инструментов Graylog...")
                    tools_result = await session.list_tools()
                    tools = [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema or {},
                        }
                        for t in tools_result.tools
                    ]
                    tool_names = ", ".join(t["name"] for t in tools[:5]) + ("..." if len(tools) > 5 else "")
                    log.info("[AGENT] [3/6] Получено инструментов Graylog: %d (%s)", len(tools), tool_names)

                    tools_text = format_tools_for_prompt(tools)
                    log.info("[AGENT] System prompt: %d символов, инструменты: %s", len(tools_text), tool_names)

                    system_prompt = f"""Ты — ассистент по анализу логов в Graylog. У тебя есть доступ к инструментам Graylog через MCP.

Доступные инструменты:
{tools_text}

ВАЖНО для search_messages:
- query — Lucene-запрос. Избегай ведущих wildcards (* в начале). Используй "error", "message:error", "*error", но НЕ "*error*".
- streams — если пользователь спрашивает про ВСЕ логи: передавай streams: [] (пустой массив = поиск по всем потокам с доступом). Если пользователь спрашивает про конкретное окружение или стрим (production, staging, dev, или по имени стрима): сначала вызови list_streams, найди нужный stream по имени/описанию, затем передай его id в streams: ["<stream_id>"]. НЕ используй streams: ["all"] или streams: ["All streams"] — это вызывает ошибку доступа.

Когда тебе нужны данные из Graylog (логи, стримы, статус системы и т.д.), вызови инструмент в формате:
TOOL_CALL: имя_инструмента
{{"аргумент1": "значение1", "аргумент2": "значение2"}}

После получения результата проанализируй его и либо дай ответ пользователю, либо вызови ещё один инструмент.
Когда у тебя достаточно информации для полного ответа — напиши его без TOOL_CALL.
Отвечай на русском языке."""

                    messages: list[dict[str, str]] = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ]
                    log.info("[AGENT] Начальный контекст: system + user, всего %d сообщений", len(messages))

                    for iteration in range(MAX_ITERATIONS):
                        log.info("[AGENT] [4/6] Итерация %d/%d: отправка в Yandex GPT (%d сообщений в контексте)",
                                 iteration + 1, MAX_ITERATIONS, len(messages))
                        response_text = await call_yandex(messages)
                        preview = (response_text[:120] + "...") if len(response_text) > 120 else response_text
                        log.info("[AGENT] [5/6] Yandex ответил: %d символов. Начало: %s", len(response_text), preview)

                        tool_name, tool_args = parse_tool_call(response_text)
                        if tool_name:
                            log.info("[AGENT] [6/6] Обнаружен TOOL_CALL: %s, args=%s", tool_name, tool_args)
                        else:
                            log.info("[AGENT] [6/6] TOOL_CALL не найден в ответе (финальный ответ)")

                        if tool_name and tool_args is not None:
                            # Execute tool via MCP
                            try:
                                log.info("[AGENT] Вызов MCP call_tool(%s, %s)", tool_name, tool_args)
                                result = await session.call_tool(tool_name, tool_args)
                                result_text = ""
                                for c in result.content:
                                    if hasattr(c, "text"):
                                        result_text += c.text
                                if result.isError:
                                    result_text = f"Ошибка: {result_text}"
                                    log.warning("[AGENT] MCP инструмент %s вернул ОШИБКУ: %s", tool_name, result_text[:300])
                                else:
                                    log.info("[AGENT] MCP инструмент %s выполнен успешно, результат: %d символов", tool_name, len(result_text))
                                    log.debug("[AGENT] Результат (первые 200 символов): %s", result_text[:200])
                            except Exception as e:
                                result_text = f"Ошибка вызова инструмента: {e}"
                                log.exception("[AGENT] ИСКЛЮЧЕНИЕ при вызове MCP инструмента %s: %s", tool_name, e)

                            # Add assistant message (with tool call) and tool result to conversation
                            messages.append({"role": "assistant", "content": response_text})
                            messages.append(
                                {
                                    "role": "user",
                                    "content": f"[Результат вызова {tool_name}]:\n{result_text}",
                                }
                            )
                        else:
                            # No tool call — final answer
                            log.info("[AGENT] ========== ФИНАЛЬНЫЙ ОТВЕТ (итерация %d) ==========", iteration + 1)
                            return response_text

                    log.warning("[AGENT] Достигнут лимит %d итераций, возврат fallback-сообщения", MAX_ITERATIONS)
                    return "Достигнут лимит итераций. Попробуйте переформулировать вопрос."

    except Exception as e:
        # MCP недоступен — отвечаем только через Yandex (без Graylog)
        log.warning("[AGENT] MCP недоступен! type=%s, msg=%s", type(e).__name__, str(e))
        log.info("[AGENT] Fallback: ответ только через Yandex (без инструментов Graylog)")
        messages = [
            {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском."},
            {"role": "user", "content": user_message},
        ]
        try:
            log.info("[AGENT] Fallback: отправка в Yandex (2 сообщения: system + user)")
            result = await call_yandex(messages)
            log.info("[AGENT] Fallback Yandex успешен: %d символов", len(result))
            return result
        except Exception as yandex_err:
            log.exception("[AGENT] Fallback Yandex ТОЖЕ УПАЛ: %s", yandex_err)
            raise RuntimeError(
                f"Graylog MCP: {e}. Yandex: {yandex_err}. "
                "Проверь: Graylog запущен? MCP включён? GRAYLOG_MCP_URL и GRAYLOG_MCP_AUTH в LogsAi/.env?"
            ) from e
