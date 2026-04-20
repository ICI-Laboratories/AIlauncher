from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import Config
from ..gateway import GatewayChatRequest, GatewayService, load_catalog
from .security import api_key_auth
from .tools import ToolManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = Config()
    app.state.catalog = load_catalog(app.state.config)
    app.state.gateway = GatewayService(app.state.config, app.state.catalog)
    if app.state.config.tools_path:
        app.state.tool_manager = ToolManager(app.state.config.tools_path)
    else:
        app.state.tool_manager = None
    await app.state.gateway.start()
    yield
    if app.state.gateway:
        await app.state.gateway.shutdown()


app = FastAPI(
    title="LMLauncher Gateway",
    version="2.0.0",
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    prompt: str = Field(..., description="Texto del usuario para la inferencia.")
    system_prompt: Optional[str] = Field(None, description="Instruccion a nivel de sistema para el modelo.")
    max_tokens: Optional[int] = Field(None, ge=1, description="Limite maximo de tokens a generar.")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Controla la aleatoriedad.")
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Muestreo nucleus.")
    repeat_penalty: Optional[float] = Field(None, ge=0.0, description="Penaliza la repeticion de tokens.")


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class JsonSchemaPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")


class ResponseFormatPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    json_schema: Optional[JsonSchemaPayload] = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = None
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    stream: bool = False
    response_format: Optional[ResponseFormatPayload] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Any = None


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]


def _normalize_usage(raw_usage: Dict[str, Any] | None) -> Dict[str, int]:
    raw_usage = raw_usage or {}
    prompt_tokens = int(raw_usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(raw_usage.get("completion_tokens", 0) or 0)
    total_tokens = int(raw_usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _build_gateway_request(req: ChatCompletionRequest) -> GatewayChatRequest:
    return GatewayChatRequest(
        model=req.model,
        messages=[message.model_dump(exclude_none=True) for message in req.messages],
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        stream=req.stream,
        response_format=req.response_format.model_dump(exclude_none=True, by_alias=True) if req.response_format else None,
        tools=req.tools,
        tool_choice=req.tool_choice,
    )


def _build_openai_response(routed_result) -> Dict[str, Any]:
    created = int(time.time())
    message_payload: Dict[str, Any] = {
        "role": "assistant",
        "content": routed_result.result.content,
    }
    if routed_result.result.tool_calls:
        message_payload["tool_calls"] = routed_result.result.tool_calls

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": created,
        "model": routed_result.selected_route.name,
        "choices": [
            {
                "index": 0,
                "message": message_payload,
                "finish_reason": routed_result.result.finish_reason,
            }
        ],
        "usage": _normalize_usage(routed_result.result.usage),
    }


async def _single_chunk_stream(response_payload: Dict[str, Any]):
    chunk_id = response_payload["id"]
    created = response_payload["created"]
    model_name = response_payload["model"]
    content = response_payload["choices"][0]["message"].get("content", "")
    finish_reason = response_payload["choices"][0]["finish_reason"]

    first_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

    final_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": finish_reason,
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _routing_headers(routed_result) -> Dict[str, str]:
    headers = {
        "X-LMLauncher-Selected-Model": routed_result.selected_route.name,
    }
    if routed_result.requested_model:
        headers["X-LMLauncher-Requested-Model"] = routed_result.requested_model
    if routed_result.routing_reason:
        headers["X-LMLauncher-Routing-Reason"] = routed_result.routing_reason
    return headers


def get_tool_manager(request: Request) -> ToolManager:
    if not request.app.state.tool_manager:
        raise HTTPException(status_code=400, detail="Tool management is not enabled. Start the server with --tools option.")
    return request.app.state.tool_manager


@app.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    gateway: GatewayService = request.app.state.gateway
    return gateway.health_payload()


@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(request: Request, req: ChatRequest) -> PlainTextResponse:
    gateway: GatewayService = request.app.state.gateway
    messages: list[dict[str, Any]] = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    messages.append({"role": "user", "content": req.prompt})

    routed_result = await gateway.chat(
        GatewayChatRequest(
            model=None,
            messages=messages,
            temperature=req.temperature,
            top_p=req.top_p,
            max_tokens=req.max_tokens,
        )
    )
    return PlainTextResponse(routed_result.result.content)


@app.get("/v1/models", dependencies=[Depends(api_key_auth)])
async def list_gateway_models(request: Request) -> Dict[str, Any]:
    gateway: GatewayService = request.app.state.gateway
    return {"object": "list", "data": gateway.models_payload()}


@app.get("/v1/models/{model_id}", dependencies=[Depends(api_key_auth)])
async def get_gateway_model(request: Request, model_id: str) -> Dict[str, Any]:
    gateway: GatewayService = request.app.state.gateway
    for model in gateway.models_payload():
        if model["id"] == model_id:
            return model
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")


@app.post("/v1/chat/completions", dependencies=[Depends(api_key_auth)])
async def chat_completions(request: Request, req: ChatCompletionRequest):
    gateway: GatewayService = request.app.state.gateway
    routed_result = await gateway.chat(_build_gateway_request(req))
    response_payload = _build_openai_response(routed_result)
    headers = _routing_headers(routed_result)

    if req.stream:
        return StreamingResponse(
            _single_chunk_stream(response_payload),
            media_type="text/event-stream",
            headers=headers,
        )

    return JSONResponse(response_payload, headers=headers)


@app.get("/tools", response_model=List[ToolSchema], dependencies=[Depends(api_key_auth)])
async def list_tools(tm: ToolManager = Depends(get_tool_manager)):
    return tm.get_all()


@app.post("/tools", response_model=ToolSchema, status_code=201, dependencies=[Depends(api_key_auth)])
async def create_tool(tool: ToolSchema, tm: ToolManager = Depends(get_tool_manager)):
    try:
        created_tool = tm.add(tool.model_dump())
        return created_tool
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/tools/{tool_name}", response_model=ToolSchema, dependencies=[Depends(api_key_auth)])
async def get_tool(tool_name: str, tm: ToolManager = Depends(get_tool_manager)):
    tool = tm.get_one(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return tool


@app.put("/tools/{tool_name}", response_model=ToolSchema, dependencies=[Depends(api_key_auth)])
async def update_tool(tool_name: str, tool: ToolSchema, tm: ToolManager = Depends(get_tool_manager)):
    updated_tool = tm.update(tool_name, tool.model_dump())
    if not updated_tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return updated_tool


@app.delete("/tools/{tool_name}", status_code=204, dependencies=[Depends(api_key_auth)])
async def delete_tool(tool_name: str, tm: ToolManager = Depends(get_tool_manager)):
    if not tm.delete(tool_name):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return None


@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
def root() -> str:
    return "LMLauncher gateway is running."
