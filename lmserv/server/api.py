from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import Config
from .pool import WorkerPool
from .security import api_key_auth

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el inicio y apagado de los recursos de la aplicación."""
    # Attach config and pool to the application's state
    app.state.config = Config()
    app.state.pool = WorkerPool(app.state.config)
    await app.state.pool.start()
    
    yield  # La aplicación está disponible aquí
    
    # Código que se ejecuta al apagar
    if app.state.pool:
        await app.state.pool.shutdown()

app = FastAPI(
    title="LMServ – mini-LM Studio",
    version=Config().__version__ if hasattr(Config, "__version__") else "dev",
    lifespan=lifespan,
)

class ChatRequest(BaseModel):
    prompt: str = Field(..., description="Texto del usuario")
    max_tokens: int | None = Field(None, ge=1, description="Sobrescribe límite")

@app.get("/health", response_class=PlainTextResponse)
async def health(request: Request) -> str:
    """Retorna “ok” + número de workers libres."""
    pool: WorkerPool = request.app.state.pool
    free = pool.free.qsize() if pool else 0
    return f"ok – workers idle: {free}"

@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(request: Request, req: ChatRequest) -> StreamingResponse:
    """Genera texto via `llama-cli` y hace *streaming* progresivo."""
    pool: WorkerPool = request.app.state.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Worker pool not ready")

    worker = await pool.acquire()

    async def _stream() -> AsyncIterator[str]:
        try:
            async for token in worker.infer(req.prompt):
                yield token
        finally:
            await pool.release(worker)

    return StreamingResponse(_stream(), media_type="text/plain")

@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root() -> str:
    return (
        "LMServ – mini-LM Studio 🌸\n"
        "POST /chat   with JSON {prompt, max_tokens}\n"
        "GET /health  for status\n"
    )