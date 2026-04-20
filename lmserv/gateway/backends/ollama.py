from __future__ import annotations

from typing import Any

from ...config import Config
from ..models import GatewayChatRequest, ModelRoute, RuntimeChatResult
from ..runtime import BackendRuntime
from .common import to_ollama_messages


def _normalize_ollama_chat_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/api"):
        return f"{normalized}/chat"
    return f"{normalized}/api/chat"


def _response_format_to_ollama_format(response_format: dict[str, Any] | None) -> Any:
    if not response_format:
        return None

    format_type = response_format.get("type")
    if format_type == "json_object":
        return "json"
    if format_type == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema")
        return schema or None
    return None


class OllamaRuntime(BackendRuntime):
    def __init__(self, route: ModelRoute, cfg: Config) -> None:
        super().__init__(route)
        base_url = str(route.settings.get("base_url", cfg.ollama_base_url))
        self._chat_url = _normalize_ollama_chat_url(base_url)
        self._timeout = cfg.request_timeout_s
        self._client: Any | None = None

    async def start(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat(self, request: GatewayChatRequest) -> RuntimeChatResult:
        if not self._client:
            raise RuntimeError("OllamaRuntime no ha sido inicializado.")

        payload: dict[str, Any] = {
            "model": self.route.target,
            "messages": to_ollama_messages(request.messages),
            "stream": False,
        }

        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.top_p is not None:
            options["top_p"] = request.top_p
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if options:
            payload["options"] = options

        format_value = _response_format_to_ollama_format(request.response_format)
        if format_value is not None:
            payload["format"] = format_value

        if request.tools:
            payload["tools"] = request.tools

        response = await self._client.post(self._chat_url, json=payload)
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)

        return RuntimeChatResult(
            content=str(message.get("content", "")),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            tool_calls=message.get("tool_calls") or None,
            raw=data,
        )
