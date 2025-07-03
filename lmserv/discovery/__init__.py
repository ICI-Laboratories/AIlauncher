from __future__ import annotations

from collections import namedtuple
from typing import List

from .mdns import discover_nodes

NodeInfo = namedtuple("NodeInfo", "host port info")

__all__: List[str] = ["discover_nodes", "NodeInfo"]