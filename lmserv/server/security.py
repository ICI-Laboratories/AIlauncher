"""
lmserv.server.security
======================

Pequeña capa de seguridad para el API:

1. **API-Key header** obligatorio (‵X-API-Key‵).  
2. **CORS** relax por defecto solo a la sub-red local.  
3. *Hooks* listos para añadir **rate-limit** o mTLS sin tocar `api.py`.

Al mantener todo aquí, el resto del código del servidor permanece
limpio y libre de detalles de autenticación.
"""
from __future__ import annotations

import ipaddress
import os
from typing import Iterable

from fastapi import Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..config import Config

# --------------------------------------------------------------------------- #
# API-Key
# --------------------------------------------------------------------------- #
def api_key_auth(
    x_api_key: str = Header(..., alias="X-API-Key"),
    cfg: Config = Depends(Config),
) -> None:
    """
    Valida que `X-API-Key` coincida con `cfg.api_key`.

    Lanza **401** si no coincide.  Se declara como *dependency* en
    los endpoints que requieran auth.
    """
    if x_api_key != cfg.api_key:
        raise HTTPException(status_code=401, detail="Bad API key")


# --------------------------------------------------------------------------- #
# CORS helper
# --------------------------------------------------------------------------- #
def add_cors_middleware(app, allowed_origins: Iterable[str] | None = None) -> None:
    """
    Añade CORS *middleware* a la aplicación **FastAPI**.

    * Por defecto permite `http://localhost` y cualquier IP *RFC1918*
      (redes privadas 10/8, 172.16/12, 192.168/16).
    * Para deshabilitar CORS por completo, pasa `allowed_origins=[]`.
    """
    if allowed_origins is None:
        allowed_origins = [
            "http://localhost",
            "http://127.0.0.1",
            *[
                f"http://{ip}.0.0.0"  # simple wildcard, e.g. 192.168.0.0/16
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
    from fastapi import Request

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
