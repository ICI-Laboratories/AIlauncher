"""
Tests de alto nivel sobre `WorkerPool`.

Los workers reales están *mockeados* (ver `conftest.py`) para que cada
uno:

* haga `spawn()` instantáneo,
* devuelva los tokens `["Hola", "🙂"]` al inferir,
* y no requiera procesos externos.
"""
from __future__ import annotations

import asyncio

import pytest

from lmserv.config import Config
from lmserv.server.pool import WorkerPool


# ════════════════════════════════════════════════════════════════════════════
# Ciclo completo: start → acquire → infer → release → shutdown
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_pool_lifecycle() -> None:
    cfg = Config(workers=2)
    pool = WorkerPool(cfg)

    await pool.start()
    assert pool.size == 2
    assert pool.free.qsize() == 2

    # tomar un worker
    worker = await pool.acquire()
    assert pool.free.qsize() == 1
    assert worker in pool.busy

    # inferencia mock
    tokens = [t async for t in worker.infer("prueba")]
    assert tokens == ["Hola", "🙂"]

    # devolver al pool
    await pool.release(worker)
    assert worker not in pool.busy
    assert pool.free.qsize() == 2

    await pool.shutdown()
    assert pool.size == 0


# ════════════════════════════════════════════════════════════════════════════
# El pool debe reemplazar un worker marcado como “muerto”
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_pool_respawn_dead_worker() -> None:
    cfg = Config(workers=1)
    pool = WorkerPool(cfg)
    await pool.start()

    w = await pool.acquire()

    # Simular fallo fatal
    w.proc_control_event.set()

    # Al liberar, el pool debería respawnearlo
    await pool.release(w)
    new_worker = await pool.acquire()
    assert new_worker is not w  # reemplazado

    await pool.shutdown()
