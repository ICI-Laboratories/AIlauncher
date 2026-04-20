import json

from lmserv.config import Config
from lmserv.gateway.catalog import load_catalog


def test_catalog_loads_aliases_and_default_model(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "default_model": "research-main",
                "models": [
                    {
                        "name": "research-main",
                        "backend": "llama_cpp",
                        "target": "models/main.gguf",
                        "aliases": ["default"],
                    },
                    {
                        "name": "research-structured",
                        "backend": "ollama",
                        "target": "llama3.1:8b",
                        "aliases": ["json-router"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    cfg = Config(catalog_path=str(catalog_path), api_key="test-key")
    catalog = load_catalog(cfg)

    assert catalog.default_model == "research-main"
    assert catalog.resolve("default").name == "research-main"
    assert catalog.resolve("json-router").name == "research-structured"
