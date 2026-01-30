# Ollama (local LLM) + Open WebUI

This stack runs **Ollama** locally in Docker and exposes its API on port `11434`, plus **Open WebUI** (веб-интерфейс) on port `3000`.

## Вариант: Ollama локально (без Docker)

Если не хочешь возиться с Docker и переносом сертификатов — поставь Ollama прямо в систему. Тогда он будет использовать **системное хранилище сертификатов** (siroot уже там), и `ollama pull` будет работать и без VPN, и по VPN, без доп. настройки.

**Установка (официальный скрипт):**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

После установки сервис обычно уже запущен. Если нет:

```bash
ollama serve
```

В другом терминале:

```bash
ollama pull llama3.2:1b
ollama run llama3.2:1b "Привет!"
```

API будет на `http://127.0.0.1:11434`. Open WebUI из этого репозитория (Docker) можно по-прежнему использовать — в настройках укажи `OLLAMA_BASE_URL=http://host.docker.internal:11434` или IP хоста, если контейнер не видит `localhost`.

### Если при локальной установке: `x509: certificate signed by unknown authority`

Ollama (Go) может не подхватывать системное хранилище CA даже при `SSL_CERT_FILE`. Запрос к registry выполняет **сервер** (ollama serve), а не команда в терминале, поэтому флаг `--insecure` и переменная в терминале не помогают — нужно задать переменную **для сервиса**.

**Отключить проверку сертификата при загрузке (обходной путь)**

Подходит, если доверяешь сети (домашний Wi‑Fi). Переменная `OLLAMA_INSECURE` должна быть у процесса **сервера** ollama:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
echo -e '[Service]\nEnvironment="OLLAMA_INSECURE=true"' | sudo tee /etc/systemd/system/ollama.service.d/insecure.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

После этого снова:

```bash
ollama pull llama3.2:1b
```

(Флаг `--insecure` в команде можно не указывать — сервер уже работает в режиме «не проверять сертификат» при обращении к registry.)

**Важно:** во многих версиях Ollama переменная `OLLAMA_INSECURE` и флаг `--insecure` **не отключают** проверку сертификата — это известная проблема. Если ошибка остаётся, переходи к шагам ниже.

**Шаг 1: обновить системные сертификаты**

Убедись, что пакет и хранилище в порядке:

```bash
sudo apt-get install -y ca-certificates
sudo update-ca-certificates
```

**Шаг 2: заставить сервис Ollama использовать системное хранилище**

Задай для сервиса и файл, и каталог (Go иногда требует оба):

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
echo -e '[Service]\nEnvironment="SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"\nEnvironment="SSL_CERT_DIR=/etc/ssl/certs"' | sudo tee /etc/systemd/system/ollama.service.d/ca-cert.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Потом снова: `ollama pull llama3.2:1b`.

**Если всё равно ошибка:** надёжный обход — либо **Docker** (папка `ollama/certs/` + siroot, см. раздел «Если нужны и рабочий VPN, и Ollama без VPN»), либо **ручная загрузка GGUF** (раздел «Вариант без ollama pull»).

**Альтернатива: проверить SSL только в терминале**

```bash
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt ollama pull llama3.2:1b
```

Если в терминале сработало, а без переменной — нет, настрой сервис (Шаг 2 выше).

## Как работать с Ollama (основные команды)

### Какие модели можно поставить

В терминале нет команды «показать все модели в каталоге». Список доступных моделей смотри на сайте:

- **https://ollama.com/library** — каталог: название, размер, описание.

Популярные примеры: `llama3.2`, `llama3.1`, `mistral`, `gemma2`, `qwen2.5`, `phi3`, `codellama` и т.д. У многих моделей есть варианты по размеру (например `llama3.2:1b`, `llama3.2:3b`).

### Что уже установлено

```bash
ollama list
```

Показывает скачанные модели и их размер.

### Установка модели

```bash
ollama pull <имя_модели>
```

Примеры:

```bash
ollama pull llama3.2:1b    # лёгкая модель
ollama pull llama3.1       # средняя
ollama pull mistral        # Mistral
ollama pull qwen2.5:7b     # Qwen 7B
```

При первом запуске скачиваются файлы; потом модель будет доступна офлайн.

### Использование

**Интерактивный чат** (диалог в терминале):

```bash
ollama run <имя_модели>
```

После запуска просто вводишь сообщения и получаешь ответы. Выход: `/bye` или Ctrl+D.

**Один запрос и выход:**

```bash
ollama run <имя_модели> "Твой вопрос или задание"
```

Пример:

```bash
ollama run llama3.2:1b "Объясни за 2 предложения, что такое API"
```

### Ещё полезные команды

| Команда | Что делает |
|--------|------------|
| `ollama list` | Список установленных моделей |
| `ollama ps` | Какие модели сейчас загружены в память |
| `ollama show <модель>` | Инфо о модели (размер, параметры) |
| `ollama stop <модель>` | Выгрузить модель из памяти |
| `ollama rm <модель>` | Удалить модель с диска |

### Через API (для скриптов и приложений)

- Список моделей: `curl http://localhost:11434/api/tags`
- Генерация ответа: POST `http://localhost:11434/api/generate` или `/api/chat` (JSON, см. [документацию](https://github.com/ollama/ollama/blob/main/docs/api.md)).

---

## Start (Docker)

```bash
cd /home/user/projects/LogsAi/ollama
docker compose up -d
```

## Access UI

После запуска открой в браузере:

- **Open WebUI**: `http://127.0.0.1:3000`
- **Ollama API**: `http://127.0.0.1:11434`

При первом входе в Open WebUI нужно будет создать аккаунт (первый пользователь автоматически становится админом).

## Pull a lightweight model

Option A (recommended, one-time init helper):

```bash
cd /home/user/projects/LogsAi/ollama
docker compose --profile init up pull-model
```

Option B (manually):

```bash
cd /home/user/projects/LogsAi/ollama
docker compose exec ollama ollama pull llama3.2:1b
```

## Вариант без `ollama pull`: скачать GGUF и импортировать локально

Если `ollama pull` не работает (TLS/прокси) и ты **не знаешь, какие сертификаты нужны**, можно так:

1) **Скачай** одну модель в формате **`.gguf`** (через браузер — обычно он “доверяет” корпоративному прокси).
2) Положи файл в папку:
   - `ollama/models/`
3) Скопируй шаблон и укажи имя файла:
   - `ollama/models/Modelfile.example` → `ollama/models/Modelfile`
   - в `FROM /models/your-model.gguf` замени на реальное имя файла
4) Импортируй модель в Ollama:

```bash
cd /home/user/projects/LogsAi/ollama
docker compose exec ollama ollama create local-gguf -f /models/Modelfile
docker compose exec ollama ollama list
```

После этого модель появится и в **Open WebUI**.

### Какие модели лучше для анализа логов Graylog и отчётности (русский язык)

Для анализа логов, составления отчётов и поддержки русского лучше брать модели, специально дообученные на русском, а не «сырой» Llama 3.2 1B (она часто отвечает на вьетнамском/английском).

| Модель | Размер GGUF | RAM | Особенности |
|--------|-------------|-----|-------------|
| **Vikhr-Llama-3.2-1B-instruct** | ~400–830 MB | ~1–2 GB | Лёгкая, **русская** instruct-модель на базе Llama 3.2 1B. Хорошо держит русский, подходит для краткого анализа и отчётов. |
| **Saiga2-7B** | ~3–6 GB (Q4/Q5) | ~6–10 GB | Сильная русская модель 7B. Лучше для сложного анализа и формулировок, если хватает памяти. |
| **YandexGPT-5-Lite-8B** | ~5 GB (Q4_K_M) | ~8–10 GB | Русский 8B от Яндекса, хорошее качество для отчётности. |
| **T-lite-it-2.1** (Qwen3 8B) | ~5 GB (Q4_K_M) | ~8–10 GB | Русский, поддержка tool-calling, удобно для структурированного вывода. |

**Рекомендация для «легковесного» варианта:**  
Скачай **Vikhr-Llama-3.2-1B-instruct** в GGUF — та же «весовая» категория, что и текущая 1B, но с нормальной поддержкой русского:

- **Hugging Face:** [Vikhrmodels/Vikhr-Llama-3.2-1B-instruct-GGUF](https://huggingface.co/Vikhrmodels/Vikhr-Llama-3.2-1B-instruct-GGUF)  
- Вариант **Q4_K_M** (~400–500 MB) или **Q5_K_M** — баланс качества и размера.  
- В Modelfile укажи `FROM /models/имя_файла.gguf` и, при желании, `SYSTEM` с текстом вроде: «Ты помощник по анализу логов. Отвечай кратко, только на русском, в формате, удобном для отчётов.»

Если есть 8+ GB RAM и нужен более «умный» анализ — **Saiga2-7B** (коллекция [Saiga GGUF](https://huggingface.co/collections/IlyaGusev/saiga-gguf)) или **YandexGPT-5-Lite-8B**.

### Развернуть модель в Docker для проверки MCP / Graylog (без pull)

Ollama в Docker уже слушает на `http://127.0.0.1:11434` — для проверки MCP/Graylog нужна только одна модель внутри контейнера, **без** обращения к registry.

**Шаги:**

1. **Скачай один файл `.gguf`** через браузер (обход проблем с сертификатами):
   - Например: [Hugging Face — Llama-3.2-1B-Instruct в GGUF](https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/tree/main) — возьми вариант `Q4_K_M` или `Q8_0` (файл ~600 MB–1 GB).
   - Или поиск по `llama 3.2 1b gguf` на Hugging Face — любой маленький instruct-модель в `.gguf`.

2. **Положи файл** в `ollama/models/`, например:
   - `ollama/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf`

3. **Создай Modelfile** в `ollama/models/Modelfile`:

```
FROM /models/Llama-3.2-1B-Instruct-Q4_K_M.gguf
PARAMETER temperature 0.2
PARAMETER num_ctx 2048
SYSTEM """Ты полезный ассистент. Отвечай кратко."""
```

(Имя файла в `FROM` — как у скачанного файла.)

4. **Запусти контейнеры** (если ещё не запущены) и **импортируй модель**:

```bash
cd /home/user/projects/LogsAi/ollama
docker compose up -d
docker compose exec ollama ollama create local-llm -f /models/Modelfile
```

5. **Проверка** — модель в списке и отвечает:

```bash
docker compose exec ollama ollama list
docker compose exec ollama ollama run local-llm "Что такое Graylog в двух предложениях?"
```

Если в выводе видны «каракули» (коды вида `[?25l`, `[K`) — это служебные символы терминала при потоковом выводе. Чистый текст без них:

```bash
TERM=dumb docker compose exec ollama ollama run local-llm "Что такое Graylog?"
```

или через API (JSON, без escape-кодов):

```bash
curl -s http://127.0.0.1:11435/api/generate -d '{"model":"local-llm","prompt":"Что такое Graylog?","stream":false}' | jq -r '.response'
```

(Порт `11435` — если в docker-compose указан он; иначе `11434`.)

В Modelfile в `SYSTEM` добавлено «отвечай только на русском», чтобы модель не переключалась на другой язык. После изменения Modelfile модель нужно пересоздать: `ollama create local-llm -f /models/Modelfile` (с флагом перезаписи при необходимости).

API для MCP/Graylog: `http://127.0.0.1:11434` (или `http://ollama:11434` из другой контейнерной сети). Имя модели в запросах: `local-llm`.

## Если нужны и рабочий VPN, и Ollama без VPN (одна настройка на все случаи)

На хосте сертификат **siroot** (Generic Root CA 2) лучше не трогать — он нужен для веб-сервисов по рабочему VPN. Чтобы при этом Ollama в Docker работал и **без VPN**, и **с VPN**, один раз добавь тот же корень в контейнер:

1. Создай папку для сертификатов (если её ещё нет) и скопируй туда системный корень:

```bash
mkdir -p /home/user/projects/LogsAi/ollama/certs
sudo cp /usr/local/share/ca-certificates/siroot.crt /home/user/projects/LogsAi/ollama/certs/
sudo chown "$USER:$USER" /home/user/projects/LogsAi/ollama/certs/siroot.crt
```

2. Перезапусти контейнеры:

```bash
cd /home/user/projects/LogsAi/ollama
docker compose down
docker compose up -d
```

После этого контейнер Ollama доверяет и обычным CA (дома без VPN), и корпоративному siroot (по VPN). Сертификат на хосте остаётся как был — веб в браузере и по VPN, и без него работает как раньше.

## If `ollama pull` fails with TLS / x509 errors

If you see errors like `x509: certificate signed by unknown authority`, your network is likely doing HTTPS interception (corporate proxy / custom CA).

Fix:

- Put your corporate/root CA certificate(s) as `.crt` files into:
  - `ollama/certs/`
- Restart containers:

```bash
cd /home/user/projects/LogsAi/ollama
docker compose down
docker compose up -d
```

Then retry the pull.

## Quick test

```bash
cd /home/user/projects/LogsAi/ollama
docker compose exec ollama ollama run llama3.2:1b "Привет! Коротко объясни что такое Graylog."
```

