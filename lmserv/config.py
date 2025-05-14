"""Carga de configuración y detección automática del binario llama-cli."""
from __future__ import annotations
import os, shutil
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_RELATIVE = Path(__file__).resolve().parent.parent / "build/bin/llama-cli"

@dataclass
class Config:
    # parámetros principales -----------------------------
    model_path : str  = os.getenv("MODEL_PATH",  "models/gemma.gguf")
    workers    : int  = int(os.getenv("WORKERS",   "3"))
    host       : str  = os.getenv("HOST",         "0.0.0.0")
    port       : int  = int(os.getenv("PORT",     "8000"))
    api_key    : str  = os.getenv("API_KEY",      "changeme")
    gpu_idx    : int  = int(os.getenv("GPU_IDX",   "0"))
    vram_cap_mb: int  = int(os.getenv("VRAM_CAP_MB","24000"))
    
    # ← Nuevo: cuántos tokens generar por petición
    max_tokens : int  = int(os.getenv("MAX_TOKENS","128"))

    # binario llama-cli (puede venir por flag o env)
    llama_bin  : str | None = field(default_factory=lambda: os.getenv("LLAMA_BIN"))

    def __post_init__(self):
        """Al terminar la construcción resolvemos la ruta."""
        self.llama_bin = self.resolve_llama_bin()

    def resolve_llama_bin(self) -> str:
        """Busca llama-cli en varios lugares y devuelve la ruta absoluta."""
        candidates: list[str] = []
        if self.llama_bin:
            candidates.append(self.llama_bin)
        which = shutil.which("llama-cli")
        if which:
            candidates.append(which)
        candidates.append(str(_DEFAULT_RELATIVE))

        for path in candidates:
            if path and Path(path).exists():
                return str(Path(path).resolve())

        raise FileNotFoundError(
            "No se encontró 'llama-cli'. Compílalo con llama.cpp o pasa --llama-bin=/ruta"
        )
