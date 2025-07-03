"""
Pruebas de la API FastAPI (/health y /chat) usando httpx + ASGITransport.
La fixture global convierte el worker real en uno “mock” que responde
con los tokens «Hola», «🙂».
"""
from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from lmserv.server.api import app

_HEADERS = {"X-API-Key": "changeme"}


# ════════════════════════════════════════════════════════════════════════════
# /health debe responder “ok – workers idle: N”
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_health_ok() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(base_url="http://test", transport=transport) as client:
        r = await client.get("/health", headers=_HEADERS)
        assert r.status_code == 200
        assert r.text.startswith("ok")


# ════════════════════════════════════════════════════════════════════════════
# /chat hace streaming token-a-token
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_chat_stream() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(base_url="http://test", transport=transport) as client:
        r = await client.post(
            "/chat",
            headers={**_HEADERS, "Content-Type": "application/json"},
            json={"prompt": "¿Quién eres?", "max_tokens": 16},
        )
        assert r.status_code == 200
        # Concatenar el stream para verificar contenido
        body = ""
        async for chunk in r.aiter_text():
            body += chunk
        assert "Hola" in body and "🙂" in body
