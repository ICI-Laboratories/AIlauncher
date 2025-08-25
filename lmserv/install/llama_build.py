# lmserv/install/llama_build.py
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
import shutil

_REPO = "https://github.com/ggerganov/llama.cpp.git"

def _which_or_raise(cmd: str) -> str:
    path = shutil.which(cmd)
    if not path:
        raise RuntimeError(f"Falta '{cmd}' en el PATH. Instálalo para continuar.")
    return path

def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)

def build_llama_cpp(
    output_dir: str | Path,
    *,
    cuda: bool = True,
    metal: bool | None = None,
) -> None:
    """
    Compila llama.cpp en Linux/macOS usando CMake.
    Idempotente: si el binario objetivo ya existe, no recompila.
    """
    output_dir = Path(output_dir).expanduser().resolve()

    sysname = platform.system()
    if sysname not in ("Linux", "Darwin"):
        raise RuntimeError(f"Este script está diseñado solo para Linux/macOS, no para {sysname}.")

    if metal is None:
        metal = (sysname == "Darwin")

    _which_or_raise("git")
    _which_or_raise("cmake")

    if not output_dir.exists():
        print(f"📥 Clonando llama.cpp en {output_dir}…")
        _run(["git", "clone", "--depth", "1", _REPO, str(output_dir)])
    else:
        print(f"↩️  Reutilizando checkout existente en {output_dir} (sin actualizar).")

    build_flavor = "build-cpu"
    if sysname == "Darwin" and metal:
        build_flavor = "build-metal"
    elif cuda:
        build_flavor = "build-cuda"

    build_dir = output_dir / build_flavor
    bin_path = build_dir / "bin" / "llama-cli"

    if bin_path.exists():
        print(f"✅ llama.cpp ya compilado en {bin_path}")
        return

    # --- INICIO DE LA CORRECCIÓN ---
    # Eliminamos la línea "-DLLAMA_CURL=OFF" para que se active por defecto
    cmake_config = [
        "cmake",
        "-S", str(output_dir),
        "-B", str(build_dir),
    ]
    # --- FIN DE LA CORRECCIÓN ---

    if sysname == "Darwin" and metal:
        cmake_config += ["-DLLAMA_METAL=1"]
    elif cuda:
        cmake_config += ["-DLLAMA_CUBLAS=1"]

    print(f"🧩 Configurando CMake en {build_dir}…")
    _run(cmake_config)

    nproc = os.cpu_count() or 1
    print(f"🛠️  Compilando (hilos={nproc})…")
    _run(["cmake", "--build", str(build_dir), "-j", str(nproc)])

    if not bin_path.exists():
        raise RuntimeError(f"La compilación se ejecutó pero no se encontró el binario en {bin_path}.")

    print(f"✅ Compilación finalizada. Binario disponible en: {bin_path}")