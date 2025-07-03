"""
Fixtures y _monkey-patches_ compartidos por toda la suite PyTest.

Objetivo → correr los tests **sin** `llama-cli` real, de forma rápida
y estable en cualquier CI.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import lmserv.server.pool as poolmod


# ════════════════════════════════════════════════════════════════════════════
# LOOP GLOBAL PARA pytest-asyncio
# ════════════════════════════════════════════════════════════════════════════
import typing

@pytest.fixture(scope="session")
def event_loop() -> typing.Generator[asyncio.AbstractEventLoop, None, None]:  # noqa: D401
    """
    Sustituye el loop por defecto de `pytest-asyncio` por uno propio y lo
    cierra al final de la sesión para evitar “Task was destroyed…”.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ════════════════════════════════════════════════════════════════════════════
# Fixture: parchear `Config` para que no requiera llama-cli real
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _patch_config(monkeypatch: pytest.MonkeyPatch, tmp_path_factory):  # noqa: D401
    """
    • Fuerza `MODEL_PATH` a apuntar a un archivo ficticio.
    • Hace que `Config._resolve_llama_bin()` devuelva una ruta dummy.
    """
    from lmserv import config as cfgmod

    dummy_model = tmp_path_factory.mktemp("models") / "dummy.gguf"
    dummy_model.write_text("fake-model")

    monkeypatch.setenv("MODEL_PATH", str(dummy_model))
    monkeypatch.setenv("LLAMA_BIN", "/usr/bin/llama-cli")

    monkeypatch.setattr(
        cfgmod.Config,
        "_resolve_llama_bin",
        lambda self: "/usr/bin/llama-cli",
    )
    yield


# ════════════════════════════════════════════════════════════════════════════
# Fixture: reemplazar LlamaWorker por versión fake muy ligera
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _patch_llama_worker(monkeypatch: pytest.MonkeyPatch):  # noqa: D401
    """
    Sustituye la clase `LlamaWorker` por una implementación en memoria
    que responde siempre con dos “tokens” (`"Hola"`, `"🙂"`).

    Así evitamos depender de procesos externos y reducimos el tiempo
    de la suite a pocos segundos.
    """
    from lmserv.server.workers import llama as lw

    class _FakeProc(SimpleNamespace):
        def poll(self):  # noqa: D401  (mismo API que subprocess.Popen.poll)
            return None

    class FakeLlamaWorker:  # noqa: D101
        def __init__(self, cfg):
            self.id = "fake-" + hex(id(self))[-4:]
            self.cfg = cfg
            self.proc = _FakeProc()
            self.proc_control_event = asyncio.Event()

        async def spawn(self):  # noqa: D401
            pass  # nada que hacer

        async def infer(self, prompt: str):  # noqa: D401
            yield "Hola"
            yield "🙂"

        async def stop(self):  # noqa: D401
            self.proc_control_event.set()

    monkeypatch.setattr(poolmod, "LlamaWorker", FakeLlamaWorker)
    yield
