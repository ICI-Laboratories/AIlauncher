## install-README.md  

### 0  Directory structure



install/
├── **init**.py          # Re-exports the public helpers
├── llama\_build.py       # Cross-platform builder for llama.cpp
├── models\_fetch.py      # Model downloader + SHA-256 verifier
└── install-README.md    # <– this file



| File | Key symbols you’ll use | What it’s for |
|------|------------------------|---------------|
| `__init__.py` | `build_llama_cpp`, `download_models` | Convenience re-export so callers can `from lmserv.install import …`. |
| `llama_build.py` | `build_llama_cpp()` | Clones & compiles `llama.cpp`; handles Windows CMake boot-strap, CUDA toggle, idempotency. |
| `models_fetch.py` | `download_models()` | Range-resumable downloads, checksum guard, optional untar. |
| *(generated at runtime)* `vendor/` | — | Temporary CMake ZIP (Windows only). |
| *(your path)* `build-{cpu|cuda}/bin/` | — | Final `llama-cli(.exe)` binary after a successful build. |

---

### 1  Overview  
The *install* subsystem automates two mandatory steps:

1. **Building [`llama.cpp`](https://github.com/ggerganov/llama.cpp)** (CPU *or* CUDA).  
2. **Fetching quantised GGUF models** with integrity checks.

It is **idempotent**—rerunning a helper skips work already done.

---

### 2  Public APIs  

| Symbol | Defined in | Purpose |
| ------ | ---------- | ------- |
| `build_llama_cpp(output_dir: str | Path, *, cuda: bool = True)` | `llama_build.py` | Clone + compile `llama.cpp`, yielding `llama-cli(.exe)` under `output_dir/build-{cpu|cuda}/bin/`. |
| `download_models(names: Iterable[str], target_dir: str | Path)` | `models_fetch.py` | Download models, verify SHA-256, untar if needed, store in `target_dir/`. |

Import convenience:

from lmserv.install import build_llama_cpp, download_models



### 2  Public APIs


| Symbol                                                     | Defined in                     | Purpose                                                                                                            |                                                                                                   |               |
| ---------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- | ------------- |
| \`build\_llama\_cpp(output\_dir: str                       | Path, \*, cuda: bool = True)\` | `llama_build.py`                                                                                                   | Clone + compile llama.cpp, creating `llama-cli(.exe)` under \`output\_dir/build-{cpu              | cuda}/bin/\`. |
| \`download\_models(names: Iterable\[str], target\_dir: str | Path)\`                        | `models_fetch.py`                                                                                                  | Download the requested models, verify SHA-256, optionally untar, and leave them in `target_dir/`. |               |
| `__all__`                                                  | `install.__init__`             | Re-exports the two helpers for convenient import:<br>`from lmserv.install import build_llama_cpp, download_models` |                                                                                                   |               |

---

### 3  Building `llama.cpp`

#### 3.1 Cross-platform strategy

| OS                | Build system      | Helper used      | Notes                                                |
| ----------------- | ----------------- | ---------------- | ---------------------------------------------------- |
| **Linux / macOS** | `make`            | `_build_unix`    | Sets `GGML_CUDA=1/0`, cleans, then `make -jN`.       |
| **Windows**       | `cmake` + `ninja` | `_build_windows` | Auto-installs portable CMake if missing (see below). |

#### 3.2 Auto-installing CMake on Windows

If `cmake` isn’t in `PATH`, `_check_for_cmake()` triggers:

1. Download portable ZIP <br>(currently v3.29.3 x86-64) into `vendor/`.
2. Extract & *prepend* its `bin/` directory to `PATH` for the current session.
3. Abort with guidance if anything fails.

No files are written outside the chosen `output_dir`.

#### 3.3 Idempotency rules

* **Repo clone** – skipped when `output_dir/.git` already exists.
* **Compilation** – skipped when the expected `llama-cli(.exe)` is already present.

---

### 4  Fetching Models

#### 4.1 The built-in catalog


_CATALOG = {
    "gemma-2b":        ("<url>", "<sha256>"),
    "phi3-mini":       ("<url>", "<sha256>"),
    "mistral-7b-instruct": ("<url>", "<sha256>"),
}


Add / edit entries in a single place. Each tuple is:

1. **Direct download URL** (supports HTTP range requests).
2. **Expected SHA-256** (repo integrity, no surprises).

#### 4.2 Download workflow

1. **Resume-capable GET** – continues partial `.part` files using `Range:` headers.
2. **Progress bar** – via `tqdm`.
3. **Checksum verification** – mismatches delete the file and raise.
4. **Optional decompression** – `.tar.{gz,zst}` archives are extracted then removed.

#### 4.3 CLI convenience

```bash
python -m lmserv.install.models_fetch gemma-2b phi3-mini  \
    --target models/
```

(The script simply forwards args to `download_models()` and defaults to `models/`.)

---

### 5  Typical end-to-end setup

```python
from pathlib import Path
from lmserv.install import build_llama_cpp, download_models

BIN_DIR   = Path("vendor/llama.cpp")   # or wherever you like
MODEL_DIR = Path("models/")

# 1. Compile llama.cpp with CUDA support if available
build_llama_cpp(BIN_DIR, cuda=True)

# 2. Grab at least one model
download_models(["gemma-2b"], MODEL_DIR)
```

After that, `vendor/llama.cpp/build-cuda/bin/llama-cli` will be ready and the models will sit under `models/`.

---

### 6  Dependencies

| Purpose              | Package / Tool                                                      |
| -------------------- | ------------------------------------------------------------------- |
| HTTP & progress bars | `requests`, `tqdm`                                                  |
| Build (Linux/macOS)  | `make`, C/C++ toolchain                                             |
| Build (Windows)      | `cmake` **and** `ninja` (CMake auto-installed if absent)            |
| Git clone            | `git` in `PATH`                                                     |
| CUDA build           | NVIDIA toolchain that llama.cpp expects (`nvcc`, compatible driver) |

All Python-level dependencies are already listed in the repo’s root `requirements.txt`.

---

### 7  Config Tweaks

| Variable / Constant | File              | Why you might change it                     |
| ------------------- | ----------------- | ------------------------------------------- |
| `_REPO`             | `llama_build.py`  | Pin llama.cpp to a fork or commit.          |
| `_CMAKE_URL`        | `llama_build.py`  | Use a mirror / newer CMake release.         |
| `_CATALOG`          | `models_fetch.py` | Add your own GGUF models.                   |
| `_CHUNK`            | `models_fetch.py` | Tune download chunk size (default = 2 MiB). |

---

### 8  Gotchas & FAQ

* **“ninja: command not found” on Windows** – Install Ninja or add it to `PATH`.
* **Checksum mismatch** – File is deleted; typically means download was corrupted or the upstream file changed. Update the `_CATALOG` hash accordingly.
* **GPU build fails** – Try `cuda=False` first to ensure the basic toolchain works, then debug CUDA specifics.
* **Proxy / firewall** – Both Git and direct model URLs must be reachable.

---

### 9  Changelog

| Version | Change                                                                      |
| ------- | --------------------------------------------------------------------------- |
| `v1.0`  | Initial cross-platform builder + model fetcher with resume & SHA-256 guard. |
| `v1.1`  | Auto-installation of portable CMake on Windows.                             |
| `v1.2`  | Added `mistral-7b-instruct` to model catalog.                               |

---

**TL;DR**
Run `build_llama_cpp()` once, then `download_models()`. You’ll get a fresh `llama-cli` binary and verified GGUF weights—ready for LMServ’s runtime.
