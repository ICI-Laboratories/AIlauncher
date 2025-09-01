# lmserv/server/api.py
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import Config
from .pool import WorkerPool
from .security import api_key_auth
from .tools import ToolManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el inicio y apagado de los recursos de la aplicación."""
    app.state.config = Config()
    app.state.pool = WorkerPool(app.state.config)
    if app.state.config.tools_path:
        app.state.tool_manager = ToolManager(app.state.config.tools_path)
    else:
        app.state.tool_manager = None
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

# --- Tool Implementations ---
def get_weather(city: str, unit: str = "celsius") -> str:
    """Placeholder for a real weather tool."""
    if "tokyo" in city.lower():
        return json.dumps({"temperature": "15", "unit": unit})
    elif "san francisco" in city.lower():
        return json.dumps({"temperature": "12", "unit": unit})
    else:
        return json.dumps({"temperature": "20", "unit": unit})

TOOL_REGISTRY = {
    "get_weather": get_weather,
}

@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(request: Request, req: ChatRequest) -> PlainTextResponse:
    """
    Genera una respuesta usando un modelo de lenguaje con un posible bucle de razonamiento y uso de herramientas.
    """
    pool: WorkerPool = request.app.state.pool
    tool_manager: ToolManager | None = request.app.state.tool_manager
    tools = tool_manager.tools if tool_manager else {}
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

                    if tool_name in tools and tool_name in TOOL_REGISTRY:
                        # Execute the tool
                        tool_function = TOOL_REGISTRY[tool_name]
                        try:
                            tool_result = tool_function(**tool_args)
                            conversation_history.append(f"Tool Result: {tool_result}")
                        except Exception as e:
                            conversation_history.append(f"Tool Result: Error executing tool '{tool_name}': {e}")
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

# --- Endpoints for Tool Management ---

class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]

def get_tool_manager(request: Request) -> ToolManager:
    """Dependency to get the tool manager or raise an exception if not available."""
    if not request.app.state.tool_manager:
        raise HTTPException(status_code=400, detail="Tool management is not enabled. Start the server with --tools option.")
    return request.app.state.tool_manager

@app.get("/tools", response_model=List[ToolSchema], dependencies=[Depends(api_key_auth)])
async def list_tools(tm: ToolManager = Depends(get_tool_manager)):
    """List all available tools."""
    return tm.get_all()

@app.post("/tools", response_model=ToolSchema, status_code=201, dependencies=[Depends(api_key_auth)])
async def create_tool(tool: ToolSchema, tm: ToolManager = Depends(get_tool_manager)):
    """Create a new tool."""
    try:
        created_tool = tm.add(tool.model_dump())
        return created_tool
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.get("/tools/{tool_name}", response_model=ToolSchema, dependencies=[Depends(api_key_auth)])
async def get_tool(tool_name: str, tm: ToolManager = Depends(get_tool_manager)):
    """Retrieve a single tool by name."""
    tool = tm.get_one(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return tool

@app.put("/tools/{tool_name}", response_model=ToolSchema, dependencies=[Depends(api_key_auth)])
async def update_tool(tool_name: str, tool: ToolSchema, tm: ToolManager = Depends(get_tool_manager)):
    """Update an existing tool."""
    updated_tool = tm.update(tool_name, tool.model_dump())
    if not updated_tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return updated_tool

@app.delete("/tools/{tool_name}", status_code=204, dependencies=[Depends(api_key_auth)])
async def delete_tool(tool_name: str, tm: ToolManager = Depends(get_tool_manager)):
    """Delete a tool by name."""
    if not tm.delete(tool_name):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return None

@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root() -> str:
    return "LMServ is running."