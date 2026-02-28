"""Парсер вызовов инструментов из ответа LLM (ReAct-формат)."""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("logs_ai.tool_parser")

# Основной формат: TOOL_CALL: tool_name\n{...}
_TOOL_CALL_PATTERN = re.compile(
    r"\[?TOOL_CALL:\s*(\w+)\s*\]?\s*\n?\s*\{",
    re.DOTALL,
)


class ToolCallParser:
    """
    Парсит строку ответа LLM и извлекает имя инструмента и аргументы.

    Поддерживает два формата:
    1. ``TOOL_CALL: tool_name\\n{...}``  — основной формат ReAct
    2. ``tool_name:\\n{...}``            — fallback (Yandex иногда пропускает префикс)
    """

    def __init__(self, tool_names: list[str] | None = None) -> None:
        self._tool_names = tool_names or []
        self._alt_pattern: re.Pattern | None = self._build_alt_pattern(self._tool_names)

    def update_tool_names(self, tool_names: list[str]) -> None:
        self._tool_names = tool_names
        self._alt_pattern = self._build_alt_pattern(tool_names)

    def parse(self, text: str) -> tuple[str | None, dict | None]:
        """Возвращает (tool_name, args) или (None, None) если вызова нет."""
        match = _TOOL_CALL_PATTERN.search(text)
        if not match and self._alt_pattern:
            match = self._alt_pattern.search(text)
        if not match:
            return None, None

        name = match.group(1).strip()
        brace_start = match.end() - 1
        raw_args = _extract_balanced_json(text, brace_start)
        if not raw_args:
            log.warning("[PARSER] Не найден полный JSON для инструмента %s", name)
            return name, None

        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            log.warning("[PARSER] Не удалось распарсить JSON для %s: %s. raw=%s", name, e, raw_args[:100])
            args = {}
        return name, args

    # ── приватные методы ───────────────────────────────────────────────────

    @staticmethod
    def _build_alt_pattern(tool_names: list[str]) -> re.Pattern | None:
        if not tool_names:
            return None
        names_re = "|".join(
            re.escape(n) for n in sorted(tool_names, key=len, reverse=True)
        )
        return re.compile(
            r"^[`\s\n]*(" + names_re + r")[\s:]*\n\s*\{",
            re.MULTILINE | re.DOTALL,
        )


def _extract_balanced_json(text: str, start: int) -> str | None:
    """Извлекает JSON-объект с позиции start, учитывая вложенные скобки и строки."""
    if start >= len(text) or text[start] != "{":
        return None
    depth, i = 0, start
    in_string, escape, quote = False, False, None
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            i += 1
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
            elif c in ('"', "'"):
                in_string, quote = True, c
        elif c == quote:
            in_string = False
        i += 1
    return None
