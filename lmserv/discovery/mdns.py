from __future__ import annotations
import asyncio
import ipaddress
import logging
import socket
from contextlib import suppress
from typing import List, NamedTuple
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)
_SERVICE_TYPE = "_lmserv._tcp.local."

class NodeInfo(NamedTuple):
    host: str
    port: int
    info: str | None = None

_zeroconf_singleton: Zeroconf | None = None
_service_info: ServiceInfo | None = None

def announce_self(port: int, info: str = "") -> None:
    global _zeroconf_singleton, _service_info
    if _zeroconf_singleton:
        logger.debug("announce_self() ya fue ejecutado, se ignora.")
        return

    hostname = socket.gethostname()
    host_ip = _first_non_loopback_ip()
    logger.info("Anunciando nodo LMServ %s:%s (%s)", host_ip, port, info or "sin descripción")

    _zeroconf_singleton = Zeroconf()
    _service_info = ServiceInfo(
        type_=_SERVICE_TYPE,
        name=f"{hostname}.{_SERVICE_TYPE}",
        addresses=[socket.inet_aton(host_ip)],
        port=port,
        properties={"info": info.encode("utf-8")},
    )
    _zeroconf_singleton.register_service(_service_info)

def _first_non_loopback_ip() -> str:
    for fam, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
        if fam == socket.AF_INET:
            ip = sockaddr[0]
            if not ipaddress.ip_address(ip).is_loopback:
                return ip
    return "127.0.0.1"

class _Collector:
    def __init__(self) -> None:
        self.nodes: list[NodeInfo] = []
        self._seen: set[str] = set()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        with suppress(Exception):
            info = zc.get_service_info(type_, name, timeout=1000)
            if not info:
                return
            host = socket.inet_ntoa(info.addresses[0])
            port = info.port
            desc = info.properties.get(b"info", b"").decode("utf-8")
            key = f"{host}:{port}"
            if key not in self._seen:
                self.nodes.append(NodeInfo(host, port, desc))
                self._seen.add(key)

def discover_nodes(timeout: int = 5) -> List[NodeInfo]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    zc = Zeroconf()
    collector = _Collector()
    browser = ServiceBrowser(zc, _SERVICE_TYPE, handlers=[collector.add_service])

    try:
        loop.run_until_complete(asyncio.sleep(timeout))
    finally:
        browser.cancel()
        zc.close()
        loop.close()

    return collector.nodes