from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import GatewayChatRequest, ModelRoute, RuntimeChatResult


class BackendRuntime(ABC):
    def __init__(self, route: ModelRoute) -> None:
        self.route = route

    @abstractmethod
    async def start(self) -> None:
        """Inicializa recursos persistentes del backend."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Libera recursos persistentes del backend."""

    @abstractmethod
    async def chat(self, request: GatewayChatRequest) -> RuntimeChatResult:
        """Ejecuta una inferencia conversacional."""

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.route.backend,
            "target": self.route.target,
            "ready": True,
        }
