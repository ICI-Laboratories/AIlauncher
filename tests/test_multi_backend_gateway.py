"""Public gateway contracts for isolated chat, OCR and embedding backends.

All engines are mocked; these tests never allocate GPU memory or contact the
production gateway. Events make contention and cancellation reproducible.
"""
import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest

from lmserv.server.routes import BackendRoute
from lmserv.server.shared_api import Settings, create_app


APP_KEY = "test-application-" + "a" * 32
ADMIN_KEY = "test-administrator-" + "b" * 32
AUTH = {"Authorization": f"Bearer {APP_KEY}"}
ADMIN_AUTH = {"Authorization": f"Bearer {ADMIN_KEY}"}
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1sAAAAASUVORK5CYII="
CHAT = {"model": "sara-main", "messages": [{"role": "user", "content": "hello"}]}
OCR = {"model": "ocr", "messages": [{"role": "user", "content": [
    {"type": "text", "text": "Transcribe this page"},
    {"type": "image_url", "image_url": {"url": PNG}},
]}]}
EMBEDDINGS = {"model": "bge-m3", "input": ["first page", "second page"]}
REQUESTS = {
    "chat": ("/v1/chat/completions", CHAT),
    "ocr": ("/v1/chat/completions", OCR),
    "embeddings": ("/v1/embeddings", EMBEDDINGS),
}
REAL_MODELS = {"chat": "qwen-real", "ocr": "glm-ocr-real", "embeddings": "bge-real"}


def auxiliary_routes(**overrides):
    common = dict(max_inflight=1, max_queue=0, per_app_inflight=1,
                  request_timeout=2, max_output_tokens=64, max_context_tokens=1024)
    return (
        BackendRoute(**{**common, "name": "ocr", "operation": "chat",
                        "backend_url": "http://ocr-engine/v1", "backend_model": REAL_MODELS["ocr"],
                        "aliases": ("ocr",), **overrides.get("ocr", {})}),
        BackendRoute(**{**common, "name": "embeddings", "operation": "embeddings",
                        "backend_url": "http://embedding-engine/v1", "backend_model": REAL_MODELS["embeddings"],
                        "aliases": ("bge-m3", "embedding"), "embedding_dimensions": 3,
                        **overrides.get("embeddings", {})}),
    )


def response_for(route, *, reverse_indices=False):
    if route != "embeddings":
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    data = [{"object": "embedding", "index": i, "embedding": [0.1, 0.2, 0.3]} for i in range(2)]
    return httpx.Response(200, json={"object": "list", "model": REAL_MODELS["embeddings"],
                                    "data": data[::-1] if reverse_indices else data,
                                    "usage": {"prompt_tokens": 4, "total_tokens": 4}})


def route_for(request):
    return {"chat-engine": "chat", "ocr-engine": "ocr", "embedding-engine": "embeddings"}[request.url.host]


@asynccontextmanager
async def gateway(handler=None, *, routes=None, **overrides):
    cfg = Settings(**{
        "backend_url": "http://chat-engine/v1", "backend_model": REAL_MODELS["chat"],
        "aliases": ("sara-main", "public"), "keys": {"app": APP_KEY, "admin": ADMIN_KEY},
        "max_output_tokens": 128, "max_inflight": 1, "max_queue": 0, "per_app_inflight": 1,
        "auxiliary_routes": auxiliary_routes() if routes is None else routes,
        **overrides,
    })
    app = create_app(cfg, transport=httpx.MockTransport(handler or (lambda req: response_for(route_for(req)))))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield app, client


async def post(client, route, **kwargs):
    path, payload = REQUESTS[route]
    return await client.post(path, headers=AUTH, json=payload, **kwargs)


@pytest.mark.asyncio
async def test_routes_forward_to_distinct_engines_and_rewrite_only_backend_model():
    seen = []

    def backend(request):
        route = route_for(request)
        payload = json.loads(request.content)
        seen.append((route, request.url.path, payload))
        assert payload["model"] == REAL_MODELS[route]
        assert "authorization" not in request.headers
        return response_for(route, reverse_indices=True)

    async with gateway(backend) as (_, client):
        for route in REQUESTS:
            response = await post(client, route)
            assert response.status_code == 200, response.text
            assert response.headers["x-lmlauncher-route"] == route
            assert response.headers["x-lmlauncher-selected-model"] == REQUESTS[route][1]["model"]
            assert response.headers["x-request-id"]
            if route == "embeddings":
                assert sorted(item["index"] for item in response.json()["data"]) == [0, 1]
                assert response.json()["model"] == "bge-m3"
        assert [(route, path) for route, path, _ in seen] == [
            ("chat", "/v1/chat/completions"), ("ocr", "/v1/chat/completions"),
            ("embeddings", "/v1/embeddings"),
        ]
        assert seen[0][2]["messages"] == CHAT["messages"]
        assert seen[1][2]["messages"] == OCR["messages"]
        assert seen[2][2]["input"] == EMBEDDINGS["input"]


@pytest.mark.asyncio
async def test_missing_chat_model_keeps_default_route():
    seen = []

    def backend(request):
        seen.append(route_for(request))
        return response_for("chat")

    async with gateway(backend) as (_, client):
        response = await client.post("/v1/chat/completions", headers=AUTH, json={"messages": CHAT["messages"]})
        assert response.status_code == 200
        assert response.headers["x-lmlauncher-selected-model"] == "sara-main"
        assert seen == ["chat"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["ocr", "embeddings"])
async def test_auxiliary_inference_requires_application_auth_before_contacting_engine(route):
    def backend(request):
        pytest.fail("Unauthenticated request reached engine")

    async with gateway(backend) as (_, client):
        path, payload = REQUESTS[route]
        for headers in ({}, {"Authorization": "Bearer incorrect"}):
            response = await client.post(path, headers=headers, json=payload)
            assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload,status", [
    ("/v1/chat/completions", {**CHAT, "model": "unknown"}, 404),
    ("/v1/embeddings", {**EMBEDDINGS, "model": "unknown"}, 404),
    ("/v1/chat/completions", {**CHAT, "model": "bge-m3"}, 409),
    ("/v1/embeddings", {**EMBEDDINGS, "model": "sara-main"}, 409),
    ("/v1/embeddings", {**EMBEDDINGS, "model": "ocr"}, 409),
])
async def test_unknown_alias_and_wrong_operation_cannot_fall_back_to_chat(path, payload, status):
    def backend(request):
        pytest.fail("Unroutable request reached engine")

    async with gateway(backend) as (_, client):
        assert (await client.post(path, headers=AUTH, json=payload)).status_code == status


@pytest.mark.asyncio
async def test_disabled_auxiliary_routes_are_not_advertised_or_forwarded():
    def backend(request):
        pytest.fail("Disabled auxiliary route reached engine")

    async with gateway(backend, routes=()) as (_, client):
        models = (await client.get("/v1/models", headers=AUTH)).json()["data"]
        assert [model["id"] for model in models] == ["sara-main", "public"]
        for route in ("ocr", "embeddings"):
            assert (await post(client, route)).status_code == 404
            alias = REQUESTS[route][1]["model"]
            assert (await client.get("/ready", params={"model": alias}, headers=AUTH)).status_code == 404


@pytest.mark.asyncio
async def test_models_publish_capabilities_for_enabled_public_aliases_only():
    async with gateway() as (_, client):
        response = await client.get("/v1/models", headers=AUTH)
        assert response.status_code == 200
        models = response.json()["data"]
        assert [(model["id"], model["category"], model["operation"]) for model in models] == [
            ("sara-main", "chat", "chat"), ("public", "chat", "chat"), ("ocr", "ocr", "chat"),
            ("bge-m3", "embeddings", "embeddings"), ("embedding", "embeddings", "embeddings"),
        ]
        assert "-engine" not in response.text
        assert not any(model in response.text for model in REAL_MODELS.values())


@pytest.mark.asyncio
async def test_readiness_checks_only_selected_route_and_auxiliary_outage_does_not_block_chat():
    seen = []

    def backend(request):
        route = route_for(request)
        seen.append(route)
        assert request.url.path == "/v1/models"
        if route == "ocr":
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"data": [{"id": REAL_MODELS[route]}]})

    async with gateway(backend) as (_, client):
        assert (await client.get("/ready", headers=AUTH)).status_code == 200
        assert seen == ["chat"]
        assert (await client.get("/ready", params={"model": "ocr"}, headers=AUTH)).status_code == 503
        response = await client.get("/ready", params={"model": "embedding"}, headers=AUTH)
        assert response.status_code == 200
        assert response.json()["model"] == "embedding"
        assert response.json()["category"] == "embeddings"
        assert seen == ["chat", "ocr", "embeddings"]


@pytest.mark.asyncio
async def test_metrics_keep_legacy_chat_counters_and_separate_auxiliary_counters():
    async with gateway() as (_, client):
        for route in REQUESTS:
            assert (await post(client, route)).status_code == 200
        assert (await client.get("/metrics", headers=AUTH)).status_code == 403
        response = await client.get("/metrics", headers=ADMIN_AUTH)
        assert response.status_code == 200
        metrics = response.json()
        assert metrics["totals"]["admitted"] == 1
        assert metrics["inflight"] == metrics["queued"] == 0
        assert set(metrics["routes"]) == set(REQUESTS)
        for route in REQUESTS:
            assert metrics["routes"][route]["totals"]["admitted"] == 1
            assert metrics["routes"][route]["inflight"] == 0
        assert APP_KEY not in response.text
        assert "Transcribe" not in response.text
        assert "-engine" not in response.text


@pytest.mark.asyncio
async def test_route_body_limits_and_ocr_output_budget_are_independent_of_chat():
    seen = []

    def backend(request):
        route = route_for(request)
        seen.append((route, json.loads(request.content)))
        return response_for(route)

    async with gateway(backend, max_body_bytes=128, routes=auxiliary_routes(
            ocr={"max_body_bytes": 2048}, embeddings={"max_body_bytes": 128})) as (_, client):
        large_chat = {**CHAT, "messages": [{"role": "user", "content": "x" * 200}]}
        assert (await client.post("/v1/chat/completions", headers=AUTH, json=large_chat)).status_code == 413
        large_embedding = {**EMBEDDINGS, "input": "x" * 200}
        assert (await client.post("/v1/embeddings", headers=AUTH, json=large_embedding)).status_code == 413
        response = await client.post("/v1/chat/completions", headers=AUTH, json={**OCR, "max_tokens": 100})
        assert response.status_code == 200
        assert response.headers["x-tokens-clamped"] == "true"
        assert [(route, body["max_tokens"]) for route, body in seen] == [("ocr", 64)]


@pytest.mark.asyncio
@pytest.mark.parametrize("occupied", ["chat", "ocr", "embeddings"])
async def test_saturating_one_route_leaves_other_routes_available(occupied):
    started, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def backend(request):
        route = route_for(request)
        seen.append(route)
        if route == occupied:
            started.set()
            await release.wait()
        return response_for(route)

    async with gateway(backend) as (app, client):
        pending = asyncio.create_task(post(client, occupied))
        try:
            await asyncio.wait_for(started.wait(), 1)
            rejected = await post(client, occupied)
            assert rejected.status_code == 429
            assert rejected.headers["retry-after"]
            for other in REQUESTS.keys() - {occupied}:
                assert (await post(client, other)).status_code == 200
            assert seen.count(occupied) == 1
            assert app.state.admissions[occupied].snapshot()["inflight"] == 1
        finally:
            release.set()
            await asyncio.wait_for(pending, 1)
        assert app.state.admissions[occupied].snapshot()["inflight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["ocr", "embeddings"])
async def test_auxiliary_queue_cancellation_releases_waiter_only(route):
    def backend(request):
        pytest.fail("Queued cancelled request reached engine")

    async with gateway(backend, routes=auxiliary_routes(**{route: {"max_queue": 1}})) as (app, client):
        controller = app.state.admissions[route]
        async with controller.acquire("occupied"):
            pending = asyncio.create_task(post(client, route))
            async with asyncio.timeout(1):
                while controller.snapshot()["queued"] != 1:
                    await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert controller.snapshot()["queued"] == 0
            assert controller.snapshot()["inflight"] == 1
        assert controller.snapshot()["inflight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["ocr", "embeddings"])
async def test_auxiliary_backend_timeout_releases_its_own_capacity(route):
    cancelled = asyncio.Event()

    async def backend(request):
        assert route_for(request) == route
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async with gateway(backend, routes=auxiliary_routes(**{route: {"request_timeout": 0.02}})) as (app, client):
        response = await post(client, route)
        assert response.status_code == 504
        assert cancelled.is_set()
        assert app.state.admissions[route].snapshot()["inflight"] == 0
        assert app.state.admission.snapshot()["totals"]["admitted"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["ocr", "embeddings"])
async def test_auxiliary_queue_deadline_does_not_reach_upstream(route):
    def backend(request):
        pytest.fail("Expired queued request reached engine")

    routes = auxiliary_routes(**{route: {"max_queue": 1, "queue_timeout": 0.02}})
    async with gateway(backend, routes=routes) as (app, client):
        controller = app.state.admissions[route]
        async with controller.acquire("occupied"):
            response = await post(client, route)
            assert response.status_code == 503
            assert response.headers["retry-after"]
            assert controller.snapshot()["queued"] == 0
            assert controller.snapshot()["inflight"] == 1
        assert controller.snapshot()["inflight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["ocr", "embeddings"])
async def test_auxiliary_cancellation_during_backend_read_closes_response(route):
    class BlockingBody(httpx.AsyncByteStream):
        def __init__(self):
            self.started, self.closed = asyncio.Event(), asyncio.Event()

        async def __aiter__(self):
            yield b'{"data":'
            self.started.set()
            await asyncio.Future()

        async def aclose(self):
            self.closed.set()

    stream = BlockingBody()
    async with gateway(lambda request: httpx.Response(200, stream=stream)) as (app, client):
        pending = asyncio.create_task(post(client, route))
        await asyncio.wait_for(stream.started.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stream.closed.is_set()
        assert app.state.admissions[route].snapshot()["inflight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["ocr", "embeddings"])
@pytest.mark.parametrize("failure", ["status", "connection"])
async def test_auxiliary_failure_never_retries_chat_and_hides_upstream_details(route, failure):
    seen = []

    def backend(request):
        seen.append(route_for(request))
        if failure == "connection":
            raise httpx.ConnectError("private /path or prompt", request=request)
        return httpx.Response(503, headers={"Retry-After": "7"}, json={"error": "private /path or prompt"})

    async with gateway(backend) as (_, client):
        response = await post(client, route)
        assert response.status_code == (502 if failure == "connection" else 503)
        if failure == "status":
            assert response.headers["retry-after"] == "7"
        assert "private" not in response.text
        assert seen == [route]


@pytest.mark.asyncio
@pytest.mark.parametrize("extra,status", [
    ({"dimensions": 2}, 422), ({"input": [1, 2]}, 422), ({"input": [[1, 2]]}, 422),
    ({"input": ["ok", 1]}, 422), ({"input": "x" * 8193}, 413), ({"input": ["page"] * 17}, 422),
    ({"input": ["x" * 8192] * 9}, 413), ({"encoding_format": "base64"}, 422), ({"id_slot": 0}, 422),
])
async def test_invalid_embedding_contract_is_rejected_before_upstream(extra, status):
    def backend(request):
        pytest.fail("Invalid embedding request reached engine")

    async with gateway(backend) as (_, client):
        response = await client.post("/v1/embeddings", headers=AUTH, json={**EMBEDDINGS, **extra})
        assert response.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [
    [],
    [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
    [{"index": 0, "embedding": [0.1, 0.2, 0.3]}] * 2,
    [{"index": 0, "embedding": [0.1, 0.2]}, {"index": 1, "embedding": [0.1, 0.2]}],
    [{"index": 0, "embedding": [True, 0.2, 0.3]}, {"index": 1, "embedding": [0.1, 0.2, 0.3]}],
    [{"index": 0, "embedding": ["private", 0.2, 0.3]}, {"index": 1, "embedding": [0.1, 0.2, 0.3]}],
])
async def test_invalid_embedding_response_is_not_delivered_to_apps(data):
    async with gateway(lambda request: httpx.Response(200, json={"data": data})) as (app, client):
        response = await post(client, "embeddings")
        assert response.status_code == 502
        assert "private" not in response.text
        assert app.state.admissions["embeddings"].snapshot()["inflight"] == 0


@pytest.mark.asyncio
async def test_nonfinite_embedding_values_are_rejected():
    body = b'{"data":[{"index":0,"embedding":[NaN,0,0]},{"index":1,"embedding":[1,0,0]}]}'
    async with gateway(lambda request: httpx.Response(200, content=body)) as (_, client):
        assert (await post(client, "embeddings")).status_code == 502


@pytest.mark.asyncio
async def test_remote_ocr_image_is_rejected_before_upstream():
    def backend(request):
        pytest.fail("Remote OCR image reached engine")

    payload = {"model": "ocr", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "http://private-document-server/page.png"}},
    ]}]}
    async with gateway(backend) as (_, client):
        assert (await client.post("/v1/chat/completions", headers=AUTH, json=payload)).status_code == 422
