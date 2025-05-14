"""Pool simple que orquesta varios LlamaWorker."""
from __future__ import annotations
import asyncio
from .worker import LlamaWorker
from .config import Config

class WorkerPool:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._workers = [LlamaWorker(cfg.model_path, cfg.gpu_idx) for _ in range(cfg.workers)]
        self.free: asyncio.Queue[LlamaWorker] = asyncio.Queue()
        self.busy: set[LlamaWorker] = set()

    async def start(self):
        for w in self._workers:
            await w.spawn()
            await self.free.put(w)

    async def acquire(self) -> LlamaWorker:
        w = await self.free.get()
        self.busy.add(w)
        return w

    async def release(self, w: LlamaWorker):
        self.busy.discard(w)
        await self.free.put(w)

    async def shutdown(self):
        for w in self._workers:
            await w.stop()