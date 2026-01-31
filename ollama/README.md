# Ollama + Open WebUI

Локальный LLM в Docker: **Ollama** (API) и **Open WebUI** (веб-интерфейс).

---

## Запуск

```bash
cd /home/user/projects/LogsAi/ollama
docker compose up -d
```

- **Open WebUI:** http://127.0.0.1:3000  
- **Ollama API:** http://127.0.0.1:11435  

При первом входе в Open WebUI создай аккаунт.

---

## Смена модели

### Вариант 1: скачать модель из каталога (если сеть без перехвата HTTPS)

```bash
cd /home/user/projects/LogsAi/ollama
docker compose exec ollama ollama pull <имя_модели>
```

Примеры: `llama3.2:1b`, `mistral`, `qwen2.5:7b`. В UI появится модель с тем же именем.

### Вариант 2: локальный GGUF (офлайн или при проблемах с сертификатами)

1. Положи файл `.gguf` в `ollama/models/`.

2. В `ollama/models/Modelfile` укажи этот файл и при желании параметры:

   ```
   FROM /models/ИмяФайла.gguf
   PARAMETER temperature 0.2
   PARAMETER num_ctx 2048
   SYSTEM """Ты полезный ассистент. Отвечай кратко."""
   ```

3. Создай/перезапиши образ в Ollama (имя `local-llm` будет в UI как **local-llm:latest**):

   ```bash
   cd /home/user/projects/LogsAi/ollama
   docker compose exec ollama ollama create local-llm -f /models/Modelfile
   ```

4. Проверка:

   ```bash
   docker compose exec ollama ollama list
   ```

5. В Open WebUI обнови список моделей и выбери **local-llm:latest**.

Чтобы сменить модель на другой GGUF — замени файл в `models/` и строку `FROM` в Modelfile, затем снова выполни `ollama create local-llm -f /models/Modelfile`.
