# lmserv/server/pool.py
from __future__ import annotations
import asyncio
import logging
from ..config import Config
from .workers.llama import LlamaWorker

logger = logging.getLogger(__name__)

class WorkerPool:
    """
    Pool que gestiona un número finito de procesos `llama-cli` persistentes.
    """
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._workers: list[LlamaWorker] = []
        self.free: asyncio.Queue[LlamaWorker] = asyncio.Queue()
        self.busy: set[LlamaWorker] = set()
        print("DEBUG [POOL]: Stateful WorkerPool created.")

    async def start(self) -> None:
        """Lanza todos los procesos `llama-cli` y los añade al pool."""
        self._workers = [LlamaWorker(self._cfg) for _ in range(self._cfg.workers)]
        try:
            await asyncio.gather(*[w.spawn() for w in self._workers])
            for w in self._workers:
                await self.free.put(w)
            logger.info("WorkerPool: %s workers persistentes en marcha.", len(self._workers))
        except Exception as e:
            logger.error(f"Failed to start workers: {e}")
            await self.shutdown() # Cleanup on failure
            raise

    async def shutdown(self) -> None:
        """Detiene todos los procesos worker."""
        logger.info("WorkerPool.shutdown() …")
        await asyncio.gather(*[w.stop() for w in self._workers], return_exceptions=True)
        self._workers.clear()
        while not self.free.empty():
            try:
                self.free.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.busy.clear()
        logger.info("WorkerPool terminado.")

    async def acquire(self) -> LlamaWorker:
        """Toma un worker de la cola, esperando si es necesario."""
        worker = await self.free.get()
        self.busy.add(worker)
        return worker

    async def release(self, worker: LlamaWorker) -> None:
        """
        Devuelve un worker a la cola. Si el proceso ha muerto, lo reemplaza.
        """
        if worker.proc is None or worker.proc.poll() is not None:
            logger.warning(f"Worker {worker.id} is unstable; respawning…")
            self.busy.remove(worker)
            try:
                await worker.stop()
            except Exception as e:
                logger.error(f"Error stopping unstable worker {worker.id}: {e}")
            
            new_worker = LlamaWorker(self._cfg)
            await new_worker.spawn()
            await self.free.put(new_worker)
        else:
            if worker in self.busy:
                self.busy.remove(worker)
            await self.free.put(worker)