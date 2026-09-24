"""Shared gateway contracts, with direct ASGI sends to observe real streaming."""
import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest

from lmserv.server.shared_api import Settings, create_app


APP_KEY = "app-secret-" + "a" * 32
ADMIN_KEY = "admin-secret-" + "b" * 32
AUTH = {"Authorization": f"Bearer {APP_KEY}"}
BASE = {"model": "public", "messages": [{"role": "user", "content": "hello"}]}


def settings(**overrides):
    return Settings(**{
        "backend_url": "http://engine/v1", "backend_model": "real-model",
        "aliases": ("public", "sara-main"), "keys": {"app": APP_KEY, "admin": ADMIN_KEY},
        "max_output_tokens": 128, **overrides,
    })


@asynccontextmanager
async def gateway(handler=None, **overrides):
    handler = handler or (lambda request: httpx.Response(200, json={"choices": []}))
    app = create_app(settings(**overrides), transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield app, client


@pytest.mark.asyncio
async def test_auth_models_and_admin_metrics():
    async with gateway() as (_, client):
        assert (await client.get("/health")).status_code == 200
        for path in ("/v1/models", "/ready", "/metrics"):
            assert (await client.get(path)).status_code == 401
        response = await client.get("/v1/models", headers=AUTH)
        assert [m["id"] for m in response.json()["data"]] == ["public", "sara-main"]
        assert (await client.get("/v1/models", headers={"x-api-key": APP_KEY})).status_code == 200
        assert (await client.get("/metrics", headers=AUTH)).status_code == 403
        assert (await client.get("/metrics", headers={"Authorization": f"Bearer {ADMIN_KEY}"})).status_code == 200


@pytest.mark.asyncio
async def test_forwards_native_images_instructions_schema_tools_and_parameters():
    seen = []

    def backend(request):
        seen.append(json.loads(request.content))
        assert str(request.url) == "http://engine/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    payload = {
        **BASE, "model": "sara-main",
        "messages": [
            {"role": "system", "content": "Only describe the image"},
            {"role": "user", "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "low"}},
            ]},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "answer", "strict": True, "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        }},
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        "temperature": 0.2, "top_p": 0.8, "seed": 123, "stop": ["STOP"],
        "max_completion_tokens": 64,
    }
    async with gateway(backend) as (app, client):
        response = await client.post("/v1/chat/completions", headers=AUTH, json=payload)
        assert response.status_code == 200
        assert response.headers["x-lmlauncher-selected-model"] == "sara-main"
        assert response.headers["x-request-id"]
        assert seen[0]["model"] == "real-model"
        assert seen[0]["max_tokens"] == 64
        assert "max_completion_tokens" not in seen[0]
        for key in ("messages", "response_format", "tools", "temperature", "top_p", "seed", "stop"):
            assert seen[0][key] == payload[key]
        assert app.state.admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"max_tokens": 0}, {"max_tokens": -1},
    {"max_tokens": 12, "max_completion_tokens": 12},
    {"max_tokens": True}, {"max_tokens": "12"}, {"max_tokens": 1.5},
    {"id_slot": 0}, {"cache_prompt": True}, {"slot_save_path": "/tmp/context"},
    {"n": 2}, {"messages": [{"role": "invalid", "content": "private"}]},
    {"messages": [{"role": {}, "content": "private"}]},
])
async def test_invalid_budgets_and_backend_controls_never_reach_engine(extra):
    def backend(request):
        pytest.fail("Invalid request reached engine")

    async with gateway(backend) as (_, client):
        response = await client.post("/v1/chat/completions", headers=AUTH, json={**BASE, **extra})
        assert response.status_code == 422
        assert "private" not in response.text


@pytest.mark.asyncio
async def test_body_limit_unknown_model_rejection_and_clamped_output_budget():
    seen = []
    def backend(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": []})

    async with gateway(backend, max_body_bytes=256) as (_, client):
        assert (await client.post("/v1/chat/completions", headers=AUTH, json={
            **BASE, "messages": [{"role": "user", "content": "x" * 300}],
        })).status_code == 413
        # An unknown alias must never silently route to the chat backend.
        unknown_resp = await client.post("/v1/chat/completions", headers=AUTH, json={**BASE, "model": "unknown-model"})
        assert unknown_resp.status_code == 404
        assert seen == []
        # Standard request uses default budget
        assert (await client.post("/v1/chat/completions", headers=AUTH, json=BASE)).status_code == 200
        assert seen[0]["max_tokens"] == 128
        # Request with tokens over budget is softly clamped with X-Tokens-Clamped header
        clamped_resp = await client.post("/v1/chat/completions", headers=AUTH, json={**BASE, "max_tokens": 200})
        assert clamped_resp.status_code == 200
        assert clamped_resp.headers["x-tokens-clamped"] == "true"
        assert seen[1]["max_tokens"] == 128
        assert len(seen) == 2


@pytest.mark.asyncio
async def test_backend_error_status_and_retry_after_preserved_without_private_details():
    error = {"error": {"message": "engine busy: private prompt or path", "type": "overloaded"}}
    async with gateway(lambda req: httpx.Response(429, headers={"Retry-After": "9"}, json=error)) as (app, client):
        response = await client.post("/v1/chat/completions", headers=AUTH, json={**BASE, "stream": True})
        assert response.status_code == 429
        assert response.json() == {"error": {"message": "Inference backend rejected request", "type": "upstream_error"}}
        assert "private prompt" not in response.text
        assert response.headers["retry-after"] == "9"
        assert app.state.admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_response", [
    httpx.Response(503, json={}), httpx.Response(200, json={"data": []}),
    httpx.Response(200, text="broken"), httpx.Response(200, json={"data": [None]}),
])
async def test_ready_rejects_unavailable_or_missing_backend_model(backend_response):
    async with gateway(lambda req: backend_response) as (_, client):
        assert (await client.get("/ready", headers=AUTH)).status_code == 503


@pytest.mark.asyncio
async def test_ready_checks_actual_engine_model():
    async with gateway(lambda req: httpx.Response(200, json={"data": [{"id": "real-model"}]})) as (_, client):
        response = await client.get("/ready", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["model"] == "public"


class ControlledStream(httpx.AsyncByteStream):
    def __init__(self):
        self.finish = asyncio.Event()
        self.closed = asyncio.Event()

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
        await self.finish.wait()
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed.set()


async def run_asgi_stream(app, on_send):
    body = json.dumps({**BASE, "stream": True}).encode()
    sent = False
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Future()

    await app({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/v1/chat/completions", "raw_path": b"/v1/chat/completions",
        "query_string": b"", "root_path": "",
        "headers": [(b"authorization", f"Bearer {APP_KEY}".encode()), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234), "server": ("gateway", 80),
    }, receive, on_send)


@pytest.mark.asyncio
async def test_stream_first_chunk_precedes_finish_and_holds_slot():
    stream = ControlledStream()
    first = asyncio.Event()
    chunks = []
    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            chunks.append(message["body"])
            first.set()

    async with gateway(lambda req: httpx.Response(200, stream=stream)) as (app, _):
        task = asyncio.create_task(run_asgi_stream(app, send))
        try:
            await asyncio.wait_for(first.wait(), 1)
            assert not task.done()
            assert not stream.finish.is_set()
            assert app.state.admission.snapshot()["inflight"] == 1
            stream.finish.set()
            await asyncio.wait_for(task, 1)
            assert b"[DONE]" in b"".join(chunks)
            assert stream.closed.is_set()
            assert app.state.admission.snapshot()["inflight"] == 0
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["active", "response_start", "first_send"])
async def test_stream_disconnect_closes_upstream_and_releases_capacity(stage):
    stream = ControlledStream()
    first = asyncio.Event()
    async def send(message):
        if stage == "response_start" and message["type"] == "http.response.start":
            raise OSError("client disconnected before headers")
        if message["type"] == "http.response.body" and message.get("body"):
            if stage == "first_send":
                raise OSError("client disconnected writing body")
            first.set()

    async with gateway(lambda req: httpx.Response(200, stream=stream)) as (app, _):
        task = asyncio.create_task(run_asgi_stream(app, send))
        if stage == "active":
            await asyncio.wait_for(first.wait(), 1)
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # Shielded cleanup may finish on the next loop iteration.
        for _ in range(10):
            await asyncio.sleep(0)
            if stream.closed.is_set() and app.state.admission.snapshot()["inflight"] == 0:
                break
        assert stream.closed.is_set()
        assert app.state.admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_queue_full_429_and_queue_timeout_503():
    async with gateway(max_inflight=1, max_queue=1, queue_timeout=0.04) as (app, client):
        async with app.state.admission.acquire("occupied"):
            waiting = asyncio.create_task(client.post("/v1/chat/completions", headers=AUTH, json=BASE))
            async with asyncio.timeout(1):
                while app.state.admission.snapshot()["queued"] != 1:
                    await asyncio.sleep(0)
            full = await client.post("/v1/chat/completions", headers=AUTH, json=BASE)
            assert full.status_code == 429
            assert full.headers["retry-after"]
            expired = await waiting
            assert expired.status_code == 503
            assert expired.headers["retry-after"]
            assert app.state.admission.snapshot()["queued"] == 0


@pytest.mark.asyncio
async def test_total_deadline_also_bounds_wait_for_upstream_headers():
    async def backend(request):
        await asyncio.sleep(0.15)
        return httpx.Response(200, json={"choices": []})
    async with gateway(backend, request_timeout=0.02) as (app, client):
        response = await client.post("/v1/chat/completions", headers=AUTH, json=BASE)
        assert response.status_code == 504
        assert app.state.admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_cancel_queued_handler_removes_waiter_without_disturbing_active_request():
    async with gateway(max_inflight=1, max_queue=1) as (app, client):
        async with app.state.admission.acquire("occupied"):
            pending = asyncio.create_task(client.post("/v1/chat/completions", headers=AUTH, json=BASE))
            async with asyncio.timeout(1):
                while app.state.admission.snapshot()["queued"] != 1:
                    await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert app.state.admission.snapshot()["queued"] == 0
            assert app.state.admission.snapshot()["inflight"] == 1
        assert app.state.admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_cancel_handler_waiting_for_backend_headers_releases_slot():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def backend(request):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async with gateway(backend) as (app, client):
        pending = asyncio.create_task(client.post("/v1/chat/completions", headers=AUTH, json=BASE))
        await asyncio.wait_for(started.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert cancelled.is_set()
        assert app.state.admission.snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_cancel_handler_reading_nonstream_response_closes_backend():
    class BlockingBody(ControlledStream):
        async def __aiter__(self):
            yield b'{"choices":'
            self.finish.set()
            await asyncio.Future()

    stream = BlockingBody()
    async with gateway(lambda req: httpx.Response(200, stream=stream)) as (app, client):
        pending = asyncio.create_task(client.post("/v1/chat/completions", headers=AUTH, json=BASE))
        await asyncio.wait_for(stream.finish.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stream.closed.is_set()
        assert app.state.admission.snapshot()["inflight"] == 0
