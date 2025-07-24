# lmserv/server/workers/llama.py
from __future__ import annotations
import asyncio
import logging
import os
import signal
import subprocess
import uuid
from pathlib import Path
from typing import AsyncIterator

from ...config import Config
from .utils import _stream_reader

logger = logging.getLogger(__name__)

READY_MARKER = "== Running in interactive mode. =="
REVERSE_PROMPT = "<|LMSERV_USER_INPUT_START|>" # This is no longer used to break the loop

class LlamaWorker:
    """Un proceso `llama-cli`."""
    def __init__(self, cfg: Config) -> None:
        self.id: str = uuid.uuid4().hex[:8]
        self.cfg = cfg
        self.proc: subprocess.Popen[str] | None = None
        self._ctl_event = asyncio.Event()
        self._queue: asyncio.Queue[tuple[str, str | None]] | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

    async def spawn(self) -> None:
        cmd = [
            self.cfg.llama_bin, "-m", self.cfg.model_path, "-i",
            "--interactive-first", "-n", str(self.cfg.max_tokens),
            "--reverse-prompt", REVERSE_PROMPT, "-ngl", "100",
            "-mg", str(self.cfg.gpu_idx),
        ]
        logger.info("[%s] spawn → %s", self.id, " ".join(cmd))
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            encoding="utf-8", errors="replace", creationflags=creation_flags
        )
        self._queue = asyncio.Queue()
        self._stdout_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, self._queue, self.id, "stdout", self._ctl_event)
        )
        self._stderr_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, self._queue, self.id, "stderr", self._ctl_event)
        )
        try:
            await asyncio.wait_for(self._wait_ready(), timeout=45)
        except asyncio.TimeoutError:
            raise RuntimeError(f"[{self.id}] llama-cli no respondió en 45 s")
        logger.info("[%s] listo para inferencia.", self.id)

    async def _wait_ready(self) -> None:
        assert self._queue
        while True:
            _, line = await self._queue.get()
            if line is None:
                raise RuntimeError(f"[{self.id}] llama-cli finalizó prematuramente")
            if READY_MARKER in line:
                return

    async def infer(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError(f"[{self.id}] worker no operativo")
        assert self.proc.stdin and self._queue

        self._ctl_event.clear()

        while not self._queue.empty():
            try: self._queue.get_nowait()
            except asyncio.QueueEmpty: break

        full_input = f"{prompt.strip()}{os.linesep}"
        print(f"DEBUG [WORKER {self.id}]: Sending input: {full_input!r}")
        self.proc.stdin.write(full_input)
        self.proc.stdin.flush()

        first_token = True
        try:
            while not self._ctl_event.is_set():
                try:
                    # --- THIS IS THE FIX ---
                    # Wait for a new line, but with a timeout.
                    # If the model stops talking for 2 seconds, we assume it's done.
                    stream, line = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                    # --- END FIX ---
                    
                    print(f"DEBUG [WORKER {self.id}]: Received line: {line!r} from {stream}")

                    if line is None or (isinstance(line, str) and line.startswith("ERROR_READER")):
                        break
                    if stream == "stderr":
                        continue
                    if first_token and line.strip() == prompt.strip():
                        continue
                    # The reverse prompt check is now a secondary stop condition, not the primary one.
                    if line.strip() == REVERSE_PROMPT:
                        break
                    first_token = False
                    yield line
                except asyncio.TimeoutError:
                    print(f"DEBUG [WORKER {self.id}]: Timeout waiting for queue item. Assuming end of generation.")
                    break # Exit the loop if the model is silent
        finally:
            print(f"DEBUG [WORKER {self.id}]: Exiting infer loop.")
            self._ctl_event.set()

    async def stop(self) -> None:
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