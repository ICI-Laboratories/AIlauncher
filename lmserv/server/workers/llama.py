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
    return 50


import json
from ...gbnf import schema_to_gbnf

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
        self.grammar: str | None = None
        self.system_prompt: str = "You are a helpful assistant."

    def _prepare_tools(self):
        """Carga las herramientas, genera la gramática GBNF y el system prompt."""
        if not self.cfg.tools_path:
            return

        logger.info("[%s] Cargando herramientas desde %s", self.id, self.cfg.tools_path)
        with open(self.cfg.tools_path, "r", encoding="utf-8") as f:
            tools_def = json.load(f)

        tool_schemas = tools_def.get("tools", [])
        if not tool_schemas:
            return

        # Construye el master schema
        tool_names = [tool["name"] for tool in tool_schemas]
        master_schema = {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "tool_call": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": tool_names},
                        "arguments": {
                            "oneOf": [tool["parameters"] for tool in tool_schemas]
                        }
                    },
                    "required": ["name", "arguments"]
                }
            },
            "required": ["thought"]
        }

        self.grammar = schema_to_gbnf(master_schema)

        # Construye el system prompt
        prompt_parts = [
            "You have access to the following tools. You must respond in JSON format that matches the specified schema.",
            "The JSON object must have a 'thought' field and may optionally have a 'tool_call' field.",
            "Available tools:",
            json.dumps(tools_def, indent=2)
        ]
        self.system_prompt = "\n".join(prompt_parts)
        logger.info("[%s] Gramática y system prompt para herramientas generados.", self.id)


    async def spawn(self) -> None:
        """Lanza `llama-cli` con el modelo indicado (local o remoto HF)."""
        self._prepare_tools()

        # --- Argumentos del Modelo ---
        model_identifier = self.cfg.model
        if _looks_like_hf_repo(model_identifier):
            repo = _strip_hf_prefix(model_identifier)
            logger.info("[%s] Usando modelo de Hugging Face: %s", self.id, repo)
            model_arg = ["--hf-repo", repo]
        else:
            p = Path(model_identifier)
            if not p.is_file():
                raise FileNotFoundError(f"Modelo local no encontrado en {p.resolve()}")
            logger.info("[%s] Usando modelo local: %s", self.id, p.resolve())
            model_arg = ["--model", str(p.resolve())]

        # --- Argumentos de Llama.cpp ---
        llama_args = [
            "--interactive",
            "--interactive-first",
            "--reverse-prompt", REVERSE_PROMPT,
            "--n-predict", str(self.cfg.max_tokens),
            "--ctx-size", str(self.cfg.ctx_size),
            "--n-gpu-layers", str(self.cfg.n_gpu_layers),
        ]
        if self.cfg.lora:
            lora_path = Path(self.cfg.lora)
            if not lora_path.is_file():
                raise FileNotFoundError(f"Fichero LoRA no encontrado en {lora_path.resolve()}")
            llama_args.extend(["--lora", str(lora_path.resolve())])

        if self.grammar:
            llama_args.extend(["--grammar", self.grammar])

        cmd = [self.cfg.llama_bin, *model_arg, *llama_args]

        logger.info("[%s] spawn → %s", self.id, " ".join(map(str, cmd)))

        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        preexec = os.setsid if os.name != "nt" else None

        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            encoding="utf-8", errors="replace",
            creationflags=creation_flags, preexec_fn=preexec,
        )

        self._queue = asyncio.Queue()
        self._stdout_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, self._queue, self.id, "stdout", self._ctl_event)
        )
        self._stderr_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, self._queue, self.id, "stderr", self._ctl_event)
        )

        try:
            await asyncio.wait_for(self._wait_ready(), timeout=600)
        except asyncio.TimeoutError:
            raise RuntimeError(f"[{self.id}] llama-cli no respondió en 10 minutos.")
        
        logger.info("[%s] listo para inferencia.", self.id)

    async def _wait_ready(self) -> None:
        """Espera hasta ver un marcador de 'ready' o falla si el proceso muere."""
        assert self._queue and self.proc
        while True:
            rc = self.proc.poll()
            if rc is not None:
                err_tail: list[str] = []
                try:
                    for _ in range(200):
                        stream, line = self._queue.get_nowait()
                        if stream == "stderr" and line:
                            err_tail.append(line.strip())
                except asyncio.QueueEmpty:
                    pass
                msg = "\n".join(err_tail[-40:]) if err_tail else "(sin stderr)"
                raise RuntimeError(f"[{self.id}] llama-cli terminó prematuramente (rc={rc}).\n{msg}")

            _, line = await self._queue.get()
            if line is None:
                raise RuntimeError(f"[{self.id}] llama-cli finalizó prematuramente")
            
            if any(marker in line for marker in READY_MARKERS):
                return

    async def infer(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError(f"[{self.id}] worker no operativo")
        assert self.proc.stdin and self._queue

        self._ctl_event.clear()

        while not self._queue.empty():
            try: self._queue.get_nowait()
            except asyncio.QueueEmpty: break

        # Prepend system prompt if it exists
        full_prompt = f"{self.system_prompt}\n\nUser: {prompt.strip()}"

        self.proc.stdin.write(f"{full_prompt}{os.linesep}")
        self.proc.stdin.flush()

        first_token = True
        try:
            while not self._ctl_event.is_set():
                try:
                    stream, line = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                    if line is None or (isinstance(line, str) and line.startswith("ERROR_READER")):
                        break
                    if stream == "stderr": continue
                    if first_token and line.strip() == prompt.strip(): continue
                    if line.strip() == REVERSE_PROMPT: break
                    first_token = False
                    yield line
                except asyncio.TimeoutError:
                    break
        finally:
            self._ctl_event.set()

    async def stop(self) -> None:
        if not self.proc: return
        self._ctl_event.set()
        for task in (self._stdout_task, self._stderr_task):
            if task and not task.done(): task.cancel()
        
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