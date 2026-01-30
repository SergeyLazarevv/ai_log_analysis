# LogsAi (Graylog + local seeder)

Короткая инструкция для локального запуска Graylog и наполнения логами.

## Запуск Graylog (Docker Compose)

0) Убедись, что доступен **Compose v2** (команда `docker compose`).

На Ubuntu 22.04 обычно достаточно:

```bash
sudo apt update
sudo apt install -y docker-compose-v2
```

1) Подготовь переменные окружения:

```bash
cp .env.example .env
```

2) В `.env` обязательно задай:

- `GRAYLOG_PASSWORD_SECRET` (случайная строка **>= 16** символов)
- `GRAYLOG_ROOT_PASSWORD_SHA2` (sha256 от пароля `admin`, **без перевода строки**)
- `OPENSEARCH_INITIAL_ADMIN_PASSWORD` (строгий пароль: **upper + lower + digit + special**)

Пример генерации хэша пароля:

```bash
printf '%s' 'admin' | sha256sum | awk '{print $1}'
```

3) (Часто нужно на Linux) настрой `vm.max_map_count` для OpenSearch:

```bash
sudo sysctl -w vm.max_map_count=262144
```

4) Подними сервисы:

```bash
docker compose up -d
```

Если получишь `permission denied while trying to connect to the Docker daemon socket`, запускай через `sudo`:

```bash
sudo docker compose up -d
```

5) Открой UI:

- `http://127.0.0.1:9000/`
- логин: `admin`
- пароль: тот, для которого ты делал sha256 в `GRAYLOG_ROOT_PASSWORD_SHA2`

## Наполнение логами (PHP скрипт)

1) Установи PHP CLI (если ещё нет):

```bash
sudo apt update
sudo apt install -y php-cli
```

2) В Graylog UI создай input для GELF:

- `System` → `Inputs` → **GELF UDP**
- `Port`: **12201**

3) Запускай генератор логов:

```bash
php php/graylog_seed.php order_created --order-id=12345
php php/graylog_seed.php order_cancelled --order-id=12345 --reason="payment timeout"
php php/graylog_seed.php sms_error --order-id=12345 --phone="+79990001122"
php php/graylog_seed.php random --count=50 --sleep-ms=100
```

По умолчанию скрипт отправляет в `127.0.0.1:12201` по UDP.

## Локальная LLM (Ollama) отдельным compose

Ollama поднимается отдельно в папке `ollama/` и слушает API на `http://127.0.0.1:11434`.  
Также включён **Open WebUI** (веб-интерфейс) на `http://127.0.0.1:3000`.

```bash
cd /home/user/projects/LogsAi/ollama
docker compose up -d
```

После запуска открой `http://127.0.0.1:3000` и создай аккаунт (первый пользователь — админ).

Чтобы скачать лёгкую модель (пример: `llama3.2:1b`):

```bash
cd /home/user/projects/LogsAi/ollama
docker compose --profile init up pull-model
```

Если `ollama pull` падает с `x509: certificate signed by unknown authority`, см. `ollama/README.md` (нужно добавить корпоративный CA в `ollama/certs/`).

