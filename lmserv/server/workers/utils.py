"""
lmserv.server.workers.utils
===========================

Funciones utilitarias compartidas por las distintas clases *Worker*.

Por ahora se limita a:

* `_stream_reader` – corrutina que lee un `TextIO` (stdout/stderr)
  y “empuja” líneas a una `asyncio.Queue` en cuanto llegan
  (útil para _streaming_ token-a-token).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TextIO

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Stream reader
# ──────────────────────────────────────────────────────────────────────────────
async def _stream_reader(
    stream: TextIO,
    queue: asyncio.Queue[tuple[str, str | None]],
    worker_id: str,
    stream_name: str,
    proc_control_event: asyncio.Event,
) -> None:
    """
    Lee el `stream` línea-a-línea y coloca tuplas en `queue`.
    """
    loop = asyncio.get_event_loop()

    try:
        while not proc_control_event.is_set():
            line = await loop.run_in_executor(None, stream.readline)

            # --- DEBUG PRINT ---
            # This will show you every line received from the llama-cli process
            if line:
                print(f"DEBUG [WORKER {worker_id}/{stream_name}]: {line.strip()!r}")
            # --- END DEBUG ---

            if not line:
                logger.debug("[%s/%s] EOF", worker_id, stream_name)
                await queue.put((stream_name, None))
                break

            await queue.put((stream_name, line.rstrip("\n")))

    except Exception as exc:  # pragma: no cover
        if not proc_control_event.is_set():
            msg = f"ERROR_READER: {exc!r}"
            logger.error("[%s/%s] %s", worker_id, stream_name, msg)
            await queue.put((stream_name, msg))

    finally:
        proc_control_event.set()
        logger.debug("[%s/%s] _stream_reader terminado.", worker_id, stream_name)