"""Carga de configuración vía variables de entorno o argumentos CLI."""
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class Config:
    model_path: str = os.getenv("MODEL_PATH", "models/gemma.gguf")
    workers: int = int(os.getenv("WORKERS", "3"))
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    api_key: str = os.getenv("API_KEY", "changeme")
    gpu_idx: int = int(os.getenv("GPU_IDX", "0"))
    vram_cap_mb: int = int(os.getenv("VRAM_CAP_MB", "24000"))

    @classmethod
    def from_cli(cls, **kwargs) -> "Config":
        """Construye la configuración priorizando flags CLI sobre envs."""
        base = cls()
        for k, v in kwargs.items():
            if v is not None:
                setattr(base, k, v)
        return base