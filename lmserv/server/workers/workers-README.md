## workers-README.md

---

### 0  Directory structure

```
workers/
├── __init__.py        # Re-exports LlamaWorker
├── cpp_bridge.py      # Optional C++ extension adapter (tokeniser & sampler)
├── llama.py           # Async wrapper around a llama-cli subprocess
├── utils.py           # Shared async I/O helpers
└── README.md          # <– this file
```

| File            | Key symbols                                     | Responsibility                                                                                              |
| --------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `__init__.py`   | `LlamaWorker`                                   | Convenience re-export (`from …workers import LlamaWorker`).                                                 |
| `cpp_bridge.py` | `HAS_CPP`, `sample_top_p()`, `tokenize()`       | Detects and forwards to **`lmserv_cpp`** extension when present; falls back to pure-Python logic otherwise. |
| `llama.py`      | `LlamaWorker`, `READY_MARKER`, `REVERSE_PROMPT` | Starts, monitors and streams output from a `llama-cli` binary; provides the main **async inference API**.   |
| `utils.py`      | `_stream_reader()`                              | Reads `stdout`/`stderr` line-by-line into an asyncio `Queue` so `LlamaWorker` can multiplex streams.        |

---

### 1  Conceptual model

```
┌──────────────┐      stdin/stdout       ┌────────────────────┐
│  LlamaWorker ├────────────────────────►│    llama-cli       │
└──────────────┘◄────────────────────────┤ (from llama.cpp)   │
     ▲   ▲    queue of lines             └────────────────────┘
     │   │
     │   └── _stream_reader() tasks feed an asyncio.Queue
     │
  Optional C++ fast-path
     (cpp_bridge.py ➜ lmserv_cpp)
```

* Each active model instance = **one `LlamaWorker`** = one `llama-cli` subprocess.
* Workers are created / pooled by higher-level orchestration code (`pool.py`).
* Communication is **plain text** over stdin/stdout with a small sentinel protocol:

  * Worker waits for `READY_MARKER` to ensure cli is booted.
  * Generation stops on *either* a 2-second silence **or** seeing `REVERSE_PROMPT` in the stream (legacy safeguard).

---

### 2  Public APIs you’ll actually call

```python
from lmserv.server.workers import LlamaWorker
from lmserv.config import Config   # ← holds paths & params

cfg = Config(
    llama_bin="vendor/llama.cpp/build-cuda/bin/llama-cli",
    model_path="models/gemma-2b-it-q4_0.gguf",
    max_tokens=512,
    gpu_idx=0,
)

worker = LlamaWorker(cfg)
await worker.spawn()               # start the subprocess

async for chunk in worker.infer("What is the capital of Peru?"):
    print(chunk, end="", flush=True)

await worker.stop()                # graceful shutdown
```

| Method          | Coroutine?                       | What it does                                                                                                                                 |
| --------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `spawn()`       | ✅                                | Launches `llama-cli`, spawns two reader tasks, waits for *ready* banner.                                                                     |
| `infer(prompt)` | ✅ (returns `AsyncIterator[str]`) | Streams generated text chunks. Handles timeouts & reverse-prompt sentinel.                                                                   |
| `stop()`        | ✅                                | Sends **SIGINT** (or `CTRL_C_EVENT` on Windows), waits up to 5 s, escalates to `terminate()` → `kill()` if needed, and cancels reader tasks. |

---

### 3  C++ fast-path (optional)

* Drop-in extension module must be named **`lmserv_cpp`** and expose:

  ```cpp
  // Python-callable signatures
  int   sample_top_p(const std::vector<float>& logits, double p);
  std::vector<int> tokenize(std::string_view text);
  ```

* When import succeeds, `cpp_bridge.HAS_CPP` flips to **True** and `sample_top_p()` / `tokenize()` transparently delegate—you don’t change call-sites elsewhere.

---

### 4  How streaming works under the hood

1. **`_stream_reader()`** (one per stdout & stderr) runs in the background:

   * `loop.run_in_executor(None, stream.readline)` keeps blocking I/O off the event loop.
   * Each *line* is pushed to an `asyncio.Queue[(stream_name, line)]`.

2. **`LlamaWorker.infer()`** pulls from the queue:

   * Ignores echo of the prompt (first line).
   * Yields tokens as soon as they arrive → great for SSE / websockets.
   * If **no line** arrives for 2 s → assumes generation is finished and exits.
   * Any reader exception enqueues `("stderr", "ERROR_READER: …")` → breaks out immediately.

This avoids deadlocks, works on Windows (no `select()` on pipes), and keeps cancellation responsive.

---

### 5  Signals & cross-platform quirks

| OS              | Soft stop                             | Hard stop                | Notes                                |
| --------------- | ------------------------------------- | ------------------------ | ------------------------------------ |
| **Linux/macOS** | `SIGINT` (Ctrl-C)                     | `terminate()` → `kill()` | `llama-cli` traps SIGINT cleanly.    |
| **Windows**     | `CTRL_C_EVENT` to the *process group* | same as above            | Requires `CREATE_NEW_PROCESS_GROUP`. |

---

### 6  Extending

* **Different model backend?** – Implement another `FooWorker` with the same async API (`spawn`, `infer`, `stop`) and expose it via `workers/__init__.py`.
* **Custom stopping criteria?** – Adjust the 2 s timeout or sentinel checks inside `llama.py::infer()`.
* **Concurrency / pooling** – See `server/pool.py`; workers are stateless between calls so they can be reused.
* **Metrics / tracing** – Insert hooks where `_queue.put()` happens; that’s the single channel for every line.

---

### 7  Troubleshooting checklist

| Symptom                                                  | Likely cause                                          | Quick test                                                        |
| -------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------- |
| *Worker never becomes ready*                             | Wrong `llama_bin` path or incompatible model          | Manually run the same `llama-cli` command shown in logs.          |
| *Subprocess dies instantly*                              | Out-of-memory (GPU/CPU) or bad CLI flag               | Check `stderr` lines captured in logs.                            |
| *Generation freezes mid-way*                             | Timeout too short / model slow                        | Increase 2 s timeout in `infer()` or watch system utilisation.    |
| `HAS_CPP = False` even though you compiled the extension | Wrong module name or Python can’t find `.pyd` / `.so` | `python -c "import lmserv_cpp, sys; print(lmserv_cpp, sys.path)"` |

---

### 8  Changelog

| Version | Change                                                                             |
| ------- | ---------------------------------------------------------------------------------- |
| `v1.0`  | Initial LlamaWorker with stdout/stderr readers and timeout stop.                   |
| `v1.1`  | Added optional C++ bridge (`lmserv_cpp`) for fast tokenisation & sampling.         |
| `v1.2`  | Reverse-prompt sentinel downgraded; 2 s silence is now the primary stop criterion. |

---

**TL;DR**
`LlamaWorker` spins up `llama-cli`, streams tokens through an asyncio queue, and can optionally accelerate tokenisation/sampling via a tiny C++ extension. Import it, `spawn()`, iterate over `infer()`, and `stop()` when done.
