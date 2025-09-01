# lmserv/config.py

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# --- Funciones de ayuda (sin cambios) ---
def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None: return default
    try: return int(raw)
    except (TypeError, ValueError): return default

def _is_executable_file(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)

def _with_windows_ext(p: Path) -> Path:
    if os.name == "nt" and p.suffix.lower() != ".exe":
        cand = p.with_suffix(p.suffix + ".exe") if p.suffix else p.with_suffix(".exe")
        return cand if cand.exists() else p
    return p

def _iter_unique(items: Iterable[Path]) -> Iterable[Path]:
    seen: set[str] = set()
    for it in items:
        key = str(it)
        if key not in seen:
            seen.add(key)
            yield it

@dataclass(slots=True)
class Config:
    # --- Parámetros del Servidor ---
    model: str = os.getenv("MODEL", "")
    workers: int = _getenv_int("WORKERS", 2)
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _getenv_int("PORT", 8000)
    api_key: str = os.getenv("API_KEY", "changeme")
    llama_bin: str | None = field(default_factory=lambda: os.getenv("LLAMA_BIN"))
    tools_path: str | None = os.getenv("TOOLS_PATH")

    # --- Parámetros del Modelo (Llama) ---
    max_tokens: int = _getenv_int("MAX_TOKENS", 1024)
    ctx_size: int = _getenv_int("CTX_SIZE", 2048)
    n_gpu_layers: int = _getenv_int("N_GPU_LAYERS", 0)
    lora: str | None = os.getenv("LORA")

    # --- Parámetros de Inferencia (legado, pueden removerse si no se usan) ---
    gpu_idx: int = _getenv_int("GPU_IDX", 0)
    vram_cap_mb: int = _getenv_int("VRAM_CAP_MB", 24000)


    def __post_init__(self) -> None:
        """Resuelve `llama_bin` y valida que se haya especificado un modelo."""
        self.llama_bin = self._resolve_llama_bin()
        if not self.model:
            raise ValueError("No se ha especificado un modelo. Usa --model o la variable de entorno MODEL.")

    def _resolve_llama_bin(self) -> str:
        """Busca `llama-cli` en el orden correcto y devuelve una ruta absoluta."""
        candidates: list[Path] = []
        project_root = Path(__file__).resolve().parent.parent

        if self.llama_bin:
            p = Path(self.llama_bin).expanduser().resolve()
            candidates.append(p.parent / "llama-cli" if p.is_dir() else p)

        if which := shutil.which("llama-cli"):
            candidates.append(Path(which))

        # Rutas de compilación actualizadas
        build_dir = project_root / "build"
        if build_dir.is_dir():
            candidates.append(build_dir / "llama.cpp" / "llama-cli") # Ruta estándar
            candidates.append(build_dir / "bin" / "llama-cli") # Ruta antigua (si aplica)

        for path in _iter_unique(candidates):
            path = _with_windows_ext(path)
            if _is_executable_file(path):
                return str(path.resolve())

        raise FileNotFoundError(
            "No se encontró `llama-cli`. Ejecuta `lmserv install llama` o proporciona la ruta con --llama-bin."
        )

    def __repr__(self) -> str:
        lora_info = f", lora='{self.lora}'" if self.lora else ""
        tools_info = f", tools='{self.tools_path}'" if self.tools_path else ""
        params = (
            f"model='{self.model}', workers={self.workers}, host='{self.host}:{self.port}', "
            f"gpu_layers={self.n_gpu_layers}, ctx={self.ctx_size}{lora_info}{tools_info}"
        )
        return f"<Config {params}>"