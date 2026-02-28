"""Нормализация аргументов инструментов перед передачей в Graylog MCP."""

from __future__ import annotations

import logging
import re

log = logging.getLogger("logs_ai.normalizer")

MAX_SEARCH_LIMIT = 200
MAX_GROUPING_LIMIT = 100


class ToolArgsNormalizer:
    """
    Исправляет типичные ошибки в аргументах, которые генерирует LLM:
    - aggregate_messages: группировка по «message» → «level», limit groupings ≤ 100,
      query level:ERROR → level:3 при вопросе про ошибки, metrics как массив.
    - search_messages: убирает wildcard в Lucene-запросе, ограничивает limit.
    """

    def normalize(self, tool_name: str, tool_args: dict, user_message: str = "") -> dict:
        if tool_name == "aggregate_messages":
            tool_args = self._fix_aggregate(tool_args, user_message)
        elif tool_name == "search_messages":
            tool_args = self._fix_search(tool_args)
        return tool_args

    # ── aggregate_messages ─────────────────────────────────────────────────

    def _fix_aggregate(self, args: dict, user_message: str) -> dict:
        args = self._fix_groupings(args)
        args = self._fix_error_query(args, user_message)
        args = self._fix_metrics(args)
        return args

    def _fix_groupings(self, args: dict) -> dict:
        groupings = args.get("groupings")
        if not groupings:
            return args
        fixed = []
        for g in groupings:
            if not isinstance(g, dict):
                fixed.append({"field": "level", "limit": MAX_GROUPING_LIMIT})
                continue
            if g.get("field") == "message":
                fixed.append({"field": "level", "limit": min(g.get("limit", MAX_GROUPING_LIMIT), MAX_GROUPING_LIMIT)})
                log.info("[NORM] aggregate_messages: groupings field 'message' → 'level'")
            else:
                lim = g.get("limit", MAX_GROUPING_LIMIT)
                if lim > MAX_GROUPING_LIMIT:
                    g = {**g, "limit": MAX_GROUPING_LIMIT}
                    log.info("[NORM] aggregate_messages: groupings limit ограничен до %d", MAX_GROUPING_LIMIT)
                fixed.append(g)
        return {**args, "groupings": fixed}

    def _fix_error_query(self, args: dict, user_message: str) -> dict:
        is_error_question = "ошиб" in user_message.lower() or "error" in user_message.lower()
        if not is_error_question:
            return args
        q = args.get("query", "")
        if not q or "level:error" in q.lower():
            log.info("[NORM] aggregate_messages: query → 'level:3' (ошибки, syslog=3)")
            return {**args, "query": "level:3"}
        return args

    def _fix_metrics(self, args: dict) -> dict:
        metrics = args.get("metrics")
        if isinstance(metrics, dict):
            log.info("[NORM] aggregate_messages: metrics dict → [metrics]")
            return {**args, "metrics": [metrics]}
        return args

    # ── search_messages ────────────────────────────────────────────────────

    def _fix_search(self, args: dict) -> dict:
        if "query" in args:
            orig = args["query"]
            fixed = _normalize_lucene_query(orig)
            if fixed != orig:
                log.info("[NORM] search_messages: query %r → %r", orig, fixed)
                args = {**args, "query": fixed}
        lim = args.get("limit")
        if isinstance(lim, (int, float)) and lim > MAX_SEARCH_LIMIT:
            log.info("[NORM] search_messages: limit %d → %d", lim, MAX_SEARCH_LIMIT)
            args = {**args, "limit": MAX_SEARCH_LIMIT}
        return args


def _normalize_lucene_query(query: str) -> str:
    """Убирает wildcard-паттерны, вызывающие 'all shards failed' в OpenSearch."""
    if not query or not isinstance(query, str):
        return query or ""
    q = query.strip()
    q = re.sub(r"(\w+):\s*\*+([^*]+)\*+", r"\1:\2", q)
    q = re.sub(r"\*+([^*]+)\*+", r"\1", q)
    return q.strip() or "*"
