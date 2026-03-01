"""MCP коннекторы — один файл на сервис.

Чтобы добавить новый коннектор (GitLab, Jira и т.д.):
  1. Создать connectors/gitlab.py с классом GitLabConnector(BaseMCPConnector).
  2. Добавить GitLabConfig в config.py.
  3. Добавить коннектор в MCPConnector.from_config().
"""

from .base import BaseMCPConnector
from .graylog import GraylogConnector
from .postgres import PostgresConnector

__all__ = [
    "BaseMCPConnector",
    "GraylogConnector",
    "PostgresConnector",
]
