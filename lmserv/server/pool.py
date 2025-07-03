"""
lmserv.server.pool
==================
Orquestrador **asíncrono** de workers `llama-cli`.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Final

from ..config import Config
from .workers.llama import LlamaWorker

logger = logging.getLogger(__name__)

class WorkerPool:
    """Pool FIFO que reutiliza procesos `llama-cli`."""
    _START_TIMEOUT_S: Final[float] = 60.0

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._workers: list[LlamaWorker] = [LlamaWorker(cfg) for _ in range(cfg.workers)]
        self.free: asyncio.Queue[LlamaWorker] = asyncio.Queue()
        self.busy: set[LlamaWorker] = set()
        self._started = False

    async def start(self) -> None:
        if self._started:
            logger.warning("WorkerPool.start() llamado dos veces; se ignora.")
            return
        async def _spawn(w: LlamaWorker) -> None:
            await w.spawn()
            await self.free.put(w)
        await asyncio.gather(*[_spawn(w) for w in self._workers])
        self._started = True
        logger.info("WorkerPool: %s workers en marcha.", len(self._workers))

    async def shutdown(self) -> None:
        logger.info("WorkerPool.shutdown() …")
        await asyncio.gather(*[w.stop() for w in self._workers], return_exceptions=True)
        self._workers.clear()
        while not self.free.empty():
            try:
                self.free.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.busy.clear()
        self._started = False
        logger.info("WorkerPool terminado.")

    async def acquire(self) -> LlamaWorker:
        """Obtiene un worker libre (FIFO)."""
        w = await self.free.get()
        self.busy.add(w)
        return w

    async def release(self, w: LlamaWorker) -> None:
        """Devuelve un worker al pool. Si el proceso ha muerto, lo reemplaza."""
        # A worker is only unstable if its underlying process has actually died.
        if w.proc is None or w.proc.poll() is not None:
            logger.warning("Worker %s inestable; respawn …", w.id)
            try:
                await w.stop()
            except Exception as exc:
                logger.exception("Error parando worker %s: %s", w.id, exc)
            new_w = LlamaWorker(self._cfg)
            await new_w.spawn()
            w = new_w
        if w in self.busy:
            self.busy.remove(w)
        await self.free.put(w)

    @property
    def size(self) -> int:
        return len(self._workers)

    def __iter__(self) -> Iterable[LlamaWorker]:
        return iter(self._workers)

__all__ = ["WorkerPool"]