from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from .models import ModelCapabilities, ModelRoute


def _default_capabilities_for_backend(backend: str) -> ModelCapabilities:
    normalized = backend.lower()
    if normalized == "ollama":
        return ModelCapabilities(
            structured_output=True,
            json_mode=True,
            tools=True,
            streaming=True,
        )
    return ModelCapabilities(streaming=True)


def _derive_route_name(model_identifier: str) -> str:
    model_path = Path(model_identifier)
    if model_path.suffix:
        return model_path.stem
    return model_identifier.replace("/", "_").replace(":", "_")


def _load_route(item: dict, cfg: Config) -> ModelRoute:
    backend = str(item.get("backend", cfg.backend)).lower()
    target = item.get("target") or item.get("model")
    if not target:
        raise ValueError(f"Cada entrada del catalogo requiere 'target' o 'model': {item!r}")

    default_capabilities = _default_capabilities_for_backend(backend)
    raw_capabilities = item.get("capabilities", {})
    capabilities = ModelCapabilities(
        structured_output=raw_capabilities.get(
            "structured_output",
            default_capabilities.structured_output,
        ),
        json_mode=raw_capabilities.get("json_mode", default_capabilities.json_mode),
        tools=raw_capabilities.get("tools", default_capabilities.tools),
        streaming=raw_capabilities.get("streaming", default_capabilities.streaming),
        vision=raw_capabilities.get("vision", default_capabilities.vision),
    )

    settings = dict(item.get("settings", {}))
    if "base_url" in item:
        settings.setdefault("base_url", item["base_url"])
    if backend == "ollama":
        settings.setdefault("base_url", cfg.ollama_base_url)

    return ModelRoute(
        name=str(item["name"]),
        backend=backend,
        target=str(target),
        aliases=tuple(item.get("aliases", [])),
        priority=int(item.get("priority", 0)),
        enabled=bool(item.get("enabled", True)),
        workers=item.get("workers"),
        capabilities=capabilities,
        settings=settings,
    )


@dataclass(slots=True, frozen=True)
class GatewayCatalog:
    default_model: str
    routes: tuple[ModelRoute, ...]

    def resolve(self, name: str | None) -> ModelRoute:
        lookup = name or self.default_model
        for route in self.routes:
            if route.enabled and route.matches(lookup):
                return route
        raise KeyError(f"Modelo no encontrado en el catalogo: {lookup}")

    def enabled_routes(self) -> tuple[ModelRoute, ...]:
        return tuple(route for route in self.routes if route.enabled)


def load_catalog(cfg: Config) -> GatewayCatalog:
    if cfg.catalog_path:
        path = Path(cfg.catalog_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        routes = tuple(_load_route(item, cfg) for item in data.get("models", []))
        if not routes:
            raise ValueError(f"El catalogo {path} no contiene modelos.")

        default_model = str(data.get("default_model") or routes[0].name)
        catalog = GatewayCatalog(default_model=default_model, routes=routes)
        catalog.resolve(default_model)
        return catalog

    default_capabilities = _default_capabilities_for_backend(cfg.backend)
    route_name = cfg.default_model_alias or _derive_route_name(cfg.model)
    settings: dict[str, str] = {}
    if cfg.backend == "ollama":
        settings["base_url"] = cfg.ollama_base_url

    return GatewayCatalog(
        default_model=route_name,
        routes=(
            ModelRoute(
                name=route_name,
                backend=cfg.backend.lower(),
                target=cfg.model,
                workers=cfg.workers,
                capabilities=default_capabilities,
                settings=settings,
            ),
        ),
    )
