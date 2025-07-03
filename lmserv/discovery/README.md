
# `lmserv.discovery` – auto-descubrimiento de nodos

> “¡Que los servidores se encuentren solos!”  
> Este paquete implementa **mDNS/Zeroconf** para que varias instancias
> de LMServ dentro de la misma sub-red se detecten y compartan su
> endpoint `/chat` sin configuración manual.

---

## Qué encontrarás aquí

```

discovery/
├── **init**.py   ← re-exporta NodeInfo, discover\_nodes
├── mdns.py       ← anuncio + escáner Zeroconf
└── registry.py   ← caché en RAM con TTL + refresco background

````

| Archivo | Rol | ~líneas |
|---------|-----|---------|
| `mdns.py` | Publica `_lmserv._tcp.local.` y busca peers | 140 |
| `registry.py` | Mantiene lista viva de nodos activos | 120 |

---

## Uso básico

```python
from lmserv.discovery.mdns import announce_self, discover_nodes

# anunciar este nodo (una sola vez al arrancar FastAPI)
announce_self(port=8000, info="gpu-box-01")

# buscar otros servidores (bloquea 3 s)
peers = discover_nodes(timeout=3)
print(peers)  # → [NodeInfo(host='192.168.1.42', port=8000, info='gpu-box-02')]
````

`registry.REGISTRY` mantiene de forma automática una lista fresca
(gracias a un hilo *daemon* que escanea cada 30 s):

```python
from lmserv.discovery.registry import REGISTRY

for node in REGISTRY.list_alive():
    print(node.host, node.port, node.info)
```

---

## Cómo funciona

1. **Announce** – `ServiceInfo` con `_lmserv._tcp.local.`
   *TXT record* incluye un campo `info=<texto libre>`.
2. **Browse** – `ServiceBrowser` escucha paquetes mDNS → `NodeInfo`.
3. **Registry** – cada nodo descubierto obtiene un TTL (60 s por defecto).
   Si en el siguiente refresco no reaparece, se elimina.

<p align="center">
  <img src="../docs/discovery-seq.svg" width="620" alt="Sequence: announce / browse / registry" />
</p>

---

## Requisitos

* **python-zeroconf** (puro-Python, se instala como dependencia).
* Puerto mDNS 5353 UDP abierto en la red local.
* No requiere privilegios de root ni cambios de firewall para LAN típica.

---

## Cambios recientes

| Fecha        | Autor       | Descripción                                          |
| ------------ | ----------- | ---------------------------------------------------- |
| 2024-06-\*\* | @tu-usuario | Primer versión de `registry.py` con TTL configurable |

---

## Pendiente

* [ ] Fallback a **ARP scan** si mDNS está bloqueado.
* [ ] Modo “mesh” con anuncios periódicos vía WebSocket.
* [ ] CLI `lmserv discover --json` para parsear en scripts.

---

> *Tip*
> Si ejecutas LMServ dentro de un contenedor Docker, expón la interfaz
> `--network host` o publica el puerto mDNS con `--publish 5353:5353/udp`
> para que Zeroconf funcione fuera del contenedor.

