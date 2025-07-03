"""
Pruebas de la CLI (Typer).

Las fixtures globales en *conftest.py* ya:
• Parchean `subprocess.run` donde corresponde.
• Sustituyen el `LlamaWorker` por una versión in-memory.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from typer.testing import CliRunner

from lmserv.cli import cli

runner = CliRunner()


# ════════════════════════════════════════════════════════════════════════════
# --help debe listar los sub-comandos básicos
# ════════════════════════════════════════════════════════════════════════════
def test_cli_help() -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout
    assert "install" in result.stdout
    assert "discover" in result.stdout


# ════════════════════════════════════════════════════════════════════════════
# El sub-comando `serve` debe invocar uvicorn con las env-vars correctas
# ════════════════════════════════════════════════════════════════════════════
def test_serve_invokes_uvicorn(monkeypatch, tmp_path) -> None:
    captured: Dict[str, Any] = {}

    def _fake_run(cmd, check, env, **kwargs):  # noqa: D401
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    dummy_model = tmp_path / "dummy.gguf"
    dummy_model.write_text("fake-model")

    res = runner.invoke(
        cli,
        [
            "serve",
            "--model-path",
            str(dummy_model),
            "--workers",
            "1",
            "--port",
            "9000",
        ],
    )

    assert res.exit_code == 0
    # comando lanzado
    assert captured["cmd"][:4] == [
        os.sys.executable,
        "-m",
        "uvicorn",
        "lmserv.server.api:app",
    ]
    # variables de entorno
    assert captured["env"]["MODEL_PATH"] == str(dummy_model)
    assert captured["env"]["PORT"] == "9000"
    assert captured["env"]["WORKERS"] == "1"


# ════════════════════════════════════════════════════════════════════════════
# El proxy `lmserv llama --version` debe reenviar flags a llama-cli
# ════════════════════════════════════════════════════════════════════════════
def test_llama_proxy(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    def _fake_run(cmd, check, **kwargs):  # noqa: D401
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    res = runner.invoke(cli, ["llama", "--version"])
    assert res.exit_code == 0
    # La fixture de Config en conftest fija LLAMA_BIN = /usr/bin/llama-cli
    assert captured["cmd"][0] == "/usr/bin/llama-cli"
    assert captured["cmd"][1:] == ["--version"]
