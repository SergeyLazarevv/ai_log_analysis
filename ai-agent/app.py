"""AI Agent: Web UI for chat with Graylog and PostgreSQL via Yandex GPT."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("logs_ai")

import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import LogsAgent
from config import AppConfig

# Загрузка .env
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root.parent / "yandexGptCli" / "src" / ".env")

# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="AI Agent", description="Чат с Graylog и PostgreSQL через Yandex GPT")


@app.on_event("startup")
async def startup_event():
    config = AppConfig.from_env()
    log.info("[STARTUP] %s", config.log_summary())


# ── Pydantic-модели ─────────────────────────────────────────────────────────

class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation: list[ChatTurn] | None = None


class ChatResponse(BaseModel):
    response: str


# ── Роуты ───────────────────────────────────────────────────────────────────


@app.post("/api/chat", response_model=ChatResponse)
async def chat(raw_request: Request):
    body = await raw_request.json()
    request = ChatRequest.model_validate(body)
    msg = request.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    log.info("[CHAT] Запрос: %d симв.: %s", len(msg), msg[:120])
    config = AppConfig.from_env()
    agent = LogsAgent(config)

    try:
        response = await agent.run(msg, history=[])
        log.info("[CHAT] Ответ готов: %d симв.", len(response))
        return ChatResponse(response=response)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("[CHAT] Исключение при обработке запроса")
        cause = e
        while getattr(cause, "__cause__", None):
            cause = cause.__cause__
        raise HTTPException(status_code=500, detail=f"Ошибка: {cause}")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ── OpenAI-совместимый API (для Open WebUI) ──────────────────────────────────

@app.get("/v1/models")
async def openai_list_models():
    """Open WebUI запрашивает список моделей при старте."""
    return JSONResponse({
        "object": "list",
        "data": [{
            "id": "logs-ai",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ai-agent",
        }],
    })


@app.post("/v1/chat/completions")
async def openai_chat_completions(raw_request: Request):
    """
    OpenAI-совместимый эндпоинт для Open WebUI.
    Open WebUI шлёт сообщения в формате OpenAI, мы прогоняем через LogsAgent
    и возвращаем ответ в формате OpenAI.
    """
    body = await raw_request.json()
    messages: list[dict] = body.get("messages", [])

    # Извлекаем последнее сообщение пользователя
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="Нет сообщений пользователя")
    msg = user_messages[-1].get("content", "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    log.info("[OPENAI] Запрос от Open WebUI: %d симв.: %s", len(msg), msg[:120])
    config = AppConfig.from_env()
    agent = LogsAgent(config)

    try:
        response_text = await agent.run(msg, history=[])
        log.info("[OPENAI] Ответ готов: %d симв.", len(response_text))
    except Exception as e:
        log.exception("[OPENAI] Исключение при обработке запроса")
        cause = e
        while getattr(cause, "__cause__", None):
            cause = cause.__cause__
        raise HTTPException(status_code=500, detail=f"Ошибка: {cause}")

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "logs-ai"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response_text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(msg) // 4,
            "completion_tokens": len(response_text) // 4,
            "total_tokens": (len(msg) + len(response_text)) // 4,
        },
    })


@app.get("/api/status")
async def status():
    """Диагностика: проверяет Graylog MCP, Yandex и наличие npx."""
    config = AppConfig.from_env()
    result: dict[str, str | None] = {
        "yandex": "ok" if (config.yandex_api_key and config.yandex_catalog_id)
                  else "нет YANDEX_API_KEY или YANDEX_CATALOG_ID",
        "graylog_mcp": None,
        "postgres_mcp_dsn": "задан" if config.postgres_dsn else "не задан (добавьте POSTGRES_MCP_DSN в .env)",
        "npx_available": None,
    }

    result["graylog_mcp"] = await _check_graylog(config)
    result["npx_available"] = _check_npx()

    log.info("[STATUS] %s", result)
    return result


# ── Вспомогательные функции статус-чека ────────────────────────────────────

async def _check_graylog(config: AppConfig) -> str:
    if not config.graylog_auth:
        return "нет GRAYLOG_MCP_AUTH в .env"
    try:
        r = httpx.post(
            config.graylog_url,
            headers={"Authorization": config.graylog_auth, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-agent-check", "version": "1.0"},
                },
            },
            timeout=10,
        )
        if r.status_code == 200:
            return "ok"
        data = r.json() if "application/json" in (r.headers.get("content-type") or "") else {}
        return f"ошибка {r.status_code}: {data.get('message', r.text[:200])}"
    except Exception as e:
        return f"ошибка: {type(e).__name__}: {e}"


def _check_npx() -> str:
    try:
        path = shutil.which("npx")
        return "ok" if path else "не найден (нужен Node.js для Postgres MCP)"
    except Exception as e:
        return f"проверка не удалась: {e}"
