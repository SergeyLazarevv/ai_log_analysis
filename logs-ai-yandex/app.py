"""Logs AI + Yandex: Web UI for chat with Graylog MCP via Yandex GPT."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("logs_ai")
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import run_agent

# Загрузка .env: LogsAi/.env (все токены и URL уже там)
_root = Path(__file__).parent.parent  # LogsAi/
load_dotenv(_root / ".env")
# yandexGptCli — если YANDEX_* не заданы в LogsAi
load_dotenv(_root.parent / "yandexGptCli" / "src" / ".env")

# Логируем конфигурацию при старте (без секретов)
def _log_startup_config():
    graylog_url = os.getenv("GRAYLOG_MCP_URL", "http://127.0.0.1:9000/api/mcp")
    has_auth = bool((os.getenv("GRAYLOG_MCP_AUTH") or "").strip())
    has_yandex = bool(os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH"))
    has_catalog = bool(os.getenv("YANDEX_CATALOG_ID"))
    log.info("[STARTUP] GRAYLOG_MCP_URL=%s, GRAYLOG_MCP_AUTH=%s, YANDEX=%s, CATALOG_ID=%s",
             graylog_url, "задан" if has_auth else "НЕТ", "ok" if has_yandex else "НЕТ", "ok" if has_catalog else "НЕТ")

app = FastAPI(title="Logs AI + Yandex", description="Чат с Graylog через Yandex GPT")


@app.on_event("startup")
async def startup_event():
    _log_startup_config()

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the chat UI."""
    html_path = static_dir / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return """
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Logs AI + Yandex</title></head>
    <body>
        <h1>Logs AI + Yandex</h1>
        <p>Создайте файл static/index.html для UI</p>
    </body>
    </html>
    """


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process user message through Yandex + Graylog MCP agent."""
    msg = request.message.strip()
    if not msg:
        log.warning("[CHAT] Отклонён пустой запрос")
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    log.info("[CHAT] ========== НАЧАЛО ОБРАБОТКИ ЗАПРОСА ==========")
    log.info("[CHAT] Сообщение пользователя (%d символов): %s", len(msg), msg[:120] + ("..." if len(msg) > 120 else ""))

    graylog_url = os.getenv("GRAYLOG_MCP_URL", "http://127.0.0.1:9000/api/mcp")
    graylog_auth = os.getenv("GRAYLOG_MCP_AUTH", "")  # "Basic <base64>"
    log.info("[CHAT] Конфиг: GRAYLOG_MCP_URL=%s, auth=%s", graylog_url, "задан" if graylog_auth.strip() else "НЕТ")

    try:
        log.info("[CHAT] Вызов run_agent()...")
        response = await run_agent(
            user_message=msg,
            graylog_url=graylog_url,
            graylog_auth_header=graylog_auth.strip() or "",
        )
        log.info("[CHAT] ========== УСПЕХ ========== Ответ готов: %d символов", len(response))
        log.info("[CHAT] Начало ответа: %s", (response[:150] + "..." if len(response) > 150 else response))
        return ChatResponse(response=response)
    except ValueError as e:
        log.warning("[CHAT] Ошибка валидации: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("[CHAT] ИСКЛЮЧЕНИЕ при обработке запроса")
        # Извлекаем реальную причину (TaskGroup скрывает её)
        cause = getattr(e, "__cause__", None) or e
        while hasattr(cause, "__cause__") and cause.__cause__:
            cause = cause.__cause__
        err_msg = str(cause) if cause else str(e)
        log.error("[CHAT] Причина ошибки: %s", err_msg)
        raise HTTPException(status_code=500, detail=f"Ошибка: {err_msg}")


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    """Проверка подключения к Graylog MCP и Yandex."""
    import httpx

    log.info("[STATUS] Проверка статуса сервисов...")
    graylog_url = os.getenv("GRAYLOG_MCP_URL", "http://127.0.0.1:9000/api/mcp")
    graylog_auth = (os.getenv("GRAYLOG_MCP_AUTH") or "").strip()
    yandex_ok = bool(os.getenv("YANDEX_API_KEY") or os.getenv("YANDEX_OAUTH"))
    yandex_catalog = bool(os.getenv("YANDEX_CATALOG_ID"))

    result = {
        "yandex": "ok" if (yandex_ok and yandex_catalog) else "нет YANDEX_API_KEY или YANDEX_CATALOG_ID",
        "graylog_mcp": None,
    }

    if not graylog_auth:
        result["graylog_mcp"] = "нет GRAYLOG_MCP_AUTH в .env"
        log.warning("[STATUS] Graylog MCP: нет GRAYLOG_MCP_AUTH в .env")
    else:
        try:
            log.info("[STATUS] Проверка Graylog MCP: POST %s", graylog_url)
            r = httpx.post(
                graylog_url,
                headers={"Authorization": graylog_auth, "Content-Type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "logs-ai-check", "version": "1.0"},
                    },
                },
                timeout=10,
            )
            if r.status_code == 200:
                result["graylog_mcp"] = "ok"
                log.info("[STATUS] Graylog MCP: ok")
            else:
                data = r.json() if "application/json" in (r.headers.get("content-type") or "") else {}
                err = f"ошибка {r.status_code}: {data.get('message', r.text[:200])}"
                result["graylog_mcp"] = err
                log.warning("[STATUS] Graylog MCP: %s", err)
        except Exception as e:
            result["graylog_mcp"] = f"ошибка: {e}"
            log.warning("[STATUS] Graylog MCP исключение: %s", e)

    log.info("[STATUS] Результат: yandex=%s, graylog=%s", result["yandex"], result["graylog_mcp"])
    return result
