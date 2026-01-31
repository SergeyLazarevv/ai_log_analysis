# LogsAi — быстрый старт

## 1. Запуск всего

```bash
cd /home/user/projects/LogsAi

# Graylog + OpenSearch + MongoDB
docker compose up -d

# Logs AI + Yandex (UI для вопросов по логам)
docker compose -f logs-ai-yandex/docker-compose.yml --env-file .env up -d
```

Перед первым запуском: `cp .env.example .env` и заполни секреты (см. README.md).

**Для Logs AI:** в Graylog включи MCP: `System` → `Configurations` → `MCP` → Enable.

**Если «у меня нет доступа к логам»** — проверь токен MCP: http://127.0.0.1:3020/api/status  
Токен неверный? Создай новый: Graylog → `System` → `Users` → `Tokens` → Create. Затем:
```bash
echo -n "НОВЫЙ_API_TOKEN:token" | base64 -w0
```
Подставь в `LogsAi/.env`: `GRAYLOG_MCP_AUTH=Basic <результат>`

---

## 2. Накидать логов в Graylog (PHP)

**В Graylog UI:** `System` → `Inputs` → **GELF UDP** → Port `12201` → Launch.

```bash
cd /home/user/projects/LogsAi

php php/graylog_seed.php order_created --order-id=12345
php php/graylog_seed.php order_cancelled --order-id=12345 --reason="payment timeout"
php php/graylog_seed.php sms_error --order-id=12345 --phone="+79990001122"
php php/graylog_seed.php random --count=50 --sleep-ms=100
```

---

## 3. Открыть UI для нейронки

**Logs AI + Yandex:** http://127.0.0.1:3020

(Один чат: задаёшь вопрос → Yandex GPT обращается к Graylog по MCP → отвечает.)

---

## 4. Задать вопрос о логах

1. Открой http://127.0.0.1:3020
2. Введи вопрос, например:
   - «Покажи список стримов»
   - «Какой статус системы Graylog?»
   - «Найди ошибки за последний час и кратко резюмируй»
3. Нажми «Отправить»

---

## Порты

| Сервис        | URL                      |
|---------------|--------------------------|
| Graylog UI    | http://127.0.0.1:9000    |
| Logs AI + Yandex | http://127.0.0.1:3020 |
