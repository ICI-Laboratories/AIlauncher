"""
lmserv.server.api
=================
FastAPI gateway que publica:

* **POST /chat**    – Genera texto y hace _streaming_ token-a-token  
* **GET /health**  – “pong” + versión + workers disponibles  
* **GET /**        – Landing mínima para humanos

Todo I/O pesado (llama-cli) se delega a `WorkerPool`.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import Config
from .pool import WorkerPool
from .security import api_key_auth

# ------------------------------------------------------------------------------
# FastAPI instance
# ------------------------------------------------------------------------------
app = FastAPI(
    title="LMServ – mini-LM Studio",
    version=Config().__version__ if hasattr(Config, "__version__") else "dev",
)

_cfg: Config | None = None          # Cargaremos en startup
_pool: WorkerPool | None = None     # Idem


# ------------------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------------------
class ChatRequest(BaseModel):
    prompt: str = Field(..., description="Texto del usuario")
    max_tokens: int | None = Field(None, ge=1, description="Sobrescribe límite")


# ------------------------------------------------------------------------------
# Start-up / shut-down
# ------------------------------------------------------------------------------
@app.on_event("startup")
async def _startup() -> None:
    global _cfg, _pool
    _cfg = Config()
    _pool = WorkerPool(_cfg)
    await _pool.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _pool:  # pragma: no cover
        await _pool.shutdown()


# ------------------------------------------------------------------------------
# Health-check
# ------------------------------------------------------------------------------
@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:  # noqa: D401
    """
    Retorna “ok” + número de workers libres.
    """
    free = _pool.free.qsize() if _pool else 0
    return f"ok – workers idle: {free}"


# ------------------------------------------------------------------------------
# Chat endpoint
# ------------------------------------------------------------------------------
@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(req: ChatRequest) -> StreamingResponse:  # noqa: D401
    """
    Genera texto via `llama-cli` y hace *streaming* progresivo.
    """
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
def root() -> str:  # noqa: D401
    return (
        "LMServ – mini-LM Studio 🌸\n"
        "POST /chat   with JSON {prompt, max_tokens}\n"
        "GET /health  for status\n"
    )
