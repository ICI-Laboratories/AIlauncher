"""
Configuración central de LMServ
===============================
... (file content is the same as the original) ...
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


_DEFAULT_REL_LLAMA = Path(__file__).resolve().parent / "build/bin/llama-cli.exe"


@dataclass(slots=True)
class Config:
    # ────────────────────────── parámetros principales ──────────────────────────
    model_path: str = os.getenv("MODEL_PATH", "models/gemma.gguf")
    workers: int = int(os.getenv("WORKERS", "2"))
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    api_key: str = os.getenv("API_KEY", "changeme")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "128"))

    # ─────────────────────────── detalles de hardware ──────────────────────────
    gpu_idx: int = int(os.getenv("GPU_IDX", "0"))
    vram_cap_mb: int = int(os.getenv("VRAM_CAP_MB", "24000"))

    # ─────────────────────────────── llama-cli ─────────────────────────────────
    llama_bin: str | None = field(default_factory=lambda: os.getenv("LLAMA_BIN"))

    # ------------------------------------------------------------------------- #
    # Métodos
    # ------------------------------------------------------------------------- #
    def __post_init__(self) -> None:
        """Resuelve `llama_bin` a una ruta absoluta válida."""
        self.llama_bin = self._resolve_llama_bin()

    # --------------------------------------------------------------------- #
    # Helpers privados
    # --------------------------------------------------------------------- #
    def _resolve_llama_bin(self) -> str:
        """
        Busca `llama-cli` en el siguiente orden y devuelve la ruta:
        1. Valor explícito via `LLAMA_BIN` o argument-flag.
        2. `$PATH`.
        3. `build/bin/llama-cli` relativo al paquete.
        """
        candidates: list[str] = []
        if self.llama_bin:
            candidates.append(self.llama_bin)

        which = shutil.which("llama-cli")
        if which:
            candidates.append(which)

        candidates.append(str(_DEFAULT_REL_LLAMA))

        for path in candidates:
            if path and Path(path).exists():
                return str(Path(path).resolve())

        raise FileNotFoundError(
            "No se encontró `llama-cli`. "
            "Ejecuta `lmserv install llama` o proporciona --llama-bin=/ruta."
        )

    # --------------------------------------------------------------------- #
    # Representación “friendly” para logs/debug
    # --------------------------------------------------------------------- #
    def __repr__(self) -> str:  # noqa: D401
        params = (
            f"model={self.model_path!s}, workers={self.workers}, "
            f"host={self.host}, port={self.port}, gpu={self.gpu_idx}"
        )
        return f"<Config {params}>"

# NO config_instance here.