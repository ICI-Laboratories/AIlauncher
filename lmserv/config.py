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
    model: str = os.getenv("MODEL", "")
    workers: int = _getenv_int("WORKERS", 2)
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _getenv_int("PORT", 8000)
    api_key: str = os.getenv("API_KEY", "changeme")
    max_tokens: int = _getenv_int("MAX_TOKENS", 128)
    gpu_idx: int = _getenv_int("GPU_IDX", 0)
    vram_cap_mb: int = _getenv_int("VRAM_CAP_MB", 24000)
    llama_bin: str | None = field(default_factory=lambda: os.getenv("LLAMA_BIN"))

    def __post_init__(self) -> None:
        """Resuelve `llama_bin` y valida que se haya especificado un modelo."""
        self.llama_bin = self._resolve_llama_bin()

        # --- INICIO DE LA CORRECCIÓN ---
        # Simplemente validamos que el modelo exista. No intentamos "adivinar"
        # si es una ruta o un repo de HF. Dejamos que el LlamaWorker decida.
        if not self.model:
            raise ValueError("No se ha especificado un modelo. Usa --model o la variable de entorno MODEL.")
        # --- FIN DE LA CORRECCIÓN ---

    def _resolve_llama_bin(self) -> str:
        """Busca `llama-cli` en el orden correcto y devuelve una ruta absoluta."""
        candidates: list[Path] = []
        project_root = Path(__file__).resolve().parent.parent

        if self.llama_bin:
            p = Path(self.llama_bin).expanduser().resolve()
            candidates.append(p.parent / "llama-cli" if p.is_dir() else p)

        if which := shutil.which("llama-cli"):
            candidates.append(Path(which))

        build_root = project_root / "build"
        if build_root.exists():
            candidates.append(build_root / "build-cuda" / "bin" / "llama-cli")
            candidates.append(build_root / "build-cpu" / "bin" / "llama-cli")

        for path in _iter_unique(candidates):
            path = _with_windows_ext(path)
            if _is_executable_file(path):
                return str(path.resolve())

        raise FileNotFoundError(
            "No se encontró `llama-cli`. Ejecuta `lmserv install llama` o proporciona la ruta con --llama-bin."
        )

    def __repr__(self) -> str:
        params = (
            f"model='{self.model}', workers={self.workers}, "
            f"host={self.host}, port={self.port}, gpu={self.gpu_idx}"
        )
        return f"<Config {params}>"