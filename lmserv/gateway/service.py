from __future__ import annotations

import asyncio
from typing import Any

from ..config import Config
from .catalog import GatewayCatalog
from .models import GatewayChatRequest, RoutedChatResult
from .resolver import CapabilityRequirements, CapabilityResolver
from .runtime import BackendRuntime


class GatewayService:
    def __init__(self, cfg: Config, catalog: GatewayCatalog) -> None:
        self._cfg = cfg
        self._catalog = catalog
        self._resolver = CapabilityResolver(catalog)
        self._runtimes: dict[str, BackendRuntime] = {}

    async def start(self) -> None:
        for route in self._catalog.enabled_routes():
            self._runtimes[route.name] = self._build_runtime(route)
        await asyncio.gather(*(runtime.start() for runtime in self._runtimes.values()))

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(runtime.shutdown() for runtime in self._runtimes.values()),
            return_exceptions=True,
        )
        self._runtimes.clear()

    def models_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for route in self._catalog.enabled_routes():
            payload.append(
                {
                    "id": route.name,
                    "object": "model",
                    "created": 0,
                    "owned_by": route.backend,
                    "aliases": list(route.aliases),
                    "capabilities": {
                        "structured_output": route.capabilities.structured_output,
                        "json_mode": route.capabilities.json_mode,
                        "tools": route.capabilities.tools,
                        "streaming": route.capabilities.streaming,
                        "vision": route.capabilities.vision,
                    },
                    "target": route.target,
                }
            )
        return payload

    def health_payload(self) -> dict[str, Any]:
        routes: dict[str, Any] = {}
        for name, runtime in self._runtimes.items():
            routes[name] = runtime.describe()
        return {
            "status": "ok",
            "default_model": self._catalog.default_model,
            "routes": routes,
        }

    async def chat(self, request: GatewayChatRequest) -> RoutedChatResult:
        requirements = self._requirements_from_request(request)
        selection = self._resolver.resolve(request.model, requirements)
        runtime = self._runtimes[selection.selected_route.name]
        result = await runtime.chat(request)
        return RoutedChatResult(
            requested_model=request.model,
            primary_route=selection.primary_route,
            selected_route=selection.selected_route,
            routing_reason=selection.reason,
            result=result,
        )

    def _build_runtime(self, route):
        if route.backend == "llama_cpp":
            from .backends.llama_cpp import LlamaCppRuntime

            return LlamaCppRuntime(route, self._cfg)
        if route.backend == "ollama":
            from .backends.ollama import OllamaRuntime

            return OllamaRuntime(route, self._cfg)
        raise ValueError(f"Backend no soportado: {route.backend}")

    def _requirements_from_request(
        self,
        request: GatewayChatRequest,
    ) -> CapabilityRequirements:
        response_format = request.response_format or {}
        format_type = response_format.get("type")
        return CapabilityRequirements(
            structured_output=format_type == "json_schema",
            json_mode=format_type == "json_object",
            tools=bool(request.tools),
        )
