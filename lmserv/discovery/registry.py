# lmserv/discovery/registry.py
from __future__ import annotations
import threading
import time
from collections import OrderedDict
from typing import Iterable, List
from .mdns import NodeInfo, discover_nodes

_DEFAULT_TTL_S: int = 60
_REFRESH_INTERVAL_S: int = 30

class _Registry:
    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._store: "OrderedDict[str, tuple[NodeInfo, float]]" = OrderedDict()

    def upsert(self, nodes: Iterable[NodeInfo]) -> None:
        now = time.time()
        with self._lock:
            for n in nodes:
                key = f"{n.host}:{n.port}"
                self._store[key] = (n, now + self._ttl)
            self._purge_locked(now)

    def list_alive(self) -> List[NodeInfo]:
        with self._lock:
            self._purge_locked(time.time())
            return [info for info, _ in self._store.values()]

    def _purge_locked(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._store.items() if exp < now]
        for k in expired:
            self._store.pop(k, None)

REGISTRY = _Registry(_DEFAULT_TTL_S)

def _background_refresh() -> None:
    while True:
        try:
            nodes = discover_nodes(timeout=2)
            if nodes:
                REGISTRY.upsert(nodes)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("discover_nodes() falló: %s", exc)
        time.sleep(_REFRESH_INTERVAL_S)

import threading as _thr
_thread = _thr.Thread(target=_background_refresh, daemon=True, name="lmserv-registry")
_thread.start()