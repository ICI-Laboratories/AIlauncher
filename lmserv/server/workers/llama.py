"""
lmserv.server.workers.llama
===========================

Worker que envuelve un **proceso externo** `llama-cli` y expone:

* `spawn()`   – lanza el binario y espera al prompt interactivo
* `infer()`   – envía un *prompt*, devuelve un *async-generator* de tokens
* `stop()`    – termina el proceso con SIGINT/SIGTERM ⇒ SIGKILL

El objetivo es **legibilidad** y ≤ 300 líneas; la lógica “hot-path”
(token sampling, etc.) puede migrarse a C++ (`cpp_bridge`) más adelante.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import uuid
from pathlib import Path
from typing import AsyncIterator

from ...config import Config
from .utils import _stream_reader

logger = logging.getLogger(__name__)

READY_MARKER = "== Running in interactive mode. =="   # stderr de llama.cpp
REVERSE_PROMPT = "<|LMSERV_USER_INPUT_START|>"        # delimita fin de respuesta

# ═════════════════════════════════════════════════════════════════════════════
# LlamaWorker
# ═════════════════════════════════════════════════════════════════════════════
class LlamaWorker:
    """
    Un proceso `llama-cli` asociado a una configuración **Config**.

    Ejemplo
    -------
    ```python
    w = LlamaWorker(Config())
    await w.spawn()
    async for tok in w.infer("Hola"): print(tok)
    await w.stop()
    ```
    """

    # ───────────────────────────── life-cycle ──────────────────────────────
    def __init__(self, cfg: Config) -> None:
        self.id: str = uuid.uuid4().hex[:8]
        self.cfg = cfg
        self.proc: subprocess.Popen[str] | None = None

        # Concurrency helpers
        self._ctl_event = asyncio.Event()
        self._queue: asyncio.Queue[tuple[str, str | None]] | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

    async def spawn(self) -> None:
        """
        Lanza `llama-cli` y espera a que muestre el marcador *READY*.
        """
        cmd = [
            self.cfg.llama_bin,
            "-m", self.cfg.model_path,
            "-i", "--interactive-first",
            "-n", str(self.cfg.max_tokens),
            "--reverse-prompt", REVERSE_PROMPT,
            "-ngl", "100",            # off-load máximo a GPU si aplica
            "-mg", str(self.cfg.gpu_idx),
        ]
        logger.info("[%s] spawn → %s", self.id, " ".join(cmd))

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,          # line-buffer
            encoding="utf-8",
            errors="replace",
        )

        # colas y readers
        self._queue = asyncio.Queue()
        self._stdout_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, self._queue, self.id, "stdout", self._ctl_event)
        )
        self._stderr_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, self._queue, self.id, "stderr", self._ctl_event)
        )

        # Esperar READY_MARKER
        try:
            await asyncio.wait_for(self._wait_ready(), timeout=45)
        except asyncio.TimeoutError:
            raise RuntimeError(f"[{self.id}] llama-cli no respondió en 45 s")

        logger.info("[%s] listo para inferencia.", self.id)

    async def _wait_ready(self) -> None:
        """Bloquea hasta encontrar READY_MARKER en stderr."""
        assert self._queue
        while True:
            _, line = await self._queue.get()
            if line is None:                       # EOF
                raise RuntimeError(f"[{self.id}] llama-cli finalizó prematuramente")
            if READY_MARKER in line:
                return

    # ──────────────────────────── inferencia ───────────────────────────────
    async def infer(self, prompt: str) -> AsyncIterator[str]:
        """
        Envia *prompt* y produce tokens conforme salen de stdout.
        """
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError(f"[{self.id}] worker no operativo")

        assert self.proc.stdin and self._queue

        # limpiar basura previa
        while not self._queue.empty():
            try: self._queue.get_nowait()
            except asyncio.QueueEmpty: break

        # enviar prompt
        self.proc.stdin.write(prompt.strip() + "\n")
        self.proc.stdin.flush()

        first_token = True
        while not self._ctl_event.is_set():
            stream, line = await self._queue.get()

            # EOF o error
            if line is None or (isinstance(line, str) and line.startswith("ERROR_READER")):
                self._ctl_event.set()
                break

            if stream == "stderr":
                continue                              # ignorar logs de stderr

            # filtrar ECO del prompt
            if first_token and line.strip() == prompt.strip():
                continue

            # fin de respuesta
            if line.strip() == REVERSE_PROMPT:
                break

            first_token = False
            yield line

    # ────────────────────────────── teardown ───────────────────────────────
    async def stop(self) -> None:
        """
        Intenta terminar el proceso limpiamente (SIGINT, SIGTERM, SIGKILL).
        """
        if not self.proc:
            return

        self._ctl_event.set()

        for task in (self._stdout_task, self._stderr_task):
            if task and not task.done():
                task.cancel()

        # Señales en cascada
        try:
            self.proc.send_signal(signal.SIGINT)
            await asyncio.to_thread(self.proc.wait, timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                self.proc.terminate()
                await asyncio.to_thread(self.proc.wait, timeout=3)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                self.proc.kill()
                await asyncio.to_thread(self.proc.wait)

        logger.info("[%s] proceso %s detenido (RC=%s)", self.id, self.proc.pid, self.proc.returncode)
        self.proc = None
