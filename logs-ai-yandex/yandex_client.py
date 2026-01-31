"""Yandex GPT API client."""

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("logs_ai.yandex")

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def _mask_key(key: str) -> str:
    """Маскирует API ключ для логов."""
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "..." + key[-4:]


async def call_yandex(
    messages: list[dict[str, str]],
    api_key: str | None = None,
    catalog_id: str | None = None,
    model: str = "yandexgpt-lite",
) -> str:
    """Send messages to Yandex GPT and return the response text."""
    api_key = api_key or os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH")
    catalog_id = catalog_id or os.getenv("YANDEX_CATALOG_ID")

    if not api_key or not catalog_id:
        log.error("[YANDEX] Ошибка конфигурации: api_key=%s, catalog_id=%s",
                  "задан" if api_key else "НЕТ", "задан" if catalog_id else "НЕТ")
        raise ValueError("YANDEX_API_KEY and YANDEX_CATALOG_ID must be set")

    model_uri = f"gpt://{catalog_id}/{model}"
    payload: dict[str, Any] = {
        "modelUri": model_uri,
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
             len(messages), roles, total_chars, model)
    log.info("[YANDEX] URL=%s, catalog=%s, api_key=%s", YANDEX_GPT_URL, catalog_id, _mask_key(api_key))

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                YANDEX_GPT_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Api-Key {api_key}",
                },
                json=payload,
                timeout=60.0,
            )
        log.info("[YANDEX] Ответ: status=%d, content-type=%s", response.status_code, response.headers.get("content-type", ""))

        if response.status_code != 200:
            log.error("[YANDEX] Ошибка HTTP %d: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()

    except httpx.TimeoutException as e:
        log.exception("[YANDEX] Таймаут запроса к Yandex API: %s", e)
        raise
    except httpx.HTTPStatusError as e:
        resp_text = e.response.text[:300] if hasattr(e, "response") and e.response else ""
        log.error("[YANDEX] HTTP ошибка %s: %s", e.response.status_code if hasattr(e, "response") else "?", resp_text)
        raise
    except Exception as e:
        log.exception("[YANDEX] Исключение при запросе: %s", e)
        raise

    text = (
        data.get("result", {})
        .get("alternatives", [{}])[0]
        .get("message", {})
        .get("text", "")
    )
    result = text.strip()
    if not result:
        log.warning("[YANDEX] Пустой ответ от API. data keys=%s", list(data.keys()) if isinstance(data, dict) else "?")
    else:
        log.info("[YANDEX] Успех: ответ %d символов", len(result))
    return result
