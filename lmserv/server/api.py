# lmserv/server/api.py
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

import json

# --- Tool Definitions ---
def get_weather(city: str, unit: str = "celsius") -> str:
    """Placeholder for a real weather tool."""
    if "tokyo" in city.lower():
        return json.dumps({"temperature": "15", "unit": unit})
    elif "san francisco" in city.lower():
        return json.dumps({"temperature": "12", "unit": unit})
    else:
        return json.dumps({"temperature": "20", "unit": unit})

TOOLS = {
    "get_weather": get_weather,
}

@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(request: Request, req: ChatRequest) -> PlainTextResponse:
    """
    Genera una respuesta usando un modelo de lenguaje con un posible bucle de razonamiento y uso de herramientas.
    """
    pool: WorkerPool = request.app.state.pool
    worker = await pool.acquire()

    conversation_history = [f"User: {req.prompt}"]
    max_turns = 5

    try:
        for turn in range(max_turns):
            # Construye el prompt para esta vuelta
            prompt = "\n".join(conversation_history)

            # Obtiene la respuesta completa del modelo
            model_output = ""
            async for token in worker.infer(prompt=prompt):
                model_output += token

            try:
                # Intenta parsear la respuesta como JSON
                data = json.loads(model_output)
                thought = data.get("thought", "")

                if "tool_call" in data:
                    tool_call = data["tool_call"]
                    tool_name = tool_call.get("name")
                    tool_args = tool_call.get("arguments", {})

                    if tool_name in TOOLS:
                        # Ejecuta la herramienta
                        tool_function = TOOLS[tool_name]
                        tool_result = tool_function(**tool_args)

                        # Añade el resultado a la conversación
                        conversation_history.append(f"Tool Result: {tool_result}")
                        continue # Siguiente vuelta del bucle
                    else:
                        # Herramienta no encontrada
                        conversation_history.append("Tool Result: Error - tool not found.")
                        continue
                else:
                    # No hay llamada a herramienta, la conversación termina
                    return PlainTextResponse(f"Final Answer:\n{thought}")

            except json.JSONDecodeError:
                # La respuesta no fue un JSON válido, considérala la respuesta final
                return PlainTextResponse(f"Final Answer (Invalid JSON):\n{model_output}")

        return PlainTextResponse("Error: El modelo excedió el número máximo de iteraciones.")

    finally:
        await pool.release(worker)

@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root() -> str:
    return "LMServ is running."