from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _getenv_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _with_windows_ext(path: Path) -> Path:
    if os.name == "nt" and path.suffix.lower() != ".exe":
        candidate = path.with_suffix(path.suffix + ".exe") if path.suffix else path.with_suffix(".exe")
        return candidate if candidate.exists() else path
    return path


def _iter_unique(items: Iterable[Path]) -> Iterable[Path]:
    seen: set[str] = set()
    for item in items:
        key = str(item)
        if key not in seen:
            seen.add(key)
            yield item


@dataclass(slots=True)
class Config:
    # Gateway / server
    backend: str = os.getenv("MODEL_BACKEND", "llama_cpp")
    model: str = os.getenv("MODEL", "")
    catalog_path: str | None = os.getenv("MODEL_CATALOG_PATH")
    default_model_alias: str | None = os.getenv("DEFAULT_MODEL_ALIAS")
    workers: int = _getenv_int("WORKERS", 2)
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _getenv_int("PORT", 8000)
    api_key: str = os.getenv("API_KEY", "changeme")
    llama_bin: str | None = field(default_factory=lambda: os.getenv("LLAMA_BIN"))
    tools_path: str | None = os.getenv("TOOLS_PATH")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    request_timeout_s: float = _getenv_float("REQUEST_TIMEOUT_S", 120.0)

    # Model parameters
    max_tokens: int = _getenv_int("MAX_TOKENS", 1024)
    ctx_size: int = _getenv_int("CTX_SIZE", 2048)
    n_gpu_layers: int = _getenv_int("N_GPU_LAYERS", 0)
    lora: str | None = os.getenv("LORA")

    # Legacy execution parameters
    gpu_idx: int = _getenv_int("GPU_IDX", 0)
    vram_cap_mb: int = _getenv_int("VRAM_CAP_MB", 24000)

    def __post_init__(self) -> None:
        """
        Validate startup inputs.

        The service can start in:
        1. simple mode: one model + one backend
        2. catalog mode: multiple routes declared in JSON
        """
        if not self.model and not self.catalog_path:
            raise ValueError(
                "No se ha especificado un modelo ni un catalogo. "
                "Usa --model/ MODEL o --catalog/ MODEL_CATALOG_PATH."
            )

        if self.catalog_path:
            self.catalog_path = str(Path(self.catalog_path).expanduser().resolve())

        if self.model and self.backend == "llama_cpp":
            self.llama_bin = self._resolve_llama_bin()

    def _resolve_llama_bin(self) -> str:
        candidates: list[Path] = []
        project_root = Path(__file__).resolve().parent.parent

        if self.llama_bin:
            path = Path(self.llama_bin).expanduser().resolve()
            candidates.append(path / "llama-cli" if path.is_dir() else path)

        if which := shutil.which("llama-cli"):
            candidates.append(Path(which))

        build_root = project_root / "build"
        if build_root.is_dir():
            for flavor_dir in build_root.iterdir():
                if flavor_dir.is_dir() and flavor_dir.name.startswith("build-"):
                    candidates.append(flavor_dir / "bin" / "llama-cli")
            candidates.append(build_root / "bin" / "llama-cli")

        for path in _iter_unique(candidates):
            candidate = _with_windows_ext(path)
            if _is_executable_file(candidate):
                return str(candidate.resolve())

        raise FileNotFoundError(
            "No se encontro `llama-cli`. Compila llama.cpp con `lmserv install llama` "
            "o proporciona la ruta explicitamente con --llama-bin."
        )

    def __repr__(self) -> str:
        lora_info = f", lora='{self.lora}'" if self.lora else ""
        tools_info = f", tools='{self.tools_path}'" if self.tools_path else ""
        catalog_info = f", catalog='{self.catalog_path}'" if self.catalog_path else ""
        params = (
            f"backend='{self.backend}', model='{self.model}', workers={self.workers}, "
            f"host='{self.host}:{self.port}', gpu_layers={self.n_gpu_layers}, ctx={self.ctx_size}"
            f"{lora_info}{tools_info}{catalog_info}"
        )
        return f"<Config {params}>"
