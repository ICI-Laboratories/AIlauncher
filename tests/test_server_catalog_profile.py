import json
from pathlib import Path


def test_server_catalog_matches_validated_sara_profile():
    catalog_path = Path(__file__).resolve().parent.parent / "deploy" / "models.server.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert catalog["default_model"] == "sara-main"
    route = catalog["models"][0]
    assert route["name"] == "sara-main"
    assert route["backend"] == "ollama"
    assert route["target"] == "qwen3.6-sara:opt"

    settings = route["settings"]
    assert settings["think"] is False
    assert settings["keep_alive"] == "24h"
    assert settings["options"] == {
        "num_ctx": 4096,
        "num_gpu": 41,
        "num_batch": 512,
        "num_thread": 24,
    }

    capabilities = route["capabilities"]
    assert capabilities["structured_output"] is True
    assert capabilities["json_mode"] is True
    assert capabilities["tools"] is True
