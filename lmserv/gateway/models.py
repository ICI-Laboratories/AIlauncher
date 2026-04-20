from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ModelCapabilities:
    structured_output: bool = False
    json_mode: bool = False
    tools: bool = False
    streaming: bool = True
    vision: bool = False


@dataclass(slots=True, frozen=True)
class ModelRoute:
    name: str
    backend: str
    target: str
    aliases: tuple[str, ...] = ()
    priority: int = 0
    enabled: bool = True
    workers: int | None = None
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    settings: dict[str, Any] = field(default_factory=dict)

    def matches(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        return candidate == self.name or candidate in self.aliases


@dataclass(slots=True)
class GatewayChatRequest:
    model: str | None
    messages: list[dict[str, Any]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    response_format: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None


@dataclass(slots=True)
class RuntimeChatResult:
    content: str
    finish_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RoutedChatResult:
    requested_model: str | None
    primary_route: ModelRoute
    selected_route: ModelRoute
    routing_reason: str | None
    result: RuntimeChatResult
