from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from ..config import Config
from ..gateway.backends.common import render_openai_content
from ..gateway.models import RoutedChatResult


def _sha256_text(text: str) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    remaining = len(text) - max_chars
    return f"{text[:max_chars]}...[truncated {remaining} chars]"


def _tool_name(tool: dict[str, Any]) -> str | None:
    if "name" in tool:
        return str(tool["name"])
    function_payload = tool.get("function") or {}
    if isinstance(function_payload, dict) and function_payload.get("name"):
        return str(function_payload["name"])
    return None


class RequestAuditLogger:
    def __init__(self, cfg: Config) -> None:
        self.enabled = bool(cfg.request_log_path)
        self._include_content = cfg.request_log_include_content
        self._max_chars = max(int(cfg.request_log_max_chars or 12000), 256)
        self._path = Path(cfg.request_log_path) if cfg.request_log_path else None
        self._lock = Lock()

        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def log_chat_event(
        self,
        *,
        endpoint: str,
        client_ip: str | None,
        user_agent: str | None,
        correlation_id: str | None,
        idempotency_key: str | None,
        requested_model: str | None,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
        stream_requested: bool,
        routed_result: RoutedChatResult | None,
        response_payload: dict[str, Any] | None,
        latency_ms: float,
        error: Exception | None = None,
    ) -> None:
        if not self.enabled:
            return

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "chat_request",
            "endpoint": endpoint,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "requested_model": requested_model,
            "primary_model": routed_result.primary_route.name if routed_result else None,
            "selected_model": routed_result.selected_route.name if routed_result else None,
            "routing_reason": routed_result.routing_reason if routed_result else None,
            "response_id": response_payload.get("id") if response_payload else None,
            "stream_requested": stream_requested,
            "latency_ms": round(latency_ms, 3),
            "request": {
                "messages": self._summarize_messages(messages),
                "response_format": response_format,
                "tools_count": len(tools or []),
                "tool_names": [name for name in (_tool_name(tool) for tool in (tools or [])) if name],
            },
            "response": self._summarize_response(routed_result, response_payload),
            "error": self._normalize_error(error),
        }
        self._write(entry)

    def _summarize_messages(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        combined_parts: list[str] = []

        for message in messages:
            role = str(message.get("role", "user"))
            content = render_openai_content(message.get("content"))
            item = {
                "role": role,
                "name": message.get("name"),
                "tool_call_id": message.get("tool_call_id"),
                "chars": len(content),
                "sha256": _sha256_text(content),
            }
            if self._include_content:
                item["content"] = _truncate(content, self._max_chars)
            items.append(item)
            combined_parts.append(f"{role}: {content}")

        combined = "\n".join(combined_parts)
        payload: dict[str, Any] = {
            "count": len(items),
            "total_chars": sum(item["chars"] for item in items),
            "sha256": _sha256_text(combined),
        }
        if self._include_content:
            payload["items"] = items
        else:
            payload["items"] = [{k: v for k, v in item.items() if k != "content"} for item in items]
        return payload

    def _summarize_response(
        self,
        routed_result: RoutedChatResult | None,
        response_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not routed_result and not response_payload:
            return None

        content = routed_result.result.content if routed_result else ""
        tool_calls = routed_result.result.tool_calls if routed_result else None
        usage = routed_result.result.usage if routed_result else (response_payload or {}).get("usage")

        payload: dict[str, Any] = {
            "finish_reason": routed_result.result.finish_reason if routed_result else None,
            "chars": len(content),
            "sha256": _sha256_text(content),
            "usage": usage,
            "tool_calls_count": len(tool_calls or []),
        }
        if self._include_content:
            payload["content"] = _truncate(content, self._max_chars)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    def _normalize_error(self, error: Exception | None) -> dict[str, Any] | None:
        if not error:
            return None

        detail = getattr(error, "detail", None)
        return {
            "type": error.__class__.__name__,
            "message": str(detail if detail is not None else error),
        }

    def _write(self, payload: dict[str, Any]) -> None:
        if not self._path:
            return

        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
