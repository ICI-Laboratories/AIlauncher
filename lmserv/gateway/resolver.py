from __future__ import annotations

from dataclasses import dataclass

from .catalog import GatewayCatalog
from .models import ModelRoute


@dataclass(slots=True, frozen=True)
class CapabilityRequirements:
    structured_output: bool = False
    json_mode: bool = False
    tools: bool = False

    def missing_from(self, route: ModelRoute) -> list[str]:
        missing: list[str] = []
        if self.structured_output and not route.capabilities.structured_output:
            missing.append("structured_output")
        if self.json_mode and not (
            route.capabilities.json_mode or route.capabilities.structured_output
        ):
            missing.append("json_mode")
        if self.tools and not route.capabilities.tools:
            missing.append("tools")
        return missing


@dataclass(slots=True, frozen=True)
class RouteSelection:
    primary_route: ModelRoute
    selected_route: ModelRoute
    reason: str | None = None


class CapabilityResolver:
    def __init__(self, catalog: GatewayCatalog) -> None:
        self._catalog = catalog

    def resolve(
        self,
        requested_model: str | None,
        requirements: CapabilityRequirements,
    ) -> RouteSelection:
        primary = self._catalog.resolve(requested_model)
        missing = requirements.missing_from(primary)
        if not missing:
            return RouteSelection(primary_route=primary, selected_route=primary)

        candidates = [
            route
            for route in self._catalog.enabled_routes()
            if route.name != primary.name and not requirements.missing_from(route)
        ]
        if not candidates:
            raise LookupError(
                f"El modelo '{primary.name}' no cubre {', '.join(missing)} y no existe "
                "un fallback compatible en el catalogo."
            )

        selected = sorted(
            candidates,
            key=lambda route: (route.priority, route.name),
            reverse=True,
        )[0]
        reason = (
            f"Ruta automatica hacia '{selected.name}' porque '{primary.name}' "
            f"no anuncia {', '.join(missing)}."
        )
        return RouteSelection(primary_route=primary, selected_route=selected, reason=reason)
