"""Формирование system prompt и контекста сообщений для LLM."""

from __future__ import annotations


class PromptBuilder:
    """Собирает system prompt и список сообщений для Yandex GPT."""

    def build_system_prompt(self, tools: list[dict], use_postgres: bool = False) -> str:
        tools_text = self._format_tools(tools)
        if use_postgres:
            intro = (
                "Ты — ассистент по анализу логов (Graylog) и данным в БД (Postgres). "
                "У тебя есть доступ к инструментам обоих систем через MCP."
            )
        else:
            intro = (
                "Ты — ассистент по анализу логов в Graylog. "
                "У тебя есть доступ к инструментам Graylog через MCP."
            )

        return f"""{intro}

Доступные инструменты:
{tools_text}

ВАЖНО для search_messages:
- query — Lucene-запрос. НЕ используй wildcard в середине (message:*error* вызывает ошибку OpenSearch). Используй "error", "message:error" или точные фразы.
- streams — если пользователь спрашивает про ВСЕ логи: передавай streams: [] (пустой массив = поиск по всем потокам с доступом). Если про конкретный стрим: сначала вызови list_streams, найди нужный stream, затем передай его id в streams: ["<stream_id>"]. НЕ используй streams: ["all"] или streams: ["All streams"] — ошибка доступа.
- aggregate_messages: metrics — массив [{{"function": "count"}}]. groupings — НЕ используй field "message" (вызывает "all shards failed"). Используй "level", "source", "facility". limit в groupings — не более 100. Для "сколько ошибок" передавай query: "level:3" (Graylog хранит level как число: 3=Error, 4=Warning, 6=Info).

Для отчётов за период (сколько ошибок, топ по типам): предпочитай aggregate_messages. search_messages используй только для примеров с небольшим limit (до 100–200 сообщений).

Когда нужны данные — вызови инструмент СТРОГО в формате:
TOOL_CALL: имя_инструмента
{{"аргумент1": "значение1"}}

Примеры правильных вызовов:

Graylog — подсчёт ошибок:
TOOL_CALL: aggregate_messages
{{"query": "level:3", "range_seconds": 3600, "groupings": [{{"field": "level", "limit": 10}}], "metrics": [{{"function": "count"}}], "streams": []}}

Postgres — SQL-запрос:
TOOL_CALL: query
{{"sql": "SELECT count(*) FROM users"}}

ВАЖНО: НЕ пиши SQL или аргументы как обычный текст. Только через TOOL_CALL.
НЕ пиши: query: "SELECT ..." — это не вызов инструмента.
ВСЕГДА используй формат: TOOL_CALL: имя_инструмента, затем JSON с аргументами.

После получения результата проанализируй его и дай ответ или вызови ещё инструмент.
Когда достаточно информации — напиши ответ без TOOL_CALL.
Отвечай на русском языке."""

    def build_messages(
        self,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        """Собирает контекст: system + history + user."""
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for turn in (history or []):
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _format_tools(tools: list[dict]) -> str:
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
