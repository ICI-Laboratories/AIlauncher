import asyncio

from lmserv.config import Config
from lmserv.gateway.backends.ollama import OllamaRuntime
from lmserv.gateway.models import GatewayChatRequest, ModelRoute


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "message": {"content": "OK"},
            "prompt_eval_count": 3,
            "eval_count": 1,
        }


class FakeClient:
    def __init__(self):
        self.payload = None

    async def post(self, url, json):
        self.payload = json
        return FakeResponse()


def test_ollama_runtime_merges_catalog_options_with_request_options():
    route = ModelRoute(
        name="sara-main",
        backend="ollama",
        target="qwen3:30b",
        settings={
            "base_url": "http://127.0.0.1:11434",
            "think": False,
            "keep_alive": "10m",
            "options": {
                "num_ctx": 4096,
                "num_gpu": 999,
                "temperature": 0.8,
            },
        },
    )
    cfg = Config(backend="ollama", model="qwen3:30b", api_key="test")
    runtime = OllamaRuntime(route, cfg)
    fake_client = FakeClient()
    runtime._client = fake_client

    request = GatewayChatRequest(
        model="sara-main",
        messages=[{"role": "user", "content": "hola"}],
        temperature=0.2,
        max_tokens=16,
    )

    result = asyncio.run(runtime.chat(request))

    assert result.content == "OK"
    assert fake_client.payload["model"] == "qwen3:30b"
    assert fake_client.payload["think"] is False
    assert fake_client.payload["keep_alive"] == "10m"
    assert fake_client.payload["options"] == {
        "num_ctx": 4096,
        "num_gpu": 999,
        "temperature": 0.2,
        "num_predict": 16,
    }
