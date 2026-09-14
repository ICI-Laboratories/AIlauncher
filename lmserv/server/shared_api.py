"""Stateless, admission-controlled OpenAI gateway for a shared inference engine.

One ASGI worker owns admission state. Scale the engine slots, not ASGI workers.
The legacy CLI and Ollama gateway remains available for older deployments.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hmac
import json
import logging
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


async def read_payload(request: Request, maximum: int) -> ChatPayload:
    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > maximum:
                raise HTTPException(413, "Request body exceeds MAX_BODY_BYTES")
        payload = ChatPayload.model_validate_json(body)
    except (ValidationError, ValueError) as exc:
        # Validation errors can contain the original prompt; do not echo it.
        raise HTTPException(422, "Invalid chat payload or unsupported parameter") from exc
    except ClientDisconnect as exc:
        raise HTTPException(400, "Client disconnected") from exc
    for message in payload.messages:
        if message.get("role") not in {"system", "developer", "user", "assistant", "tool"}:
            raise HTTPException(422, "Unsupported message role")
    return payload


def is_vision(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(item, dict) and item.get("type") in {"image_url", "input_image"}
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
        app.state.admission = AdmissionController(
            max_inflight=cfg.max_inflight, max_queue=cfg.max_queue,
            per_app_inflight=cfg.per_app_inflight, queue_timeout=cfg.queue_timeout,
        )
        async with httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(cfg.request_timeout, connect=5),
            limits=httpx.Limits(max_connections=cfg.max_inflight + 4,
                               max_keepalive_connections=cfg.max_inflight + 4),
            follow_redirects=False, trust_env=False,
        ) as client:
            app.state.client = client
            yield

    api = FastAPI(title="LMLauncher Shared Gateway", version="3.0.0", lifespan=lifespan)

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
    async def ready(request: Request, app_id=Depends(authenticate)):
        cfg = request.app.state.settings
        try:
            response = await request.app.state.client.get(cfg.backend_url + "/models")
            response.raise_for_status()
            model_ids = [m.get("id") for m in response.json().get("data", [])]
            if cfg.backend_model not in model_ids:
                raise ValueError("Configured model not loaded")
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise HTTPException(503, "Configured model is not ready")
        return {"status": "ready", "model": cfg.aliases[0], "context_tokens": cfg.max_context_tokens}

    @api.get("/metrics")
    async def metrics(request: Request, app_id=Depends(authenticate)):
        if app_id != "admin":
            raise HTTPException(403, "Admin key required")
        return request.app.state.admission.snapshot()

    @api.get("/v1/models")
    async def models(request: Request, app_id=Depends(authenticate)):
        return {"object": "list", "data": [
            {"id": alias, "object": "model", "owned_by": "local", "created": 0}
            for alias in request.app.state.settings.aliases]}

    @api.post("/v1/chat/completions")
    async def chat(request: Request, app_id=Depends(authenticate)):
        state = request.app.state
        cfg = state.settings
        payload = await read_payload(request, cfg.max_body_bytes)
        alias = payload.model or cfg.aliases[0]
        if alias not in cfg.aliases:
            raise HTTPException(404, "Unknown model alias")
        if payload.max_tokens is not None and payload.max_completion_tokens is not None:
            raise HTTPException(422, "Specify only one output token limit")
        limit = payload.max_tokens or payload.max_completion_tokens or cfg.max_output_tokens
        if limit > cfg.max_output_tokens:
            raise HTTPException(422, f"Output budget exceeds {cfg.max_output_tokens} tokens")
        body = payload.model_dump(exclude_none=True)
        body.pop("max_completion_tokens", None)
        body["max_tokens"] = limit
        body["model"] = cfg.backend_model
        async with cancel_on_disconnect(request):
            return await forward(request, payload, body, alias, app_id)

    async def forward(request, payload, body, alias, app_id):
        state = request.app.state
        cfg = state.settings
        workload = "vision" if is_vision(payload.messages) else "text"
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        stats = StreamStats(started)
        admission = state.admission.acquire(app_id, workload=workload)
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
                    "workload": workload, "status": status,
                    "queue_wait_ms": round(lease.queued_seconds * 1000, 3),
                    "first_content_ms": stats.first_content_ms,
                    "total_ms": round((time.monotonic() - started) * 1000, 3),
                    "usage": {k: v for k, v in (stats.usage or {}).items()
                              if k in {"prompt_tokens", "completion_tokens", "total_tokens"}},
                }))

        try:
            upstream_request = state.client.build_request("POST", cfg.backend_url + "/chat/completions", json=body)
            async with asyncio.timeout(cfg.request_timeout):
                upstream = await state.client.send(upstream_request, stream=True)
            status = upstream.status_code
            headers = {"X-Request-ID": request_id, "X-LMLauncher-Selected-Model": alias}
            if "retry-after" in upstream.headers:
                headers["Retry-After"] = upstream.headers["retry-after"]
            if payload.stream and upstream.is_success:
                async def stream():
                    nonlocal status
                    try:
                        remaining = max(0.001, cfg.request_timeout - (time.monotonic() - started - lease.queued_seconds))
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
            remaining = max(0.001, cfg.request_timeout - (time.monotonic() - started - lease.queued_seconds))
            async with asyncio.timeout(remaining):
                await upstream.aread()
            try:
                data = upstream.json()
            except ValueError:
                status = 502
                raise HTTPException(502, "Invalid inference response")
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                stats.usage = data["usage"]
            return JSONResponse(data, status_code=status, headers=headers)
        except (TimeoutError, httpx.TimeoutException):
            status = 504
            raise HTTPException(504, "Inference deadline exceeded")
        except httpx.HTTPError:
            status = 502
            raise HTTPException(502, "Inference backend unavailable")
        finally:
            if not handed_to_stream:
                await asyncio.shield(cleanup())

    return api


app = create_app()
