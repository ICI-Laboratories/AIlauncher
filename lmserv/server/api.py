"""
lmserv.server.api
=================
FastAPI gateway que publica:

* **POST /chat** – Genera texto y hace _streaming_ token-a-token
* **GET /health** – “pong” + versión + workers disponibles
* **GET /** – Landing mínima para humanos

Todo I/O pesado (llama-cli) se delega a `WorkerPool`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager  # <-- AÑADIDO
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import Config
from .pool import WorkerPool
from .security import api_key_auth

# --- Definición de variables globales para el ciclo de vida ---
_cfg: Config | None = None
_pool: WorkerPool | None = None

# --- CORREGIDO: Uso de lifespan en lugar de on_event ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el inicio y apagado de la aplicación."""
    global _cfg, _pool
    # Código de inicio
    _cfg = Config()
    _pool = WorkerPool(_cfg)
    await _pool.start()
    
    yield  # La aplicación se ejecuta aquí
    
    # Código de apagado
    if _pool:
        await _pool.shutdown()

# ------------------------------------------------------------------------------
# Instancia de FastAPI con el nuevo lifespan
# ------------------------------------------------------------------------------
app = FastAPI(
    title="LMServ – mini-LM Studio",
    version=Config().__version__ if hasattr(Config, "__version__") else "dev",
    lifespan=lifespan,  # <-- AÑADIDO
)


# ------------------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------------------
class ChatRequest(BaseModel):
    prompt: str = Field(..., description="Texto del usuario")
    max_tokens: int | None = Field(None, ge=1, description="Sobrescribe límite")


# --- ELIMINADO: Los antiguos manejadores de eventos ya no son necesarios ---
# @app.on_event("startup") ...
# @app.on_event("shutdown") ...


# ------------------------------------------------------------------------------
# Health-check
# ------------------------------------------------------------------------------
@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    """Retorna “ok” + número de workers libres."""
    free = _pool.free.qsize() if _pool else 0
    return f"ok – workers idle: {free}"


# ------------------------------------------------------------------------------
# Chat endpoint
# ------------------------------------------------------------------------------
@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(req: ChatRequest) -> StreamingResponse:
    """Genera texto via `llama-cli` y hace *streaming* progresivo."""
    if not _pool:
        raise HTTPException(status_code=503, detail="Worker pool not ready")

    worker = await _pool.acquire()

    async def _stream() -> AsyncIterator[str]:
        try:
            async for token in worker.infer(req.prompt):
                yield token
        finally:
            await _pool.release(worker)

    return StreamingResponse(_stream(), media_type="text/plain")


# ------------------------------------------------------------------------------
# Root friendly HTML
# ------------------------------------------------------------------------------
@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root() -> str:
    return (
        "LMServ – mini-LM Studio 🌸\n"
        "POST /chat   with JSON {prompt, max_tokens}\n"
        "GET /health  for status\n"
    )