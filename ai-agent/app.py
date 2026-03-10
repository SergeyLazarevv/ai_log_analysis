"""AI Agent: Web UI for chat with Graylog and PostgreSQL via Yandex GPT."""

from __future__ import annotations

import asyncio
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
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from agent import LogsAgent
from config import AppConfig

# Загрузка .env (override=True — .env всегда главнее переменных окружения shell)
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env", override=True)
load_dotenv(_root.parent / "yandexGptCli" / "src" / ".env")

# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="AI Agent", description="Чат с Graylog и PostgreSQL через Yandex GPT")


@app.on_event("startup")
async def startup_event():
    config = AppConfig.from_env()
    log.info("[STARTUP] %s", config.log_summary())


# ── Web UI (главная страница) ───────────────────────────────────────────────

_INDEX_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LogsAI — чат с агентом</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #1a1d23; color: #e4e6eb; min-height: 100vh; }
    .container { max-width: 720px; margin: 0 auto; padding: 1rem; min-height: 100vh; display: flex; flex-direction: column; }
    h1 { font-size: 1.25rem; margin: 0 0 1rem; font-weight: 600; }
    .chat { flex: 1; overflow-y: auto; margin-bottom: 1rem; }
    .msg { margin: 0.75rem 0; padding: 0.75rem 1rem; border-radius: 10px; max-width: 95%; white-space: pre-wrap; word-break: break-word; }
    .msg.user { background: #2d3748; margin-left: 0; margin-right: auto; }
    .msg.assistant { background: #2c5282; margin-left: auto; margin-right: 0; }
    .msg.error { background: #742a2a; }
    .form { display: flex; gap: 0.5rem; }
    #input { flex: 1; padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid #4a5568; background: #2d3748; color: #e4e6eb; font-size: 1rem; }
    #input:focus { outline: none; border-color: #63b3ed; }
    #send { padding: 0.75rem 1.25rem; border-radius: 8px; border: none; background: #3182ce; color: white; font-weight: 600; cursor: pointer; }
    #send:hover { background: #2c5282; }
    #send:disabled { opacity: 0.5; cursor: not-allowed; }
    .status { font-size: 0.85rem; color: #a0aec0; margin-top: 0.5rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>LogsAI — чат с агентом (Graylog, БД, GitLab)</h1>
    <div class="chat" id="chat"></div>
    <form class="form" id="form">
      <input type="text" id="input" placeholder="Задайте вопрос по логам, БД или коду..." autocomplete="off">
      <button type="submit" id="send">Отправить</button>
    </form>
    <div class="status" id="status"></div>
  </div>
  <script>
    const chat = document.getElementById('chat');
    const form = document.getElementById('form');
    const input = document.getElementById('input');
    const send = document.getElementById('send');
    const status = document.getElementById('status');

    function addMsg(role, text, isError) {
      const div = document.createElement('div');
      div.className = 'msg ' + role + (isError ? ' error' : '');
      div.textContent = text;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      addMsg('user', text);
      send.disabled = true;
      status.textContent = 'Отправка запроса...';

      try {
        const r = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, conversation: [] })
        });
        const data = await r.json();
        if (!r.ok) {
          addMsg('assistant', 'Ошибка: ' + (data.detail || r.statusText), true);
        } else {
          addMsg('assistant', data.response || '');
        }
      } catch (err) {
        addMsg('assistant', 'Ошибка сети: ' + err.message, true);
      }
      status.textContent = '';
      send.disabled = false;
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    """Главная страница — простой чат с агентом."""
    return HTMLResponse(_INDEX_HTML)


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

    # history = [{"role": t.role, "content": t.content} for t in (request.conversation or [])]
    history: list = []
    log.info("[CHAT] Запрос: %d симв.: %s", len(msg), msg[:120])
    config = AppConfig.from_env()
    agent = LogsAgent(config)

    try:
        response = await agent.run(msg, history=history)
        log.info("[CHAT] Ответ готов: %d симв.", len(response))
        return ChatResponse(response=response)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except asyncio.CancelledError:
        raise
    except BaseException as e:
        log.exception("[CHAT] Исключение при обработке запроса")
        cause = e
        while getattr(cause, "__cause__", None):
            cause = cause.__cause__
        if getattr(cause, "exceptions", None):
            cause = cause.exceptions[0]
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

    if not messages:
        raise HTTPException(status_code=400, detail="Нет сообщений пользователя")

    # Последнее сообщение — текущий вопрос, всё остальное — история диалога
    current = messages[-1]
    msg = (current.get("content") or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    # history = [{"role": m["role"], "content": m.get("content", "")} for m in messages[:-1]]
    history: list = []

    # Open WebUI шлёт служебные запросы на генерацию подсказок и заголовков —
    # они не требуют MCP, передаём напрямую в YandexGPT без агента.
    _SYSTEM_PREFIXES = ("### Task:", "Generate a title", "Suggest ", "You are a title")
    if any(msg.startswith(p) for p in _SYSTEM_PREFIXES):
        return await _handle_utility_request(msg, body)

    log.info("[OPENAI] Запрос от Open WebUI: %d симв.: %s", len(msg), msg[:120])
    config = AppConfig.from_env()
    agent = LogsAgent(config)

    try:
        response_text = await agent.run(msg, history=history)
        log.info("[OPENAI] Ответ готов: %d симв.", len(response_text))
    except asyncio.CancelledError:
        raise
    except BaseException as e:
        log.exception("[OPENAI] Исключение при обработке запроса")
        cause = e
        while getattr(cause, "__cause__", None):
            cause = cause.__cause__
        if getattr(cause, "exceptions", None):
            cause = cause.exceptions[0]
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
                  else "нет YANDEX_API_KEY или YANDEX_CATALOG_ID",  # type: ignore[truthy-bool]
        "graylog_mcp": None,
        "postgres_mcp_dsn": "задан" if config.postgres.is_configured else "не задан (добавьте POSTGRES_MCP_DSN в .env)",
        "npx_available": None,
    }

    result["graylog_mcp"] = await _check_graylog(config.graylog.url, config.graylog.auth)
    result["npx_available"] = _check_npx()

    log.info("[STATUS] %s", result)
    return result


# ── Вспомогательные функции ─────────────────────────────────────────────────

async def _handle_utility_request(msg: str, body: dict) -> JSONResponse:
    """Служебные запросы Open WebUI (подсказки, заголовки) — без MCP, напрямую в LLM."""
    log.info("[OPENAI] Служебный запрос Open WebUI (%d симв.) — без MCP", len(msg))
    config = AppConfig.from_env()
    from yandex_client import YandexClient
    try:
        llm = YandexClient(
            config.yandex_api_key,  # type: ignore[arg-type]
            config.yandex_catalog_id,  # type: ignore[arg-type]
            config.yandex_model,
        )
        response_text = await llm.complete([{"role": "user", "content": msg}])
    except Exception:
        response_text = ""
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "ai-agent"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response_text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


async def _check_graylog(url: str, auth: str) -> str:
    if not auth:
        return "нет GRAYLOG_MCP_AUTH в .env"
    try:
        r = httpx.post(
            url,
            headers={"Authorization": auth, "Content-Type": "application/json"},
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
        if r.status_code == 401:
            return (
                "401 Unauthorized. Формат: GRAYLOG_MCP_AUTH=Basic <base64(ваш_токен:token)>. "
                "Токен: Graylog → System → Users and Teams → пользователь → Edit tokens. "
                "Срок действия по умолчанию 30 дней — создайте новый токен. "
                "Проверка: из каталога ai-agent выполните python check_mcp.py"
            )
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
