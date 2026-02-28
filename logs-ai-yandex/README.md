# Logs AI + Yandex

Веб-интерфейс для анализа логов Graylog через Yandex GPT. Модель может обращаться к Graylog по MCP и получать данные (поиск логов, стримы, статус системы).

## Архитектура

```
Пользователь → [Web UI] → FastAPI → Agent (Yandex GPT + MCP Client)
                                    ↓
                              Graylog MCP (/api/mcp)
```

- **Yandex GPT** — отвечает на вопросы, решает когда вызвать инструмент
- **ReAct** — модель выводит `TOOL_CALL: tool_name {"args"}` в ответе
- **MCP Client** — выполняет вызовы Graylog MCP и возвращает результаты в контекст

## Требования

- Python 3.10+
- Graylog 7.0+ с включённым MCP
- Yandex Cloud: API-ключ и ID каталога

## Что установить в систему

Чат запускается на хосте (не в Docker), поэтому нужны:

| Что | Зачем |
|-----|--------|
| **Python 3.10+** | Запуск приложения |
| **pip** | Установка зависимостей (`pip install -r requirements.txt`) |
| **Node.js** (LTS, например 20.x) | Нужен только если используешь Postgres MCP: агент вызывает `npx @modelcontextprotocol/server-postgres`. Без Node чат будет работать только с Graylog. |
| **npx** | Идёт вместе с Node.js; отдельно ставить не нужно. |

**Установка Node.js (если нужен Postgres MCP):**

- **Ubuntu/Debian:** `sudo apt install nodejs npm` (или [NodeSource](https://github.com/nodesource/distributions) для свежей LTS).
- **macOS:** `brew install node`.
- **Проверка:** `node -v` и `npx -v` должны выполняться без ошибок.

Если **не** задавать `POSTGRES_MCP_DSN` в `.env`, Postgres MCP не используется и Node.js не нужен.

## Установка

```bash
cd logs-ai-yandex
pip install -r requirements.txt
```

## Настройка

Переменные подхватываются автоматически:

| Переменная | Откуда |
|------------|--------|
| `YANDEX_API_KEY`, `YANDEX_CATALOG_ID` | `LogsAi/.env` или `yandexGptCli/src/.env` |
| `GRAYLOG_MCP_URL`, `GRAYLOG_MCP_AUTH` | `LogsAi/.env` (из `mcp/cursor-mcp-config.json`) |
| `POSTGRES_MCP_DSN` (опционально) | `LogsAi/.env` — строка подключения к PostgreSQL для MCP (read-only). Если задана — один агент работает и с логами, и с БД. |

Отдельный `.env` в `logs-ai-yandex/` не нужен — всё в соседних проектах.

**Два MCP (Graylog + Postgres):** при заданном `POSTGRES_MCP_DSN` агент поднимает ещё один MCP-сервер (stdio, `npx @modelcontextprotocol/server-postgres`). Нужен Node.js в окружении. Подробнее: [MCP_DUAL_GRAYLOG_POSTGRES.md](MCP_DUAL_GRAYLOG_POSTGRES.md).

## Запуск

### Локально

```bash
uvicorn app:app --reload --port 8000
```

Откройте http://127.0.0.1:8000

### Docker

Запуск из корня LogsAi (подхватывает `LogsAi/.env`):

```bash
cd /path/to/LogsAi
docker compose -f logs-ai-yandex/docker-compose.yml --env-file .env up -d
```

Или из `logs-ai-yandex/` после `cp ../.env .env`:

```bash
cd logs-ai-yandex && cp ../.env .env 2>/dev/null || true
docker compose up -d
```

Откройте http://127.0.0.1:3020

**Примечание:** Graylog должен быть доступен по `GRAYLOG_MCP_URL`. В Docker используется `host.docker.internal:9000` для доступа к Graylog на хосте.

## Использование

1. Откройте UI в браузере
2. Введите вопрос, например:
   - «Покажи список стримов в Graylog»
   - «Какой статус системы?»
   - «Найди сообщения с ошибками за последний час и кратко резюмируй»
3. Модель при необходимости обратится к Graylog через MCP и даст ответ

## Ограничения

- Модель использует ReAct-подход (prompt-based tool calling), а не нативный function calling
- YandexGPT может не всегда корректно выводить `TOOL_CALL` — при ошибках переформулируйте вопрос
- MCP в Graylog 7.0 в статусе beta
