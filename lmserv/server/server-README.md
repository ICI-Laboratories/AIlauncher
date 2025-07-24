## server-README.md

---

### 0  Directory structure

```
server/
├── __init__.py      # Logging bootstrap; re-exports FastAPI app & WorkerPool
├── api.py           # FastAPI routes + application lifespan
├── pool.py          # Async WorkerPool (manages persistent llama-cli procs)
├── security.py      # API-key auth, CORS helper, optional rate-limiter
├── workers/         # Runtime wrappers around llama.cpp  ➜  see workers-README.md
│   ├── __init__.py
│   ├── cpp_bridge.py
│   ├── llama.py
│   ├── utils.py
│   └── README.md
└── README.md        # <– this file
```

| File          | Key symbols                                                              | What it does                                                                          |
| ------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| `__init__.py` | `app`, `WorkerPool`                                                      | Sets global logging format, then just re-exports.                                     |
| `api.py`      | `app` (FastAPI instance), `ChatRequest`                                  | Defines `/chat`, `/health`, root `/`; wires `WorkerPool` into startup/shutdown.       |
| `pool.py`     | `WorkerPool`                                                             | Spawns *N* `LlamaWorker`s on start-up, hands them out with `acquire()` / `release()`. |
| `security.py` | `api_key_auth()`, `add_cors_middleware()`, `add_rate_limit_dependency()` | Drop-in helpers for auth, CORS and (optional) QPS limiting.                           |

---

### 1  End-to-end request flow

```
HTTP                                           ┌──────────────┐
POST /chat  ────────────────────────────────►  │   api.py     │
{prompt:"…"}                                   │  /chat route │
                                               └──────┬───────┘
                                                      │ acquires
                                                      ▼
                                            ┌───────────────────┐
                                            │   WorkerPool      │
                                            │ (pool.py)         │
                                            └──────┬────────────┘
                       AsyncIterator[str] ▲        │ holds
                                           │        ▼
                                            ┌───────────────────┐
                                            │   LlamaWorker     │
                                            │ (workers/llama.py)│
                                            └───────────────────┘
```

1. **Client** sends `POST /chat` with JSON body *(see §2.1)* and header `X-API-Key`.
2. **security.api\_key\_auth** validates the key.
3. Route **acquires** an idle `LlamaWorker` from the shared **WorkerPool**.
4. The worker streams tokens from its `llama-cli` subprocess; each chunk is yielded to FastAPI’s `StreamingResponse`.
5. Once generation ends (timeout/sentinel), the route **releases** the worker back to the pool (or respawns if it died).

`/health` simply returns `"ok – workers idle: <n>"` so you can probe liveness.

---

### 2  Public API surface

#### 2.1 `POST /chat`

```jsonc
{
  "prompt":          "Hello, world!",
  "system_prompt":   "You are a helpful assistant.",   // optional
  "max_tokens":      256,                               // optional
  "temperature":     0.8,                               // optional
  "top_p":           0.9,                               // optional
  "repeat_penalty":  1.1                                // optional
}
```

*Headers* — `X-API-Key: <your key>` (required).
*Response* — **text/plain** streaming chunks (one per token / line).

#### 2.2 `GET /health` → `"ok – workers idle: N"`

#### 2.3 `GET /` (root) → `"LMServ is running."`

---

### 3  Configuration (via `Config`)

`api.py` instantiates a **Config** into `app.state.config`.
Typical environment variables (see `lmserv/config.py`) include:

| Env var          | Purpose                      | Default                                     |
| ---------------- | ---------------------------- | ------------------------------------------- |
| `LLM_MODEL_PATH` | Path to `.gguf` model        | `models/gemma-2b-it-q4_0.gguf`              |
| `LLM_BIN_PATH`   | Path to `llama-cli`          | `vendor/llama.cpp/build-cuda/bin/llama-cli` |
| `LLM_WORKERS`    | Number of persistent workers | **1**                                       |
| `API_KEY`        | Key required in `X-API-Key`  | `"changeme"`                                |
| `LOG_LEVEL`      | Root log level               | `"INFO"`                                    |

Adjust them before launching the server.

---

### 4  Running the service

```bash
# 1. Ensure llama.cpp is compiled & models are downloaded (see install-README)
export API_KEY=secret123
export LLM_WORKERS=2

# 2. Fire up Uvicorn
uvicorn lmserv.server.api:app --host 0.0.0.0 --port 8000
```

Test it:

```bash
curl -N -H "X-API-Key: secret123" \
     -H "Content-Type: application/json" \
     -d '{"prompt":"Name a famous Peruvian dish"}' \
     http://localhost:8000/chat
```

You should see tokens stream back in real-time.

---

### 5  Security & middleware

| Concern        | How it’s handled                               | Where                          |
| -------------- | ---------------------------------------------- | ------------------------------ |
| **API key**    | Simple header check                            | `security.api_key_auth`        |
| **CORS**       | Call `add_cors_middleware(app, origins)` early | `security.py`                  |
| **Rate-limit** | Opt-in via `RATE_LIMIT_QPS` env var (>0)       | `security.py` (in-memory stub) |
| **Logging**    | BasicConfig at import; level from `LOG_LEVEL`  | `server/__init__.py`           |

---

### 6  WorkerPool rules of thumb

* Workers are **long-lived**: spawning is expensive, so they stay up.
* `acquire()` **awaits** an idle worker → back-pressure if pool is exhausted.
* `release()` checks if the process is still alive; if not, it respawns a fresh one transparently.
* Call `WorkerPool.shutdown()` at exit to terminate all `llama-cli` children cleanly (handled inside FastAPI lifespan).

---

### 7  Extending the API

* **New routes** – import `app` from `lmserv.server` and mount any additional FastAPI routers.
* **Different model backend** – create another `FooWorker` (same coroutine API) in `workers/` and swap it into `pool.py`.
* **Custom auth** – replace `api_key_auth` dependency with OAuth/JWT etc.

---

### 8  Troubleshooting quick table

| Symptom                                              | Likely cause                               | Remedy                                            |
| ---------------------------------------------------- | ------------------------------------------ | ------------------------------------------------- |
| `503 Server is starting up`                          | Request arrived before pool spawned        | Wait; pool startup can take \~30 s.               |
| `401 Bad API key`                                    | Wrong `X-API-Key` header                   | Check `API_KEY` env var.                          |
| `/health` shows `idle: 0` forever                    | All workers hung or crashed                | Inspect logs; they’ll be respawned automatically. |
| Uvicorn exits with `ModuleNotFoundError: lmserv_cpp` | Only a warning; C++ extension is optional. |                                                   |

---

### 9  Changelog

| Version | Change                                                  |
| ------- | ------------------------------------------------------- |
| `v1.0`  | First public server API (health, chat) with WorkerPool. |
| `v1.1`  | Added API-key auth, CORS helper, stub rate-limit.       |
| `v1.2`  | Improved WorkerPool self-healing & detailed logging.    |

---

**TL;DR**
Run `uvicorn lmserv.server.api:app`, hit `/chat` with `X-API-Key`, and the stack (`FastAPI → Pool → LlamaWorker → llama-cli`) streams back tokens in real-time. All moving parts live in `lmserv/server/` and `lmserv/server/workers/`.
