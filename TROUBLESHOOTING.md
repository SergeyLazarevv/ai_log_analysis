# Решение типичных проблем

## Модель отвечает «нет доступа к данным» / не подключается к Graylog и БД

**Симптом:** в чате модель пишет, что у неё нет доступа к логам или к БД, вместо того чтобы вызывать инструменты.

**Причина:** агент не смог подключиться к MCP (Graylog и/или Postgres) и работает без инструментов. При первой же ошибке подключения в чат возвращается подсказка с текстом ошибки и «вероятной причиной».

**Что сделать:**

1. Откройте **http://127.0.0.1:3020/api/status** (или ваш хост/порт Logs AI). Там видно:
   - **graylog_mcp** — доходит ли запрос до Graylog (ok / ошибка / нет GRAYLOG_MCP_AUTH);
   - **postgres_mcp_dsn** — задан ли POSTGRES_MCP_DSN;
   - **npx_available** — найден ли npx (нужен для Postgres MCP).

2. **Graylog:** если `graylog_mcp` не «ok»:
   - Запущен ли Graylog? (`docker compose ps`, порт 9000).
   - Включён ли MCP: в веб-интерфейсе Graylog → System → Configurations → MCP → Enable.
   - В `LogsAi/.env` заданы `GRAYLOG_MCP_URL` (например `http://127.0.0.1:9000/api/mcp`) и `GRAYLOG_MCP_AUTH` (Basic и base64 от `API_TOKEN:token`).

3. **Postgres MCP:** если нужны вопросы по БД:
   - В `.env` задан `POSTGRES_MCP_DSN=postgresql://logsai:пароль@127.0.0.1:5432/logsai` (хост 127.0.0.1 при локальном запуске).
   - Установлен Node.js: в терминале `npx --version` должен выполняться без ошибок.
   - Postgres запущен и доступен на порту 5432 (логин/пароль/БД совпадают с DSN).

4. Перезапустите приложение Logs AI после изменений в `.env` и снова откройте `/api/status` и задайте вопрос в чате.

---

## Docker: `x509: certificate signed by unknown authority` при сборке logs-ai

**Симптом:** при `docker compose up -d` или `docker compose build` ошибка:
```text
failed to fetch anonymous token: Get "https://auth.docker.io/...": tls: failed to verify certificate: x509: certificate signed by unknown authority
```

Docker не доверяет сертификату при обращении к registry (Docker Hub). Это не ошибка зависимостей внутри образа.

**Что можно сделать:**

1. **Корпоративный прокси/файрвол**  
   Если есть подмена HTTPS (MITM), в доверенные корневые сертификаты Docker нужно добавить корпоративную CA.  
   Обычно: положить сертификат в `/usr/local/share/ca-certificates/` или в каталог, указанный в `DOCKER_CERT_PATH`, и обновить хранилище (например `update-ca-certificates`), затем перезапустить Docker.

2. **Проверить время**  
   Неточные дата/время часто ломают проверку сертификатов:
   ```bash
   date
   ```

3. **Собрать образ в окружении с нормальным доступом к Docker Hub**  
   Например, на другой машине или в CI, затем сохранить образ и загрузить на нужную:
   ```bash
   docker save logsai-logs-ai:latest | gzip > logs-ai.tar.gz
   # на целевой машине:
   gunzip -c logs-ai.tar.gz | docker load
   ```

4. **Запускать Logs AI без Docker (локально)**  
   Если нужен только чат, без монолита в контейнерах:
   ```bash
   cd logs-ai-yandex
   pip install -r requirements.txt
   # Установи Node.js для Postgres MCP (если нужен)
   export GRAYLOG_MCP_URL=http://127.0.0.1:9000/api/mcp
   export GRAYLOG_MCP_AUTH=Basic ...
   export YANDEX_API_KEY=...
   export YANDEX_CATALOG_ID=...
   # опционально: export POSTGRES_MCP_DSN=postgresql://...
   uvicorn app:app --host 0.0.0.0 --port 3020
   ```
   Postgres, Graylog и т.д. при этом могут оставаться в Docker или быть внешними.

5. **Использовать другой registry**  
   Если у вас есть внутренний или зеркальный registry с образом Python, в `logs-ai-yandex/Dockerfile` можно заменить `FROM python:3.12-slim` на полный адрес образа из этого registry (например `FROM your-registry.example.com/python:3.12-slim`).
