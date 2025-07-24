## discovery-README.md

---

### 1  Overview
1
`lmserv.discovery` is the **LAN-discovery subsystem**.
It solves two related problems:

1. **Announcing your own server** – so other LMServ instances can find you.
2. **Discovering other servers** – and keeping a *fresh* in-memory registry of all live peers.

It relies on **mDNS/Zero-configuration networking** (via the `zeroconf` library) and uses the well-known service type:

```
_lmserv._tcp.local.
```

---

### 2  Key Public APIs

| Symbol                                              | Defined in                | Purpose                                                                         |                                    |
| --------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------- | ---------------------------------- |
| `announce_self(port: int, info: str = "")`          | `mdns.py`                 | Broadcasts *this* node on the LAN. Call once after the HTTP server starts.      |                                    |
| `discover_nodes(timeout: int = 5) → list[NodeInfo]` | `mdns.py`                 | Actively scans the LAN for peers and returns their `(host, port, info)` tuples. |                                    |
| `NodeInfo`                                          | `mdns.py` & `__init__.py` | Typed NamedTuple \`(host: str, port: int, info: str                             | None)\`. Exposed for external use. |
| `REGISTRY`                                          | `registry.py`             | Thread-safe, auto-refreshing cache of live nodes.                               |                                    |
| `REGISTRY.list_alive() → list[NodeInfo]`            | `registry.py`             | Snapshot of all peers seen within the last *TTL* seconds.                       |                                    |

All essential symbols (`discover_nodes`, `NodeInfo`) are re-exported in `lmserv.discovery.__init__`, so callers can simply:

```python
from lmserv.discovery import announce_self, discover_nodes, NodeInfo
```

---

### 3  How It Works Internally

#### 3.1 Announcement (`announce_self`)

1. Grabs the first **non-loopback IPv4** address of the host.
2. Registers a `zeroconf.ServiceInfo` under `_lmserv._tcp.local.` with:

   * Address   → host IP
   * Port      → your HTTP/API port
   * TXT record `info` → arbitrary descriptive string (model name, etc.)
3. A module-level singleton ensures it only broadcasts once.

#### 3.2 Active Discovery (`discover_nodes`)

* Spawns a temporary asyncio event loop.
* Runs a `zeroconf.ServiceBrowser` for the same service type.
* Collects unique peers for *`timeout`* seconds.
* Returns a deduplicated `list[NodeInfo]`.

#### 3.3 Background Registry (`registry.py`)

* A private `_Registry` keeps an **OrderedDict \<node, expires-at>**.
* Each import of `lmserv.discovery.registry` starts a **daemon thread** that:

  1. Calls `discover_nodes(timeout=2)` every 30 s (`_REFRESH_INTERVAL_S`).
  2. `upsert`s fresh nodes and purges expired ones (`_DEFAULT_TTL_S` = 60 s).

Because the thread is a daemon, it will not prevent process shutdown.

---

### 4  Configuration Knobs

| Constant              | Meaning                                            | Default |
| --------------------- | -------------------------------------------------- | ------- |
| `_DEFAULT_TTL_S`      | Seconds a node is considered alive without refresh | **60**  |
| `_REFRESH_INTERVAL_S` | How often the background thread rescans the LAN    | **30**  |

Override them in code **before** importing `lmserv.discovery.registry` if you need different values.

---

### 5  Typical Usage

```python
# server.py (snippet)

from lmserv.discovery import announce_self
from lmserv.discovery.registry import REGISTRY

# 1. Start your FastAPI server on PORT
PORT = 8000
...

# 2. Broadcast yourself once the port is bound
announce_self(PORT, info="gemma-2b-it Q4_0")

# 3. Anywhere in your app: ask who else is alive
for node in REGISTRY.list_alive():
    print(f"Found peer @ http://{node.host}:{node.port}  ({node.info})")
```

No manual cleanup is required—the registry prunes itself.

---

### 6  Extending / Debugging

* **Logging** – all modules honor the root logger.

  ```bash
  export LOGLEVEL=DEBUG
  ```

  will show announce/discovery activity.

* **Custom Service Type** – change `_SERVICE_TYPE` in `mdns.py` if you must coexist with non-LMServ services.

* **Unit Testing** – inject a fake `Zeroconf` via monkeypatching to avoid network I/O.

---

### 7  Dependencies

* `zeroconf` ≥ 0.60.0
* Standard library: `asyncio`, `socket`, `ipaddress`, `threading`, `logging`

---

### 8  Gotchas & Limitations

* **mDNS traffic is limited to the local subnet**; discovery won’t cross routers without specific configuration.
* Multiple network interfaces: only the first non-loopback IPv4 is announced.
* Windows: make sure the *“Function Discovery Service”* is enabled or mDNS may be blocked.

---

### 9  Changelog

| Version | Change                                                 |
| ------- | ------------------------------------------------------ |
| `v1.0`  | Initial implementation (announce, discover, registry). |

---

**TL;DR**
Import `announce_self()` when you start the server, query `REGISTRY.list_alive()` whenever you need peers, and the discovery subsystem takes care of the rest.
