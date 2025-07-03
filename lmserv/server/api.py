from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import Config
from .pool import WorkerPool
from .security import api_key_auth

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el inicio y apagado de los recursos de la aplicación."""
    app.state.config = Config()
    app.state.pool = WorkerPool(app.state.config)
    await app.state.pool.start()
    yield
    if app.state.pool:
        await app.state.pool.shutdown()

app = FastAPI(
    title="LMServ – mini-LM Studio",
    version="1.0.0",
    lifespan=lifespan,
)

class ChatRequest(BaseModel):
    prompt: str = Field(..., description="Texto del usuario para la inferencia.")
    system_prompt: Optional[str] = Field(None, description="Instrucción a nivel de sistema para el modelo.")
    max_tokens: Optional[int] = Field(None, ge=1, description="Límite máximo de tokens a generar.")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Controla la aleatoriedad. Más alto = más creativo.")
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Muestreo Nucleus.")
    repeat_penalty: Optional[float] = Field(None, ge=0.0, description="Penaliza la repetición de tokens.")

@app.get("/health", response_class=PlainTextResponse)
async def health(request: Request) -> str:
    pool: WorkerPool = request.app.state.pool
    return f"ok – workers idle: {pool.free.qsize()}"

@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(request: Request, req: ChatRequest) -> StreamingResponse:
    """Genera texto via `llama-cli` con parámetros personalizables."""
    pool: WorkerPool = request.app.state.pool
    worker = await pool.acquire()

    async def _stream() -> AsyncIterator[str]:
        try:
            # Pass all parameters from the request to the worker
            async for token in worker.infer(
                prompt=req.prompt,
                system_prompt=req.system_prompt,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                top_p=req.top_p,
                repeat_penalty=req.repeat_penalty,
            ):
                yield token
        finally:
            await pool.release(worker)

    return StreamingResponse(_stream(), media_type="text/plain; charset=utf-8")

@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root() -> str:
    return "LMServ is running."