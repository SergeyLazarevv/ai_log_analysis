# PHP Graylog seeder

This folder contains a small CLI script that sends demo logs to Graylog using **GELF**.

## 1) Create input in Graylog UI

In Graylog:

- `System` → `Inputs`
- `Select input`: **GELF UDP**
- `Port`: **12201**
- `Node`: Global (or pick your node)

`docker-compose.yml` already exposes `12201/udp` and `12201/tcp`.

## 2) Run the script

From repo root:

```bash
php php/graylog_seed.php order_created --order-id=12345
php php/graylog_seed.php order_cancelled --order-id=12345 --reason="payment timeout"
php php/graylog_seed.php sms_error --order-id=12345 --phone="+79990001122"
# Логи с "error" в сообщении — для проверки поиска "сколько ошибок за сегодня"
php php/graylog_seed.php error --order-id=999
php php/graylog_seed.php error --count=10 --reason="Database connection failed"
php php/graylog_seed.php random --count=50 --sleep-ms=100
```

## 3) Configure target (optional)

By default it sends to `127.0.0.1:12201` via UDP.

```bash
export GRAYLOG_GELF_HOST=127.0.0.1
export GRAYLOG_GELF_PORT=12201
export GRAYLOG_GELF_PROTO=udp   # udp|tcp
```

