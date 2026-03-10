"""GitLab REST API коннектор — работает без MCP, на любом тарифе GitLab.

Реализует BaseMCPConnector через GitLab REST API v4.
Инструменты описаны вручную — список фиксированный, но покрывает основные сценарии.

Конфиг из env:
  GITLAB_URL    — URL GitLab инстанса (https://gitlab.com или self-managed)
  GITLAB_TOKEN  — Personal Access Token (права: api или read_api)
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from urllib.parse import quote

import httpx

from .base import BaseMCPConnector

log = logging.getLogger("logs_ai.connectors.gitlab")

# ── Описание инструментов (аналог MCP tool schema) ─────────────────────────

_TOOLS: list[dict] = [
    {
        "name": "gitlab_list_projects",
        "description": "Список проектов GitLab, доступных по токену. Можно фильтровать поиском.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Поиск по имени проекта (необязательно)"},
                "limit": {"type": "integer", "description": "Количество результатов (по умолчанию 20)"},
            },
        },
    },
    {
        "name": "gitlab_get_project",
        "description": "Информация о конкретном проекте: описание, ветки, статистика.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID или путь проекта (например: 123 или namespace/project)"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "gitlab_list_issues",
        "description": "Список issues проекта. Можно фильтровать по статусу, метке, поиску.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID или путь проекта"},
                "state": {"type": "string", "description": "Статус: opened, closed, all (по умолчанию opened)"},
                "search": {"type": "string", "description": "Поиск по заголовку/описанию (необязательно)"},
                "labels": {"type": "string", "description": "Фильтр по меткам, через запятую (необязательно)"},
                "limit": {"type": "integer", "description": "Количество результатов (по умолчанию 20)"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "gitlab_list_merge_requests",
        "description": "Список merge request-ов проекта. Можно фильтровать по статусу.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID или путь проекта"},
                "state": {"type": "string", "description": "Статус: opened, closed, merged, all (по умолчанию opened)"},
                "search": {"type": "string", "description": "Поиск по заголовку (необязательно)"},
                "limit": {"type": "integer", "description": "Количество результатов (по умолчанию 20)"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "gitlab_list_pipelines",
        "description": "Список CI/CD пайплайнов проекта. Можно фильтровать по статусу.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID или путь проекта"},
                "status": {"type": "string", "description": "Статус: running, pending, success, failed, canceled, all"},
                "limit": {"type": "integer", "description": "Количество результатов (по умолчанию 10)"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "gitlab_list_commits",
        "description": "Последние коммиты в ветке проекта.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID или путь проекта"},
                "branch": {"type": "string", "description": "Имя ветки (по умолчанию — default branch)"},
                "limit": {"type": "integer", "description": "Количество коммитов (по умолчанию 20)"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "gitlab_get_file",
        "description": (
            "Читает содержимое файла из репозитория GitLab. "
            "Используй когда нужно изучить код по пути из стектрейса. "
            "Если указана строка (line), возвращает контекст ±20 строк вокруг неё."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID или путь проекта (например: mygroup/myapp)"},
                "file_path": {"type": "string", "description": "Путь к файлу в репозитории (например: app/Services/Payment/SberbankGateway.php)"},
                "ref": {"type": "string", "description": "Ветка или коммит (по умолчанию: main)"},
                "line": {"type": "integer", "description": "Номер строки из стектрейса — вернёт контекст ±20 строк вокруг неё (необязательно)"},
            },
            "required": ["project_id", "file_path"],
        },
    },
]


class GitLabConnector(BaseMCPConnector):
    """
    GitLab коннектор через REST API v4.
    Работает на любом тарифе GitLab (Free, Premium, Ultimate).
    """

    def __init__(self, url: str, token: str) -> None:
        self._base_url = url.rstrip("/")
        self._token = token  # Может быть пустым — тогда работаем анонимно (только публичные проекты)
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        # Токен необязателен: без него доступны только публичные проекты (rate limit: 60 req/hour)
        return bool(self._base_url)

    async def connect(self, stack: AsyncExitStack) -> None:
        mode = "с токеном" if self._token else "анонимно (только публичные проекты)"
        log.info("[GitLab] Подключение к %s/api/v4 (%s)", self._base_url, mode)

        headers = {"PRIVATE-TOKEN": self._token} if self._token else {}
        self._client = await stack.enter_async_context(
            httpx.AsyncClient(
                base_url=f"{self._base_url}/api/v4",
                headers=headers,
                timeout=30.0,
                verify=False,  # корпоративный SSL-перехватчик не доверяет cert chain gitlab.com
            )
        )

        if self._token:
            try:
                r = await self._client.get("/user")
                r.raise_for_status()
                user = r.json()
                log.info("[GitLab] Авторизован как: %s", user.get("username", "?"))
            except Exception as e:
                log.warning("[GitLab] Не удалось проверить токен: %s", e)
        else:
            log.info("[GitLab] Анонимный режим — приватные проекты недоступны")

        log.info("[GitLab] Инструментов: %d", len(_TOOLS))

    @property
    def tools(self) -> list[dict]:
        return _TOOLS

    async def call_tool(self, name: str, args: dict) -> str:
        if not self._client:
            return "Ошибка: GitLab не подключён"
        try:
            handlers = {
                "gitlab_list_projects": self._list_projects,
                "gitlab_get_project": self._get_project,
                "gitlab_list_issues": self._list_issues,
                "gitlab_list_merge_requests": self._list_merge_requests,
                "gitlab_list_pipelines": self._list_pipelines,
                "gitlab_list_commits": self._list_commits,
                "gitlab_get_file": self._get_file,
            }
            handler = handlers.get(name)
            if not handler:
                return f"Ошибка: неизвестный инструмент {name}"
            log.info("[GitLab] call_tool(%s, %s)", name, args)
            result = await handler(args)
            log.info("[GitLab] %s выполнен, результат: %d символов", name, len(result))
            return result
        except Exception as e:
            log.exception("[GitLab] Исключение при вызове %s: %s", name, e)
            return f"Ошибка: {e}"

    # ── обработчики инструментов ───────────────────────────────────────────

    async def _list_projects(self, args: dict) -> str:
        search = (args.get("search") or "").strip()
        params: dict = {"per_page": args.get("limit", 20)}

        if self._token:
            # С токеном — показываем только свои проекты
            params["membership"] = True
        else:
            # Без токена — ищем публичные проекты по namespace владельца если задан search,
            # иначе возвращаем подсказку
            if not search:
                return (
                    "Анонимный режим: укажи имя проекта или namespace для поиска.\n"
                    "Пример: поиск по 'web193527' покажет публичные проекты этого пользователя.\n"
                    "Или добавь GITLAB_TOKEN в .env для доступа к своим проектам."
                )

        if search:
            params["search"] = search

        r = await self._client.get("/projects", params=params)  # type: ignore[union-attr]
        r.raise_for_status()
        projects = r.json()
        if not projects:
            hint = "" if self._token else " (анонимный режим — видны только публичные проекты)"
            return f"Проекты не найдены{hint}"
        rows = [
            f"- [{p['id']}] {p['path_with_namespace']} — {p.get('description') or 'без описания'}"
            for p in projects
        ]
        return "\n".join(rows)

    async def _get_project(self, args: dict) -> str:
        pid = _encode_id(args["project_id"])
        r = await self._client.get(f"/projects/{pid}")  # type: ignore[union-attr]
        r.raise_for_status()
        p = r.json()
        return (
            f"Проект: {p['path_with_namespace']}\n"
            f"ID: {p['id']}\n"
            f"Описание: {p.get('description') or '—'}\n"
            f"Default branch: {p.get('default_branch', '—')}\n"
            f"Видимость: {p.get('visibility', '—')}\n"
            f"Stars: {p.get('star_count', 0)}, Forks: {p.get('forks_count', 0)}\n"
            f"Last activity: {p.get('last_activity_at', '—')}\n"
            f"URL: {p.get('web_url', '—')}"
        )

    async def _list_issues(self, args: dict) -> str:
        pid = _encode_id(args["project_id"])
        params: dict = {
            "state": args.get("state", "opened"),
            "per_page": args.get("limit", 20),
        }
        if args.get("search"):
            params["search"] = args["search"]
        if args.get("labels"):
            params["labels"] = args["labels"]
        r = await self._client.get(f"/projects/{pid}/issues", params=params)  # type: ignore[union-attr]
        r.raise_for_status()
        issues = r.json()
        rows = [
            f"- [#{i['iid']}] {i['title']} ({i['state']}) — {i.get('web_url', '')}"
            for i in issues
        ]
        return "\n".join(rows) if rows else "Issues не найдены"

    async def _list_merge_requests(self, args: dict) -> str:
        pid = _encode_id(args["project_id"])
        params: dict = {
            "state": args.get("state", "opened"),
            "per_page": args.get("limit", 20),
        }
        if args.get("search"):
            params["search"] = args["search"]
        r = await self._client.get(f"/projects/{pid}/merge_requests", params=params)  # type: ignore[union-attr]
        r.raise_for_status()
        mrs = r.json()
        rows = [
            f"- [!{m['iid']}] {m['title']} ({m['state']}) "
            f"{m.get('source_branch')} → {m.get('target_branch')} — {m.get('web_url', '')}"
            for m in mrs
        ]
        return "\n".join(rows) if rows else "Merge request-ы не найдены"

    async def _list_pipelines(self, args: dict) -> str:
        pid = _encode_id(args["project_id"])
        params: dict = {"per_page": args.get("limit", 10)}
        if args.get("status") and args["status"] != "all":
            params["status"] = args["status"]
        r = await self._client.get(f"/projects/{pid}/pipelines", params=params)  # type: ignore[union-attr]
        r.raise_for_status()
        pipelines = r.json()
        rows = [
            f"- [#{p['id']}] {p['status']} — ветка: {p.get('ref', '?')} — {p.get('web_url', '')}"
            for p in pipelines
        ]
        return "\n".join(rows) if rows else "Пайплайны не найдены"

    async def _list_commits(self, args: dict) -> str:
        pid = _encode_id(args["project_id"])
        params: dict = {"per_page": args.get("limit", 20)}
        if args.get("branch"):
            params["ref_name"] = args["branch"]
        r = await self._client.get(f"/projects/{pid}/repository/commits", params=params)  # type: ignore[union-attr]
        r.raise_for_status()
        commits = r.json()
        rows = [
            f"- [{c['short_id']}] {c['title']} — {c.get('author_name', '?')} ({c.get('committed_date', '')[:10]})"
            for c in commits
        ]
        return "\n".join(rows) if rows else "Коммиты не найдены"

    async def _get_file(self, args: dict) -> str:
        pid = _encode_id(args["project_id"])
        file_path = args["file_path"].lstrip("/")
        ref = args.get("ref") or "main"
        target_line = args.get("line")

        # Нормализуем путь из стектрейса: убираем /var/www/html/ и app/ префиксы
        for prefix in ("/var/www/html/", "/app/", "app/"):
            if file_path.startswith(prefix):
                file_path = file_path[len(prefix):]
                break

        encoded_path = quote(file_path, safe="")
        r = await self._client.get(  # type: ignore[union-attr]
            f"/projects/{pid}/repository/files/{encoded_path}/raw",
            params={"ref": ref},
        )

        if r.status_code == 404:
            # Попробуем другую ветку
            for fallback in ("master", "develop", "HEAD"):
                r = await self._client.get(  # type: ignore[union-attr]
                    f"/projects/{pid}/repository/files/{encoded_path}/raw",
                    params={"ref": fallback},
                )
                if r.status_code == 200:
                    ref = fallback
                    break

        if r.status_code == 404:
            return f"Файл не найден: {file_path} (проверь project_id и ref)"
        r.raise_for_status()

        content = r.text
        lines = content.splitlines()
        total = len(lines)

        if target_line:
            # Показываем контекст ±25 строк вокруг нужной строки
            ctx = 25
            start = max(0, target_line - ctx - 1)
            end = min(total, target_line + ctx)
            snippet = lines[start:end]
            numbered = []
            for i, ln in enumerate(snippet, start=start + 1):
                marker = ">>> " if i == target_line else "    "
                numbered.append(f"{marker}{i:4d} | {ln}")
            header = f"Файл: {file_path} (ветка: {ref}, строки {start+1}–{end} из {total})\n"
            return header + "\n".join(numbered)
        else:
            # Без указания строки — первые 100 строк
            MAX_LINES = 100
            snippet = lines[:MAX_LINES]
            numbered = [f"{i+1:4d} | {ln}" for i, ln in enumerate(snippet)]
            header = f"Файл: {file_path} (ветка: {ref}, первые {min(MAX_LINES, total)} из {total} строк)\n"
            suffix = f"\n... ещё {total - MAX_LINES} строк. Укажи параметр line для просмотра нужного места." if total > MAX_LINES else ""
            return header + "\n".join(numbered) + suffix


def _encode_id(project_id: str | int) -> str:
    """Числовой ID оставляем как есть, путь вида namespace/project кодируем для URL."""
    s = str(project_id)
    return s if s.isdigit() else quote(s, safe="")
