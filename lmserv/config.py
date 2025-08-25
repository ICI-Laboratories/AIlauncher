# lmserv/config.py

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Ruta relativa de cortesía: .../build/bin/llama-cli
_DEFAULT_REL_LLAMA_DIR = Path(__file__).resolve().parent.parent / "build" / "bin"
_DEFAULT_REL_LLAMA = _DEFAULT_REL_LLAMA_DIR / "llama-cli"


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default  # opcional: loggear advertencia


def _normalize_path(p: str) -> str:
    # Expande ~ y variables, y resuelve a absoluta sin exigir existencia
    return str(Path(os.path.expandvars(os.path.expanduser(p))).resolve())


def _is_executable_file(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)


def _with_windows_ext(p: Path) -> Path:
    # Si estamos en Windows y no tiene .exe, pruébalo
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
    # --- CAMBIO: 'model' requerido (sin default) ---
    model: str = os.getenv("MODEL", "")
    # ------------------------------------------------
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

        # Normaliza y valida el modelo (permite rutas locales o aliases tipo -hf)
        if not self.model:
            raise ValueError("No se ha especificado un modelo. Usa --model o la variable de entorno MODEL.")
        # Si parece ruta local, normalízala; si es alias remoto (ej. 'hf:...'), déjalo tal cual
        if any(self.model.startswith(prefix) for prefix in ("hf:", "hf/", "huggingface:", "ms:", "gs:")):
            # backends remotos: no tocar
            pass
        else:
            # tratar como ruta de archivo
            self.model = _normalize_path(self.model)

    def _resolve_llama_bin(self) -> str:
        """
        Busca `llama-cli` en este orden y devuelve ruta absoluta ejecutable:
        1) Valor explícito via `LLAMA_BIN` (archivo o directorio).
        2) `$PATH`.
        3) `build/bin/llama-cli` relativo al proyecto (best effort).
        """
        candidates: list[Path] = []

        # 1) LLAMA_BIN: aceptar archivo o directorio
        if self.llama_bin:
            p = Path(self.llama_bin).expanduser().resolve()
            if p.is_dir():
                candidates.append(p / "llama-cli")
            else:
                candidates.append(p)

        # 2) PATH
        which = shutil.which("llama-cli")
        if which:
            candidates.append(Path(which))

        # 3) ruta relativa de cortesía
        if _DEFAULT_REL_LLAMA_DIR.exists():
            candidates.append(_DEFAULT_REL_LLAMA_DIR / "llama-cli")
        else:
            candidates.append(_DEFAULT_REL_LLAMA)

        for path in _iter_unique(candidates):
            path = _with_windows_ext(path)
            if _is_executable_file(path):
                return str(path.resolve())

        raise FileNotFoundError(
            "No se encontró `llama-cli`. "
            "Ejecuta `lmserv install llama` o proporciona --llama-bin=/ruta/al/llama-cli."
        )

    def __repr__(self) -> str:  # noqa: D401
        params = (
            f"model='{self.model}', workers={self.workers}, "
            f"host={self.host}, port={self.port}, gpu={self.gpu_idx}"
        )
        return f"<Config {params}>"
