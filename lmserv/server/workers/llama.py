# lmserv/server/workers/llama.py
from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
import uuid
from pathlib import Path
from typing import AsyncIterator

from ...config import Config
from .utils import _stream_reader

logger = logging.getLogger(__name__)

# Marcadores que indican que llama-cli ya está listo en modo interactivo
READY_MARKERS = (
    "== Running in interactive mode. ==",
    "interactive mode",
    "Reverse prompt:",
    "sampling:",
)

REVERSE_PROMPT = "<|LMSERV_USER_INPUT_START|>"


def _looks_like_hf_repo(s: str) -> bool:
    """Heurística para detectar identificadores de Hugging Face (owner/repo[:variant])."""
    if s.startswith(("hf:", "hf/", "huggingface:")):
        return True
    return bool(re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+($|[:/])", s))


def _strip_hf_prefix(s: str) -> str:
    for pref in ("hf:", "huggingface:", "hf/"):
        if s.startswith(pref):
            return s[len(pref) :]
    return s


def _default_ngl_for_vram(vram_mb: int) -> int:
    """Heurística conservadora para -ngl según VRAM disponible."""
    if vram_mb < 8_000:
        return 0
    if vram_mb < 12_000:
        return 20
    if vram_mb < 20_000:
        return 35
    return 50  # 24 GB+


class LlamaWorker:
    """Gestiona un proceso `llama-cli` y su IO asíncrono."""

    def __init__(self, cfg: Config) -> None:
        self.id: str = uuid.uuid4().hex[:8]
        self.cfg = cfg
        self.proc: subprocess.Popen[str] | None = None
        self._ctl_event = asyncio.Event()
        self._queue: asyncio.Queue[tuple[str, str | None]] | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

    async def spawn(self) -> None:
        """Lanza `llama-cli` con el modelo indicado (local o remoto HF)."""
        # ── Selección de modelo: remoto (HF) vs local ──
        model_identifier = self.cfg.model
        if _looks_like_hf_repo(model_identifier):
            repo = _strip_hf_prefix(model_identifier)
            logger.info("[%s] Usando modelo de Hugging Face: %s", self.id, repo)
            model_arg = ["-hf", repo]
        else:
            p = Path(model_identifier)
            if not p.exists():
                logger.error("[%s] Ruta al modelo local no existe: %s", self.id, model_identifier)
                raise FileNotFoundError(f"Modelo local no encontrado en {model_identifier}")
            logger.info("[%s] Usando modelo local: %s", self.id, model_identifier)
            model_arg = ["-m", str(p)]

        # ── Flags de GPU ──
        ngl = int(os.getenv("NGPU_LAYERS", _default_ngl_for_vram(self.cfg.vram_cap_mb)))
        gpu_flags: list[str] = ["-ngl", str(ngl)]
        if self.cfg.gpu_idx:
            gpu_flags += ["-mg", str(self.cfg.gpu_idx)]  # Main GPU

        # ── Comando final ──
        cmd = [
            self.cfg.llama_bin,
            *model_arg,
            "-i",
            "--interactive-first",
            "-n",
            str(self.cfg.max_tokens),
            "--reverse-prompt",
            REVERSE_PROMPT,
            *gpu_flags,
        ]

        logger.info("[%s] spawn → %s", self.id, " ".join(map(str, cmd)))

        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        preexec = os.setsid if os.name != "nt" else None

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
            preexec_fn=preexec,
        )

        self._queue = asyncio.Queue()
        self._stdout_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, self._queue, self.id, "stdout", self._ctl_event)
        )
        self._stderr_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, self._queue, self.id, "stderr", self._ctl_event)
        )

        # La primera ejecución con -hf puede descargar el modelo: damos margen amplio
        try:
            await asyncio.wait_for(self._wait_ready(), timeout=600)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"[{self.id}] llama-cli no respondió en 10 minutos. La descarga/arranque del modelo pudo haber fallado."
            )
        logger.info("[%s] listo para inferencia.", self.id)

    async def _wait_ready(self) -> None:
        """Espera hasta ver un marcador de 'ready' o falla si el proceso muere."""
        assert self._queue and self.proc
        while True:
            # Fail-fast si el proceso terminó prematuramente
            rc = self.proc.poll()
            if rc is not None:
                # Intenta extraer algo de stderr para diagnóstico
                err_tail: list[str] = []
                try:
                    for _ in range(200):  # drenar hasta ~200 líneas recientes si están en la cola
                        stream, line = self._queue.get_nowait()
                        if stream == "stderr" and line:
                            err_tail.append(line.strip())
                except asyncio.QueueEmpty:
                    pass
                msg = "\n".join(err_tail[-40:]) if err_tail else "(sin stderr)"
                raise RuntimeError(
                    f"[{self.id}] llama-cli terminó prematuramente (rc={rc}). "
                    f"Últimas líneas de stderr:\n{msg}"
                )

            stream, line = await self._queue.get()
            if line is None:
                raise RuntimeError(f"[{self.id}] llama-cli finalizó prematuramente")
            if stream != "stderr" and any(marker in line for marker in READY_MARKERS):
                return

    async def infer(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        """Envía un prompt y *streamea* los tokens de salida."""
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError(f"[{self.id}] worker no operativo")
        assert self.proc.stdin and self._queue

        self._ctl_event.clear()

        # Vacía el buffer antes de escribir
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        full_input = f"{prompt.strip()}{os.linesep}"
        self.proc.stdin.write(full_input)
        self.proc.stdin.flush()

        first_token = True
        try:
            while not self._ctl_event.is_set():
                try:
                    stream, line = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                    if line is None or (isinstance(line, str) and line.startswith("ERROR_READER")):
                        break
                    if stream == "stderr":
                        continue
                    # filtra el eco del prompt
                    if first_token and line.strip() == prompt.strip():
                        continue
                    # fin de turno cuando aparece el reverse prompt
                    if line.strip() == REVERSE_PROMPT:
                        break
                    first_token = False
                    yield line
                except asyncio.TimeoutError:
                    break
        finally:
            self._ctl_event.set()

    async def stop(self) -> None:
        """Detiene con cuidado el proceso y limpia tareas lectoras."""
        if not self.proc:
            return
        self._ctl_event.set()
        for task in (self._stdout_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        try:
            sig = signal.CTRL_C_EVENT if os.name == "nt" else signal.SIGINT
            self.proc.send_signal(sig)
            await asyncio.to_thread(self.proc.wait, timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError, ValueError):
            try:
                self.proc.terminate()
                await asyncio.to_thread(self.proc.wait, timeout=3)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                self.proc.kill()
                await asyncio.to_thread(self.proc.wait)
        logger.info("[%s] proceso %s detenido (RC=%s)", self.id, self.proc.pid, self.proc.returncode)
        self.proc = None
