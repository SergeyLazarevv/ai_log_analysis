"""Yandex GPT API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("logs_ai.yandex")

_YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "..." + key[-4:]


class YandexClient:
    """Клиент Yandex GPT Foundation Models API."""

    def __init__(self, api_key: str, catalog_id: str, model: str = "yandexgpt-lite") -> None:
        if not api_key or not catalog_id:
            raise ValueError("YANDEX_API_KEY and YANDEX_CATALOG_ID must be set")
        self._api_key = api_key
        self._catalog_id = catalog_id
        self._model = model
        self._model_uri = f"gpt://{catalog_id}/{model}"

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Отправляет сообщения в Yandex GPT, возвращает текст ответа."""
        payload: dict[str, Any] = {
            "modelUri": self._model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.6,
                "maxTokens": "4096",
            },
            "messages": [{"role": m["role"], "text": m["content"]} for m in messages],
        }

        roles = [m["role"] for m in messages]
        total_chars = sum(len(m.get("content", "")) for m in messages)
        log.info("[YANDEX] Запрос: %d сообщений (roles=%s), ~%d символов, model=%s",
                 len(messages), roles, total_chars, self._model)
        log.info("[YANDEX] URL=%s, catalog=%s, api_key=%s",
                 _YANDEX_GPT_URL, self._catalog_id, _mask_key(self._api_key))

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    _YANDEX_GPT_URL,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Api-Key {self._api_key}",
                    },
                    json=payload,
                    timeout=60.0,
                )
            log.info("[YANDEX] Ответ: status=%d, content-type=%s",
                     response.status_code, response.headers.get("content-type", ""))

            if response.status_code != 200:
                log.error("[YANDEX] Ошибка HTTP %d: %s", response.status_code, response.text[:500])
            response.raise_for_status()
            data = response.json()

        except httpx.TimeoutException as e:
            log.exception("[YANDEX] Таймаут запроса к Yandex API: %s", e)
            raise
        except httpx.HTTPStatusError as e:
            resp_text = e.response.text[:300] if hasattr(e, "response") and e.response else ""
            log.error("[YANDEX] HTTP ошибка %s: %s",
                      e.response.status_code if hasattr(e, "response") else "?", resp_text)
            raise
        except Exception as e:
            log.exception("[YANDEX] Исключение при запросе: %s", e)
            raise

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> str:
        result_obj = data.get("result") or {}
        alternatives = result_obj.get("alternatives") or []
        if not alternatives:
            log.warning("[YANDEX] Пустой ответ от API: result.alternatives пустой. result keys=%s",
                        list(result_obj.keys()) if isinstance(result_obj, dict) else "?")
            return ""
        first = alternatives[0] if isinstance(alternatives[0], dict) else {}
        message = first.get("message")
        if isinstance(message, str):
            text = message.strip()
        elif isinstance(message, dict):
            text = (message.get("text") or message.get("content") or "").strip()
        else:
            text = ""
        if not text:
            log.warning("[YANDEX] Пустой ответ от API: message.text пустой. first keys=%s",
                        list(first.keys()) if isinstance(first, dict) else "?")
            return ""
        log.info("[YANDEX] Успех: ответ %d символов", len(text))
        return text


async def call_yandex(
    messages: list[dict[str, str]],
    api_key: str | None = None,
    catalog_id: str | None = None,
    model: str = "yandexgpt-lite",
) -> str:
    """Обратная совместимость: функциональный интерфейс поверх YandexClient."""
    import os
    api_key = api_key or os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH")
    catalog_id = catalog_id or os.getenv("YANDEX_CATALOG_ID")
    if not api_key or not catalog_id:
        raise ValueError("YANDEX_API_KEY and YANDEX_CATALOG_ID must be set")
    return await YandexClient(api_key, catalog_id, model).complete(messages)
