"""Абстрактный базовый класс для MCP-коннекторов."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AsyncExitStack


class BaseMCPConnector(ABC):
    """
    Базовый класс для всех MCP-коннекторов.

    Каждый коннектор инкапсулирует логику подключения к одному сервису.
    Новый коннектор (GitLab, Jira и т.д.) — это новый класс-наследник.

    Жизненный цикл:
      1. MCPConnector проверяет is_configured — пропускает некonfigured коннекторы.
      2. Вызывает connect(stack) — коннектор регистрирует ресурсы в общем стеке.
      3. Через tools/tool_names получает список инструментов.
      4. Маршрутизирует вызовы через call_tool().
    """

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True если коннектор имеет достаточно конфига для подключения."""
        ...

    @abstractmethod
    async def connect(self, stack: AsyncExitStack) -> None:
        """Установить соединение и зарегистрировать ресурсы в общем стеке."""
        ...

    @property
    @abstractmethod
    def tools(self) -> list[dict]:
        """Список схем инструментов, доступных через этот коннектор."""
        ...

    @property
    def tool_names(self) -> list[str]:
        return [t["name"] for t in self.tools]

    @abstractmethod
    async def call_tool(self, name: str, args: dict) -> str:
        """Вызвать инструмент и вернуть текстовый результат."""
        ...
