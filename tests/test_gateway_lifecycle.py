"""Regression tests for bounded upstream reads and the ASGI stream handoff."""
import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from lmserv.server import shared_api
from lmserv.server.routes import BackendRoute


KEY = "application-secret-" + "a" * 32
AUTH = {"Authorization": f"Bearer {KEY}"}
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1sAAAAASUVORK5CYII="


def payload_for(route, stream=False):
    if route == "embeddings":
        return {"model": "bge-m3", "input": "page"}
    content = "hello" if route == "chat" else [
        {"type": "text", "text": "Transcribe this page"},
        {"type": "image_url", "image_url": {"url": PNG}},
    ]
    return {"model": route, "stream": stream, "messages": [{"role": "user", "content": content}]}


class UnreadBody(httpx.AsyncByteStream):
    """Content must be closed without ever decoding or iterating it."""
    def __init__(self):
        self.closed = False
        self.iterated = False

    async def __aiter__(self):
        self.iterated = True
        raise AssertionError("Upstream body must not be read")
        yield b""  # pragma: no cover; make this an async generator

    async def aclose(self):
        self.closed = True


@asynccontextmanager
async def gateway(handler):
    config = shared_api.Settings(
        backend_url="http://chat-engine/v1", backend_model="qwen-real", aliases=("chat",),
        keys={"app": KEY}, auxiliary_routes=(
            BackendRoute(name="ocr", operation="chat", backend_url="http://ocr-engine/v1",
                         backend_model="ocr-real", aliases=("ocr",)),
            BackendRoute(name="embeddings", operation="embeddings", backend_url="http://embedding-engine/v1",
                         backend_model="bge-real", aliases=("bge-m3",)),
        ),
    )
    app = shared_api.create_app(config, transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield app, client


@pytest.mark.asyncio
@pytest.mark.parametrize("route,stream", [("chat", False), ("chat", True), ("ocr", False),
                                         ("ocr", True), ("embeddings", False)])
@pytest.mark.parametrize("encoding", ["gzip", "br"])
async def test_unexpected_compression_rejected_before_upstream_body_decode(route, stream, encoding):
    body = UnreadBody()

    def backend(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": encoding}, stream=body)

    async with gateway(backend) as (app, client):
        path = "/v1/embeddings" if route == "embeddings" else "/v1/chat/completions"
        response = await client.post(path, headers=AUTH, json=payload_for(route, stream))
        assert response.status_code == 502
        assert app.state.admissions[route].snapshot()["inflight"] == 0
        assert body.closed
        assert not body.iterated


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["chat", "ocr", "bge-m3"])
async def test_readiness_rejects_compressed_catalog_without_reading_it(alias):
    body = UnreadBody()

    def backend(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=body)

    async with gateway(backend) as (_, client):
        response = await client.get("/ready", params={"model": alias}, headers=AUTH)
        assert response.status_code == 503
        assert body.closed
        assert not body.iterated


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["chat", "ocr"])
@pytest.mark.parametrize("failure", [asyncio.CancelledError, RuntimeError])
async def test_context_exit_failure_finalizes_stream_before_asgi_handoff(monkeypatch, route, failure):
    body = UnreadBody()
    app = None

    @asynccontextmanager
    async def interrupted_context_exit(request):
        yield
        # forward has returned a stream, but the handler has not yet handed the
        # response to ASGI. Reproduce cancellation in the watcher's final await.
        assert app.state.admissions[route].snapshot()["inflight"] == 1
        await asyncio.sleep(0)
        raise failure()

    monkeypatch.setattr(shared_api, "cancel_on_disconnect", interrupted_context_exit)
    async with gateway(lambda request: httpx.Response(200, stream=body)) as (app, client):
        with pytest.raises(failure):
            await client.post("/v1/chat/completions", headers=AUTH, json=payload_for(route, stream=True))
        assert body.closed
        assert not body.iterated
        assert app.state.admissions[route].snapshot()["inflight"] == 0
        assert app.state.admissions[route].snapshot()["totals"]["completed"] == 1
