"""Logs AI + Yandex: Web UI for chat with Graylog MCP via Yandex GPT."""

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

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import LogsAgent
from config import AppConfig

# Загрузка .env
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root.parent / "yandexGptCli" / "src" / ".env")

# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="Logs AI + Yandex", description="Чат с Graylog через Yandex GPT")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


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

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(
            content=html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                     "Pragma": "no-cache", "Expires": "0"},
        )
    return HTMLResponse("<h1>Logs AI</h1><p>Создайте static/index.html</p>")


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
                    "clientInfo": {"name": "logs-ai-check", "version": "1.0"},
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
