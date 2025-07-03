"""
lmserv.install.llama_build
==========================

Compila **llama.cpp** de forma *no-interactiva* para Linux, macOS y Windows.

• Bajo Linux/macOS usa **make** con las flags correctas (CUDA opcional).  
• En Windows se invoca **CMake + Ninja + MSVC** (requiere “Developer Prompt”).  

La función `build_llama_cpp(output_dir, cuda=True)` es idempotente:
si ya existe el binario en *output_dir/bin/llama-cli* se omite el build.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_REPO = "https://github.com/ggerganov/llama.cpp.git"


def build_llama_cpp(output_dir: str | Path, cuda: bool = True) -> None:  # noqa: D401
    output_dir = Path(output_dir).expanduser().resolve()
    build_dir = output_dir / ("build-cuda" if cuda else "build-cpu")
    bin_path = build_dir / "bin" / ("llama.exe" if os.name == "nt" else "llama-cli")

    if bin_path.exists():
        print(f"✅  llama.cpp ya compilado en {bin_path}")
        return

    # ------------------------------------------------------------ #
    # Clonar repo si no existe
    # ------------------------------------------------------------ #
    if not (output_dir / ".git").exists():
        print(f"📥  Clonando llama.cpp en {output_dir} …")
        subprocess.run(["git", "clone", "--depth", "1", _REPO, str(output_dir)], check=True)

    # ------------------------------------------------------------ #
    # Elegir backend
    # ------------------------------------------------------------ #
    sysname = platform.system()
    if sysname == "Windows":
        _build_windows(output_dir, build_dir, cuda)
    else:  # Linux o macOS
        _build_unix(output_dir, build_dir, cuda)

    if not bin_path.exists():
        raise RuntimeError("Compilación completó pero no se encontró el binario llama-cli")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers Unix
# ──────────────────────────────────────────────────────────────────────────────
def _build_unix(src: Path, build_dir: Path, cuda: bool) -> None:
    env = os.environ.copy()
    env["LLAMA_CUBLAS"] = "1" if cuda else "0"

    print(f"🛠️   make LLAMA_CUBLAS={env['LLAMA_CUBLAS']} -j{os.cpu_count()} …")
    subprocess.run(["make", f"-j{os.cpu_count()}"], cwd=src, env=env, check=True)

    # mover binarios
    build_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src / "build/bin"), str(build_dir / "bin"), copy_function=shutil.copy2)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers Windows
# ──────────────────────────────────────────────────────────────────────────────
def _build_windows(src: Path, build_dir: Path, cuda: bool) -> None:
    cmake_args = [
        "cmake",
        "-B", str(build_dir),
        "-S", str(src),
        "-G", "Ninja",
        f"-DLLAMA_CUBLAS={'ON' if cuda else 'OFF'}",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_CURL=OFF",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    print("🛠️  ", " ".join(cmake_args))
    subprocess.run(cmake_args, check=True)

    subprocess.run(["cmake", "--build", str(build_dir), "--config", "Release"], check=True)