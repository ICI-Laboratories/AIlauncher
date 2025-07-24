# lmserv/server/workers/cpp_bridge.py
from __future__ import annotations
import importlib
import logging
import math
import random
from typing import List

logger = logging.getLogger(__name__)
HAS_CPP = False
_cpp_mod = None

try:
    _cpp_mod = importlib.import_module("lmserv_cpp")
    HAS_CPP = True
    logger.info("Extensión C++ ‘lmserv_cpp’ cargada ✔")
except ModuleNotFoundError:
    logger.warning("Extensión C++ no encontrada; usando implementaciones Python.")

def sample_top_p(logits: List[float], p: float = 0.9) -> int:
    if HAS_CPP:
        return int(_cpp_mod.sample_top_p(logits, p))

    probs = [math.exp(x) for x in logits]
    pairs = sorted(enumerate(probs), key=lambda t: t[1], reverse=True)

    cumulative = 0.0
    filtered: list[tuple[int, float]] = []
    for idx, pr in pairs:
        cumulative += pr
        filtered.append((idx, pr))
        if cumulative >= p:
            break

    total = sum(pr for _, pr in filtered)
    r = random.random() * total
    upto = 0.0
    for idx, pr in filtered:
        upto += pr
        if upto >= r:
            return idx
    return filtered[-1][0]

def tokenize(text: str) -> List[int]:
    if HAS_CPP:
        return _cpp_mod.tokenize(text)
    return [hash(tok) & 0xFFFF for tok in text.split()]

__all__ = ["HAS_CPP", "sample_top_p", "tokenize"]