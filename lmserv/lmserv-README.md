## lmserv-README.md

> **Scope**: Everything in **`lmserv/`** (top-level package)
> **Mission**: Explain what the whole project is, how to run it from the CLI or as a library, and where every major sub-package lives—so readers don’t have to dig into source.

---

### 0  Directory structure

```
lmserv/
├── discovery/         # mDNS announce & peer discovery
│   └── discovery-README.md
├── install/           # llama.cpp build helper + GGUF model fetcher
│   └── install-README.md
├── server/            # FastAPI service, WorkerPool, workers
│   └── server-README.md
├── __init__.py        # Version, `Config`, `run_cli()`
├── cli.py             # Typer CLI entry-points (serve, install, discover, …)
├── config.py          # Typed runtime configuration
└── README.md          # <– this file
```

| Layer         | What it does                                  | Entry-points                                      |
| ------------- | --------------------------------------------- | ------------------------------------------------- |
| **Install**   | Compile `llama.cpp`, download verified models | `lmserv install llama/models`                     |
| **Discovery** | Broadcast & locate LMServ nodes on LAN        | `lmserv discover`                                 |
| **Server**    | Stream-style REST API backed by WorkerPool    | `lmserv serve` or `uvicorn lmserv.server.api:app` |

---

### 1  Quick start

```bash
# 1. Build llama.cpp (CUDA) & grab a model
python -m lmserv install llama   --output-dir build/ --cuda
python -m lmserv install models  gemma-2b --target-dir models/

# 2. Launch the HTTP service (2 workers on port 8000)
export API_KEY=mysecret
lmserv serve -m models/gemma-2b-it-q4_0.gguf -w 2 -p 8000

# 3. Talk to it
curl -N -H "X-API-Key: mysecret" \
     -d '{"prompt":"Hola, ¿cómo estás?"}' \
     -H "Content-Type: application/json" \
     http://localhost:8000/chat
```

Everything above is just syntactic sugar around pure-Python helpers—feel free to script them yourself.

---

### 2  Public Python API

| Symbol       | Where             | Why you’d import it                                                                |
| ------------ | ----------------- | ---------------------------------------------------------------------------------- |
| `Config`     | `lmserv.config`   | Resolve paths & environment into a dataclass (`model_path`, `workers`, `host`, …). |
| `run_cli()`  | `lmserv.__init__` | Launches the Typer CLI programmatically.                                           |
| `app`        | `lmserv.server`   | FastAPI application object (for Uvicorn/Gunicorn, testing).                        |
| `WorkerPool` | `lmserv.server`   | Manage persistent `llama-cli` processes yourself, outside FastAPI.                 |

```python
from lmserv import Config
cfg = Config(workers=1, model_path="models/gemma.gguf")

from lmserv.server import WorkerPool
pool = WorkerPool(cfg)
await pool.start()
worker = await pool.acquire()
async for tok in worker.infer("2+2="):
    print(tok, end="", flush=True)
await pool.release(worker)
await pool.shutdown()
```

---

### 3  The CLI in a nutshell

| Command                 | Flags (abridged)                                                                           | Purpose                                               |
| ----------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------- |
| `lmserv serve`          | `--model-path -m`, `--workers -w`, `--host -H`, `--port -p`, `--max-tokens`, `--llama-bin` | Spin up FastAPI + WorkerPool.                         |
| `lmserv install llama`  | `--output-dir -o`, `--cuda/--no-cuda`                                                      | Clone & build `llama.cpp`.                            |
| `lmserv install models` | `<names…>` `--target-dir -d`                                                               | Download GGUF models from built-in catalog.           |
| `lmserv discover`       | `--timeout -t`                                                                             | Scan LAN for other LMServ nodes via mDNS.             |
| `lmserv llama …`        | *(passthrough flags)*                                                                      | Call `llama-cli` directly (debug convenience).        |
| `lmserv update`         | —                                                                                          | `git pull` + `pip install -e .` for source checkouts. |

All commands are defined in **`cli.py`** using [Typer](https://typer.tiangolo.com).

---

### 4  Configuration dataclass (`config.py`)

```python
@dataclass(slots=True)
class Config:
    model_path: str   = env("MODEL_PATH", "models/gemma.gguf")
    workers: int      = env("WORKERS", 2)
    host: str         = env("HOST", "0.0.0.0")
    port: int         = env("PORT", 8000)
    api_key: str      = env("API_KEY", "changeme")
    max_tokens: int   = env("MAX_TOKENS", 128)
    gpu_idx: int      = env("GPU_IDX", 0)
    …                 # plus auto-detect for `llama_bin`
```

* `__post_init__` resolves an **absolute path** to `llama-cli` by checking:
  `LLAMA_BIN` → `$PATH` → `build/bin/llama-cli`.
* `__repr__` prints a concise one-liner for logs.

Instantiate once and pass around; immutable via `slots=True`.

---

### 5  Versioning

`lmserv.__version__` is pulled from package metadata (`importlib.metadata.version`).
Running from source (no wheel) defaults to **`0.0.0.dev0`**.

---

### 6  Extending / embedding

* **Add new CLI sub-commands** – append to `cli.py` (`@cli.command()` or new Typer group).
* **Alternative back-ends** – create your own worker subclass (see `server/workers`) and point the pool to it.
* **Config fields** – extend `Config`, but remember to update docs & env parsing.
* **Packaging** – `lmserv/run_cli` can act as a setuptools entry-point for `python -m lmserv`.

---

### 7  Changelog

| Version | Highlight                                             |
| ------- | ----------------------------------------------------- |
| `v1.0`  | Initial release: config, Typer CLI, FastAPI server.   |
| `v1.1`  | Added install sub-commands & LAN discovery helper.    |
| `v1.2`  | Self-healing WorkerPool, richer environment defaults. |

---

**TL;DR**
`lmserv` is a self-contained toolkit to run small-to-medium LLMs via `llama.cpp`:

1. `lmserv install llama` + `lmserv install models …`
2. `lmserv serve -m <model>.gguf -w 2`
3. Hit `POST /chat` with `X-API-Key`.
   Everything else—build, config resolution, worker management, discovery—is handled by the sub-packages above.
