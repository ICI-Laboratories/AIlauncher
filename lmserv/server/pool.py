"""
lmserv.server.pool
==================
Orquestrador **asíncrono** de workers `llama-cli`.

• Cada worker es un proceso independiente (véase
  `lmserv.server.workers.llama.LlamaWorker`).
• La clase expone métodos **start / acquire / release / shutdown**.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Final

from ..config import Config
from .workers.llama import LlamaWorker

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# WorkerPool
# ──────────────────────────────────────────────────────────────────────────────
class WorkerPool:
    """
    Pool FIFO que reutiliza procesos `llama-cli`.

    Ejemplo
    -------
    ```python
    cfg   = Config()
    pool  = WorkerPool(cfg)
    await pool.start()

    w = await pool.acquire()
    async for tok in w.infer("Hola"):
        print(tok)
    await pool.release(w)

    await pool.shutdown()
    ```
    """

    _START_TIMEOUT_S: Final[float] = 60.0

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._workers: list[LlamaWorker] = [LlamaWorker(cfg) for _ in range(cfg.workers)]
        self.free: asyncio.Queue[LlamaWorker] = asyncio.Queue()
        self.busy: set[LlamaWorker] = set()
        self._started = False

    # --------------------------------------------------------------------- #
    # Life-cycle
    # --------------------------------------------------------------------- #
    async def start(self) -> None:
        """
        Lanza todos los procesos `llama-cli` en paralelo.

        La llamada retorna cuando **todos** están listos.
        """
        if self._started:  # pragma: no cover
            logger.warning("WorkerPool.start() llamado dos veces; se ignora.")
            return

        async def _spawn(w: LlamaWorker) -> None:
            await w.spawn()
            await self.free.put(w)

        await asyncio.gather(*[_spawn(w) for w in self._workers])
        self._started = True
        logger.info("WorkerPool: %s workers en marcha.", len(self._workers))

    async def shutdown(self) -> None:
        """
        Detiene todos los procesos y limpia colas internas.
        """
        logger.info("WorkerPool.shutdown() …")
        await asyncio.gather(*[w.stop() for w in self._workers], return_exceptions=True)
        self._workers.clear()
        while not self.free.empty():
            try:
                self.free.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover
                break
        self.busy.clear()
        self._started = False
        logger.info("WorkerPool terminado.")

    # --------------------------------------------------------------------- #
    # Borrow / return
    # --------------------------------------------------------------------- #
    async def acquire(self) -> LlamaWorker:
        """
        Obtiene un worker libre (FIFO).  Espera indefinidamente.
        """
        w = await self.free.get()
        self.busy.add(w)
        logger.debug("WorkerPool.acquire() → %s busy=%d", w.id, len(self.busy))
        return w

    async def release(self, w: LlamaWorker) -> None:
        """
        Devuelve un *worker* al elenco de libres.

        Si el worker está marcado como “muerto” (proc_control_event),
        se descarta y se crea uno nuevo *on the fly* para mantener el
        pool en el tamaño configurado.
        """
        if w.proc_control_event.is_set() or w.proc is None or w.proc.poll() is not None:
            logger.warning("Worker %s inestable; respawn …", w.id)
            try:
                await w.stop()
            except Exception as exc:  # pragma: no cover
                logger.exception("Error parando worker %s: %s", w.id, exc)

            # Reemplazar por uno nuevo
            new_w = LlamaWorker(self._cfg)
            await new_w.spawn()
            w = new_w

        if w in self.busy:
            self.busy.remove(w)
        await self.free.put(w)
        logger.debug("WorkerPool.release() ← %s busy=%d", w.id, len(self.busy))

    # --------------------------------------------------------------------- #
    # Introspection helpers
    # --------------------------------------------------------------------- #
    @property
    def size(self) -> int:  # noqa: D401
        return len(self._workers)

    def __iter__(self) -> Iterable[LlamaWorker]:  # noqa: D401
        return iter(self._workers)


__all__ = ["WorkerPool"]
