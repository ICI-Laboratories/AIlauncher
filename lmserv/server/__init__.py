# lmserv/server/__init__.py
from __future__ import annotations

import logging
import os

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s | %(levelname)8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.debug("Logger inicializado con nivel %s", _LOG_LEVEL)

from .api import app
from .pool import WorkerPool

__all__ = [
    "app",
    "WorkerPool",
]