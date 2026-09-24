"""Stateless, admission-controlled OpenAI gateway for a shared inference engine.

One ASGI worker owns admission state. Scale the engine slots, not ASGI workers.
The legacy CLI and Ollama gateway remains available for older deployments.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import hmac
import json
import logging
import math
import os
from pathlib import Path
import time
from typing import Any
import uuid

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import ClientDisconnect

from .admission import AdmissionController, AdmissionQueueFull, AdmissionTimeout
from .auxiliary_payloads import (
    EmbeddingPayload, prepare_embeddings, validate_embeddings_response, validate_ocr_messages,
)
from .routes import BackendRoute, build_routes, load_auxiliary_routes, resolve_route

logger = logging.getLogger("lmserv.requests")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False


@dataclass(frozen=True)
class Settings:
    backend_url: str
    backend_model: str
    aliases: tuple[str, ...]
    keys: dict[str, str]
    max_inflight: int = 4
    max_queue: int = 32
    per_app_inflight: int = 2
    queue_timeout: float = 60
    request_timeout: float = 300
    max_output_tokens: int = 2048
    max_body_bytes: int = 16 * 1024 * 1024
    max_context_tokens: int = 8192
    auxiliary_routes: tuple[BackendRoute, ...] = ()

    def __post_init__(self):
        url = httpx.URL(self.backend_url)
        if url.scheme not in {"http", "https"} or not url.host or url.query or url.fragment:
            raise ValueError("MODEL_BACKEND_URL must be an HTTP(S) base URL without query/fragment")
        if not self.keys or any(not isinstance(k, str) or not k or not isinstance(v, str)
                                or len(v) < 24 for k, v in self.keys.items()):
            raise ValueError("APP_KEYS_FILE must map app IDs to distinct secrets of at least 24 characters")
        if len(set(self.keys.values())) != len(self.keys):
            raise ValueError("Each application must have a distinct API key")
        if not self.aliases or any(not alias for alias in self.aliases):
            raise ValueError("At least one model alias is required")
        if min(self.request_timeout, self.max_output_tokens, self.max_body_bytes,
               self.max_context_tokens) <= 0 or self.max_output_tokens >= self.max_context_tokens:
            raise ValueError("Invalid timeout, body or token budgets")
        build_routes(self)

    @classmethod
    def from_env(cls):
        return cls(
            backend_url=os.environ["MODEL_BACKEND_URL"].rstrip("/"),
            backend_model=os.getenv("MODEL_BACKEND_MODEL", "qwen-local"),
            aliases=tuple(x.strip() for x in os.getenv("MODEL_ALIASES", "qwen-local,sara-main,local-model").split(",")),
            keys=json.loads(Path(os.environ["APP_KEYS_FILE"]).read_text()),
            max_inflight=int(os.getenv("MAX_INFLIGHT", "4")),
            max_queue=int(os.getenv("MAX_QUEUE", "32")),
            per_app_inflight=int(os.getenv("PER_APP_INFLIGHT", "2")),
            queue_timeout=float(os.getenv("QUEUE_TIMEOUT_SECONDS", "60")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "300")),
            max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "2048")),
            max_body_bytes=int(os.getenv("MAX_BODY_BYTES", str(16 * 1024 * 1024))),
            max_context_tokens=int(os.getenv("MAX_CONTEXT_TOKENS", "8192")),
            auxiliary_routes=load_auxiliary_routes(),
        )


class ChatPayload(BaseModel):
    # Keep native multimodal messages and schemas intact, reject backend control
    # fields such as id_slot or slot persistence paths from application clients.
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    max_completion_tokens: int | None = Field(default=None, gt=0, strict=True)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=0)
    min_p: float | None = Field(default=None, ge=0, le=1)
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    repeat_penalty: float | None = None
    seed: int | None = None
    stop: str | list[str] | None = None
    response_format: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    parallel_tool_calls: bool | None = None
    chat_template_kwargs: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    stream_options: dict[str, Any] | None = None
    logit_bias: dict[str, float] | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    n: int = Field(default=1, ge=1, le=1)


async def read_payload(request: Request, maximum: int, payload_type=ChatPayload):
    """Bound incoming bytes before parsing, then report length for route budgets."""
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > maximum:
                raise HTTPException(413, "Request body exceeds configured limit")
            body.extend(chunk)
        payload = payload_type.model_validate_json(body)
    except (ValidationError, ValueError) as exc:
        # Validation errors can contain the original input; never echo it.
        raise HTTPException(422, "Invalid payload or unsupported parameter") from exc
    except ClientDisconnect as exc:
        raise HTTPException(400, "Client disconnected") from exc
    if isinstance(payload, ChatPayload):
        for message in payload.messages:
            if (not isinstance(message.get("role"), str)
                    or message["role"] not in {"system", "developer", "user", "assistant", "tool"}):
                raise HTTPException(422, "Unsupported message role")
    return payload, len(body)


def require_identity_encoding(response: httpx.Response):
    # HTTPX decompresses a whole received chunk before aiter_bytes yields it.
    # Reject compression before iteration so expansion cannot bypass our cap.
    if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
        raise HTTPException(502, "Unexpected inference response encoding")


async def read_upstream_json(response: httpx.Response, maximum: int):
    """Bound response bytes, including a missing/false Content-Length."""
    require_identity_encoding(response)
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(502, "Inference response exceeds configured limit")
        body.extend(chunk)
    try:
        return json.loads(body)
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise HTTPException(502, "Invalid inference response") from exc


def safe_usage(usage):
    """Only numeric token counters may enter metadata logs."""
    return {key: value for key, value in (usage or {}).items()
            if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
            and isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 2**63 - 1 and math.isfinite(value)}


def is_vision(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(item, dict) and isinstance(item.get("type"), str)
               and item["type"] in {"image_url", "input_image"}
               for message in messages if isinstance(message.get("content"), list)
               for item in message["content"])


class StreamStats:
    """Observe bounded SSE metadata without altering bytes or logging content."""
    def __init__(self, started: float):
        self.started = started
        self.pending = b""
        self.first_content_ms = None
        self.usage = None

    def feed(self, data: bytes):
        self.pending += data
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            if not line.startswith(b"data:"):
                continue
            try:
                event = json.loads(line[5:])
                if not isinstance(event, dict):
                    continue
                if isinstance(event.get("usage"), dict):
                    self.usage = event["usage"]
                if self.first_content_ms is None and any(
                    c.get("delta", {}).get("content") or c.get("delta", {}).get("reasoning_content")
                    or c.get("delta", {}).get("tool_calls") for c in event.get("choices", [])
                ):
                    self.first_content_ms = round((time.monotonic() - self.started) * 1000, 3)
            except (ValueError, AttributeError, TypeError):
                pass
        if len(self.pending) > 512 * 1024:
            self.pending = b""


class FinalizingStream(StreamingResponse):
    """Release the lease even if ASGI fails before entering the generator."""
    def __init__(self, *args, finalize, **kwargs):
        super().__init__(*args, **kwargs)
        self.finalize = finalize

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                close = getattr(self.body_iterator, "aclose", None)
                if close is not None:
                    await close()
            finally:
                await asyncio.shield(self.finalize())


@asynccontextmanager
async def cancel_on_disconnect(request: Request):
    """Cancel queued/nonstream work when the socket closes after the body."""
    owner = asyncio.current_task()

    async def watch():
        while True:
            event = await request.receive()
            if event["type"] == "http.disconnect":
                owner.cancel()
                return

    watcher = asyncio.create_task(watch())
    try:
        yield
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or Settings.from_env()
        app.state.settings = cfg
        app.state.routes = build_routes(cfg)
        app.state.admissions = {}
        app.state.clients = {}
        async with AsyncExitStack() as stack:
            for name, route in app.state.routes.items():
                app.state.admissions[name] = AdmissionController(
                    max_inflight=route.max_inflight, max_queue=route.max_queue,
                    per_app_inflight=route.per_app_inflight, queue_timeout=route.queue_timeout,
                )
                app.state.clients[name] = await stack.enter_async_context(httpx.AsyncClient(
                    transport=transport, timeout=httpx.Timeout(route.request_timeout, connect=5),
                    headers={"Accept-Encoding": "identity"},
                    limits=httpx.Limits(max_connections=route.max_inflight + 4,
                                       max_keepalive_connections=route.max_inflight + 4),
                    follow_redirects=False, trust_env=False,
                ))
            # Existing monitoring/tests may continue to inspect the chat route.
            app.state.admission = app.state.admissions["chat"]
            app.state.client = app.state.clients["chat"]
            yield

    api = FastAPI(title="LMLauncher Shared Gateway", version="3.1.0", lifespan=lifespan)

    async def authenticate(request: Request):
        authorization = request.headers.get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        key = bearer if scheme.lower() == "bearer" else request.headers.get("x-api-key", "")
        app_id = None
        for candidate, secret in request.app.state.settings.keys.items():
            if hmac.compare_digest(key.encode(), secret.encode()):
                app_id = candidate
        if app_id is None:
            raise HTTPException(401, "Invalid application key", headers={"WWW-Authenticate": "Bearer"})
        return app_id

    @api.get("/health")
    async def health():
        return {"status": "ok"}

    @api.get("/ready")
    async def ready(request: Request, model: str | None = None, app_id=Depends(authenticate)):
        state = request.app.state
        route, alias = resolve_route(state.routes, model, None)
        try:
            async with asyncio.timeout(route.request_timeout):
                async with state.clients[route.name].stream("GET", route.backend_url + "/models") as response:
                    response.raise_for_status()
                    data = await read_upstream_json(response, 256 * 1024)
            model_ids = [m.get("id") for m in data.get("data", [])]
            if route.backend_model not in model_ids:
                raise ValueError("Configured model not loaded")
        except (httpx.HTTPError, HTTPException, TimeoutError, ValueError, TypeError, AttributeError):
            raise HTTPException(503, "Configured model is not ready")
        return {"status": "ready", "model": alias, "context_tokens": route.max_context_tokens,
                "operation": route.operation, "category": route.name}

    @api.get("/metrics")
    async def metrics(request: Request, app_id=Depends(authenticate)):
        if app_id != "admin":
            raise HTTPException(403, "Admin key required")
        state = request.app.state
        return {**state.admission.snapshot(), "routes": {
            name: admission.snapshot() for name, admission in state.admissions.items()
        }}

    @api.get("/v1/models")
    async def models(request: Request, app_id=Depends(authenticate)):
        return {"object": "list", "data": [
            {"id": alias, "object": "model", "owned_by": "local", "created": 0,
             "operation": route.operation, "category": route.name}
            for route in request.app.state.routes.values() for alias in route.aliases]}

    @api.post("/v1/chat/completions")
    async def chat(request: Request, app_id=Depends(authenticate)):
        state = request.app.state
        maximum = max(route.max_body_bytes for route in state.routes.values() if route.operation == "chat")
        payload, body_size = await read_payload(request, maximum)
        route, alias = resolve_route(state.routes, payload.model, "chat")
        if body_size > route.max_body_bytes:
            raise HTTPException(413, "Request body exceeds configured route limit")
        if route.name == "ocr":
            validate_ocr_messages(payload.messages, route)
        if payload.max_tokens is not None and payload.max_completion_tokens is not None:
            raise HTTPException(422, "Specify only one output token limit")
        requested_limit = payload.max_tokens or payload.max_completion_tokens or route.max_output_tokens
        was_clamped = requested_limit > route.max_output_tokens
        body = payload.model_dump(exclude_none=True)
        body.pop("max_completion_tokens", None)
        body["max_tokens"] = min(requested_limit, route.max_output_tokens)
        body["model"] = route.backend_model
        workload = "vision" if is_vision(payload.messages) else "text"
        return await forward_with_disconnect(
            request, body, route, alias, app_id, endpoint="chat/completions",
            stream_requested=payload.stream, workload=workload, was_clamped=was_clamped,
        )

    @api.post("/v1/embeddings")
    async def embeddings(request: Request, app_id=Depends(authenticate)):
        state = request.app.state
        # Parse small disabled-route requests too, so unknown and wrong-operation
        # aliases get the same strict dispatch semantics as chat.
        maximum = max((route.max_body_bytes for route in state.routes.values()
                       if route.operation == "embeddings"), default=state.settings.max_body_bytes)
        payload, body_size = await read_payload(request, maximum, EmbeddingPayload)
        route, alias = resolve_route(state.routes, payload.model, "embeddings")
        if body_size > route.max_body_bytes:
            raise HTTPException(413, "Request body exceeds configured route limit")
        body = prepare_embeddings(payload, route)
        count = len(payload.input) if isinstance(payload.input, list) else 1
        return await forward_with_disconnect(
            request, body, route, alias, app_id, endpoint="embeddings",
            stream_requested=False, workload="embeddings", embedding_count=count,
        )

    async def forward_with_disconnect(request, *args, **kwargs):
        response = None
        try:
            async with cancel_on_disconnect(request):
                response = await forward(request, *args, **kwargs)
        except BaseException:
            # A stream owns its lease after forward returns, but ASGI does not
            # own the response until the disconnect watcher has exited. Close
            # that handoff gap if cancellation interrupts the context exit.
            if isinstance(response, FinalizingStream):
                await asyncio.shield(response.finalize())
            raise
        return response

    async def forward(request, body, route, alias, app_id, *, endpoint, stream_requested,
                      workload, was_clamped: bool = False, embedding_count: int | None = None):
        state = request.app.state
        client = state.clients[route.name]
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        stats = StreamStats(started)
        admission = state.admissions[route.name].acquire(app_id, workload=workload)
        try:
            lease = await admission.__aenter__()
        except AdmissionQueueFull:
            raise HTTPException(429, "Inference queue is full", headers={"Retry-After": "5"})
        except AdmissionTimeout:
            raise HTTPException(503, "Inference queue deadline exceeded", headers={"Retry-After": "5"})
        upstream = None
        handed_to_stream = False
        status = 502
        cleaned = False

        async def cleanup():
            nonlocal cleaned
            if cleaned:
                return
            cleaned = True
            try:
                if upstream is not None:
                    await upstream.aclose()
            finally:
                await admission.__aexit__(None, None, None)
                logger.info(json.dumps({
                    "request_id": request_id, "app_id": app_id, "model": alias,
                    "route": route.name, "workload": workload, "status": status,
                    "queue_wait_ms": round(lease.queued_seconds * 1000, 3),
                    "first_content_ms": stats.first_content_ms,
                    "total_ms": round((time.monotonic() - started) * 1000, 3),
                    "usage": safe_usage(stats.usage),
                }))

        try:
            upstream_request = client.build_request("POST", route.backend_url + "/" + endpoint, json=body)
            async with asyncio.timeout(route.request_timeout):
                upstream = await client.send(upstream_request, stream=True)
            status = upstream.status_code
            headers = {"X-Request-ID": request_id, "X-LMLauncher-Selected-Model": alias,
                       "X-LMLauncher-Route": route.name}
            if was_clamped:
                headers["X-Tokens-Clamped"] = "true"
            if "retry-after" in upstream.headers:
                headers["Retry-After"] = upstream.headers["retry-after"]
            if not upstream.is_success:
                # Backends may echo full text/images in error bodies. Preserve
                # retry/status semantics without forwarding or reading that body.
                status = status if 400 <= status <= 599 else 502
                return JSONResponse({"error": {"message": "Inference backend rejected request",
                                               "type": "upstream_error"}}, status_code=status, headers=headers)
            require_identity_encoding(upstream)
            if stream_requested:
                async def stream():
                    nonlocal status
                    try:
                        remaining = max(0.001, route.request_timeout - (time.monotonic() - started - lease.queued_seconds))
                        async with asyncio.timeout(remaining):
                            async for chunk in upstream.aiter_bytes():
                                stats.feed(chunk)
                                yield chunk
                    except (TimeoutError, httpx.TimeoutException):
                        status = 504
                        yield b'data: {"error":{"message":"Inference deadline exceeded","type":"timeout"}}\n\ndata: [DONE]\n\n'
                    except httpx.HTTPError:
                        status = 502
                        yield b'data: {"error":{"message":"Inference stream interrupted","type":"upstream_error"}}\n\ndata: [DONE]\n\n'
                    except asyncio.CancelledError:
                        status = 499
                        raise
                    finally:
                        await asyncio.shield(cleanup())
                handed_to_stream = True
                return FinalizingStream(stream(), finalize=cleanup, media_type="text/event-stream",
                                         headers={**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
            maximum_response = (embedding_count * route.embedding_dimensions * 32 + 65536
                                if embedding_count is not None else
                                max(route.max_body_bytes, route.max_output_tokens * 32 + 65536))
            remaining = max(0.001, route.request_timeout - (time.monotonic() - started - lease.queued_seconds))
            async with asyncio.timeout(remaining):
                data = await read_upstream_json(upstream, maximum_response)
            if embedding_count is not None:
                data = validate_embeddings_response(data, route, embedding_count, alias)
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                stats.usage = data["usage"]
            return JSONResponse(data, status_code=status, headers=headers)
        except (TimeoutError, httpx.TimeoutException):
            status = 504
            raise HTTPException(504, "Inference deadline exceeded")
        except httpx.HTTPError:
            status = 502
            raise HTTPException(502, "Inference backend unavailable")
        except HTTPException as exc:
            status = exc.status_code
            raise
        except (ValueError, OverflowError) as exc:
            status = 502
            raise HTTPException(502, "Invalid inference response") from exc
        except asyncio.CancelledError:
            status = 499
            raise
        finally:
            if not handed_to_stream:
                await asyncio.shield(cleanup())

    return api


app = create_app()
