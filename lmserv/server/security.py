# lmserv/server/security.py
from __future__ import annotations

import ipaddress
import os
from typing import Iterable

from fastapi import Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# No need to import CFG or config_instance anymore

# --------------------------------------------------------------------------- #
# API-Key
# --------------------------------------------------------------------------- #
def api_key_auth(request: Request, x_api_key: str = Header(..., alias="X-API-Key")):
    """
    Valida que `X-API-Key` coincida con la configuración en app.state.
    """
    # Access the config safely from the application state
    if not hasattr(request.app.state, "config") or not request.app.state.config:
         raise HTTPException(status_code=503, detail="Server is starting up, please wait.")

    if x_api_key != request.app.state.config.api_key:
        raise HTTPException(status_code=401, detail="Bad API key")


# --------------------------------------------------------------------------- #
# CORS helper
# --------------------------------------------------------------------------- #
def add_cors_middleware(app, allowed_origins: Iterable[str] | None = None) -> None:
    if allowed_origins is None:
        allowed_origins = [
            "http://localhost",
            "http://127.0.0.1",
            *[
                f"http://{ip}.0.0.0"
                for ip in ("10", "172", "192")
            ],
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["*"],
    )

# --------------------------------------------------------------------------- #
# Rate-limit  (stub)
# --------------------------------------------------------------------------- #
RATE_LIMIT_QPS = float(os.getenv("RATE_LIMIT_QPS", "0"))  # 0 → deshabilitado

if RATE_LIMIT_QPS > 0:  # pragma: no cover  (habilitar según necesidad)
    from datetime import datetime, timedelta
    from collections import defaultdict
    from fastapi import Request, Depends

    _requests: dict[str, list[datetime]] = defaultdict(list)

    async def _rate_limiter(request: Request) -> None:  # noqa: D401
        key = request.headers.get("X-API-Key", "anon")
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=1)
        _requests[key] = [t for t in _requests[key] if t > window_start]
        if len(_requests[key]) >= RATE_LIMIT_QPS:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        _requests[key].append(now)

    def add_rate_limit_dependency(app) -> None:  # noqa: D401
        from fastapi.routing import APIRoute

        for route in app.routes:
            if isinstance(route, APIRoute):
                route.dependencies.append(Depends(_rate_limiter))
else:  # pragma: no cover
    def add_rate_limit_dependency(app) -> None:  # noqa: D401
        """No-op si RATE_LIMIT_QPS = 0."""
        return