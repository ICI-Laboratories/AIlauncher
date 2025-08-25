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

    Args:
        output_dir: carpeta destino del *checkout* de llama.cpp (se clonará si no existe).
        cuda: habilitar CUBLAS/CUDA en Linux.
        metal: habilitar Metal en macOS. Por defecto: True en macOS, False en Linux.
    """
    output_dir = Path(output_dir).expanduser().resolve()

    # ── 1) Plataforma soportada
    sysname = platform.system()
    if sysname not in ("Linux", "Darwin"):
        raise RuntimeError(f"Este script está diseñado solo para Linux/macOS, no para {sysname}.")

    if metal is None:
        metal = (sysname == "Darwin")

    # ── 2) Preflight herramientas
    _which_or_raise("git")
    _which_or_raise("cmake")
    # El generador por defecto usará make o ninja; no lo forzamos. (Opcional: _which_or_raise("make"))

    # ── 3) Preparar/Clonar repo
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if not output_dir.exists():
        print(f"📥 Clonando llama.cpp en {output_dir}…")
        _run(["git", "clone", "--depth", "1", _REPO, str(output_dir)])
    elif not (output_dir / ".git").exists():
        raise RuntimeError(
            f"'{output_dir}' existe pero no parece un repo de git de llama.cpp (falta .git). "
            "Elimina la carpeta o apunta a un directorio válido."
        )
    else:
        print(f"↩️  Reutilizando checkout existente en {output_dir} (sin actualizar).")

    # ── 4) Elegir variante de build y rutas
    if sysname == "Darwin" and metal:
        build_flavor = "build-metal"
    elif cuda:
        build_flavor = "build-cuda"
    else:
        build_flavor = "build-cpu"

    build_dir = output_dir / build_flavor
    bin_path = build_dir / "bin" / ("llama-cli.exe" if os.name == "nt" else "llama-cli")

    # Idempotencia: si ya está el binario, salimos
    if bin_path.exists():
        print(f"✅ llama.cpp ya compilado en {bin_path}")
        return

    # ── 5) Configurar CMake
    cmake_config = [
        "cmake",
        "-S", str(output_dir),
        "-B", str(build_dir),
    ]
    if sysname == "Darwin" and metal:
        cmake_config += ["-DLLAMA_METAL=1"]
    elif cuda:
        cmake_config += ["-DLLAMA_CUBLAS=1"]

    print(f"🧩 Configurando CMake en {build_dir}…")
    _run(cmake_config)

    # ── 6) Compilar
    nproc = os.cpu_count() or 1
    print(f"🛠️  Compilando (hilos={nproc})…")
    _run(["cmake", "--build", str(build_dir), "-j", str(nproc)])

    # ── 7) Verificación final
    if not bin_path.exists():
        # En builds antiguos podría llamarse distinto; ayudamos a diagnosticar:
        maybe_old = list((build_dir / "bin").glob("*llama*"))
        hint = f"Contenido en bin: {[p.name for p in maybe_old]}" if maybe_old else "No hay binarios en bin/"
        raise RuntimeError(
            f"La compilación se ejecutó pero no se encontró el binario esperado en {bin_path}. {hint}"
        )

    print(f"✅ Compilación finalizada. Binario disponible en: {bin_path}")
