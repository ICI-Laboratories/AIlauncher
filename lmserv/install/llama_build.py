# lmserv/install/llama_build.py
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import zipfile
import requests
from pathlib import Path
from tqdm.auto import tqdm

# --- INICIO DE CAMBIOS ---

_CMAKE_URL = "https://github.com/Kitware/CMake/releases/download/v3.29.3/cmake-3.29.3-windows-x86_64.zip"
_CMAKE_ZIP_FILENAME = "cmake-windows.zip"
_CMAKE_EXTRACTED_DIR_NAME = "cmake-3.29.3-windows-x86_64"

def _download_and_setup_cmake(vendor_dir: Path) -> None:
    """
    Descarga, descomprime y añade CMake al PATH del entorno actual.
    """
    vendor_dir.mkdir(exist_ok=True)
    cmake_zip_path = vendor_dir / _CMAKE_ZIP_FILENAME
    cmake_bin_path = vendor_dir / _CMAKE_EXTRACTED_DIR_NAME / "bin"

    # 1. Descargar si no existe el zip
    if not cmake_zip_path.exists():
        print(f"📥 Descargando CMake desde {_CMAKE_URL}...")
        try:
            with requests.get(_CMAKE_URL, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get("content-length", 0))
                with open(cmake_zip_path, "wb") as f, tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="CMake"
                ) as bar:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        bar.update(len(chunk))
        except requests.RequestException as e:
            print(f"❌ Error descargando CMake: {e}", file=sys.stderr)
            if cmake_zip_path.exists():
                cmake_zip_path.unlink() # Limpiar archivo parcial
            sys.exit(1)

    # 2. Descomprimir si no está extraído
    if not cmake_bin_path.exists():
        print(f"📦 Descomprimiendo {cmake_zip_path.name}...")
        with zipfile.ZipFile(cmake_zip_path, 'r') as zip_ref:
            zip_ref.extractall(vendor_dir)

    # 3. Añadir la ruta del binario de CMake al PATH del proceso actual
    os.environ["PATH"] = str(cmake_bin_path) + os.pathsep + os.environ["PATH"]
    print(f"✅ CMake configurado temporalmente para esta sesión.")


def _check_for_cmake(base_dir: Path) -> None:
    """
    Verifica si CMake está disponible. Si no, intenta instalarlo automáticamente.
    """
    if shutil.which("cmake"):
        print("✅ CMake encontrado en el PATH del sistema.")
        return

    print("⚠️ CMake no se encontró en el PATH.")
    try:
        _download_and_setup_cmake(base_dir / "vendor")
    except Exception as e:
        print(f"❌ Falló la instalación automática de CMake: {e}", file=sys.stderr)
        print("   Por favor, instala CMake manualmente y asegúrate de añadirlo al PATH.", file=sys.stderr)
        sys.exit(1)

    # Verificar de nuevo tras la instalación
    if not shutil.which("cmake"):
        print("❌ La configuración automática de CMake falló. No se pudo encontrar el ejecutable.", file=sys.stderr)
        sys.exit(1)

# --- FIN DE CAMBIOS ---

_REPO = "https://github.com/ggerganov/llama.cpp.git"

def build_llama_cpp(output_dir: str | Path, cuda: bool = True) -> None:
    """
    Compila llama.cpp de forma no-interactiva, verificando dependencias.
    Es idempotente: si el binario ya existe, omite la compilación.
    """
    output_dir = Path(output_dir).expanduser().resolve()
    build_dir = output_dir / ("build-cuda" if cuda else "build-cpu")
    bin_path = build_dir / "bin" / ("llama-cli.exe" if os.name == "nt" else "llama-cli")

    if bin_path.exists():
        print(f"✅ llama.cpp ya compilado en {bin_path}")
        return

    # Clonar repo si no existe
    if not (output_dir / ".git").exists():
        print(f"📥 Clonando llama.cpp en {output_dir}…")
        subprocess.run(["git", "clone", "--depth", "1", _REPO, str(output_dir)], check=True)

    # Elegir backend de compilación según el SO
    sysname = platform.system()
    if sysname == "Windows":
        # --- CAMBIO ---
        # En Windows, verificar (e instalar si es necesario) y luego usar CMake
        _check_for_cmake(output_dir)
        # --- FIN CAMBIO ---
        _build_windows(output_dir, build_dir, cuda)
    else:
        # En Linux o macOS, usar Make
        _build_unix(output_dir, build_dir, cuda)

    if not bin_path.exists():
        raise RuntimeError("La compilación completó pero no se encontró el binario llama-cli")


def _build_unix(src: Path, build_dir: Path, cuda: bool) -> None:
    # (Esta función no necesita cambios)
    env = os.environ.copy()
    # Nota: Llama.cpp ahora usa GGML_CUDA, no LLAMA_CUBLAS
    env["GGML_CUDA"] = "1" if cuda else "0"

    print(f"🛠️  make GGML_CUDA={env['GGML_CUDA']} -j{os.cpu_count() or 1}…")
    # Limpiar builds anteriores por si acaso
    subprocess.run(["make", "clean"], cwd=src, check=False)
    subprocess.run(["make", f"-j{os.cpu_count() or 1}"], cwd=src, env=env, check=True)

    # Mover binarios. El build de make ahora ocurre en el directorio raíz.
    bin_dir_src = src / "build" / "bin"
    if not bin_dir_src.exists(): # Fallback por si la estructura cambia
        bin_dir_src = src
        
    build_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(bin_dir_src), str(build_dir / "bin"), copy_function=shutil.copy2)


def _build_windows(src: Path, build_dir: Path, cuda: bool) -> None:
    # (Esta función no necesita cambios)
    cmake_args = [
        "cmake",
        "-B", str(build_dir),
        "-S", str(src),
        "-G", "Ninja",
        f"-DGGML_CUDA={'ON' if cuda else 'OFF'}",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_CURL=OFF",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    print("🛠️  ", " ".join(cmake_args))
    subprocess.run(cmake_args, check=True)

    subprocess.run(["cmake", "--build", str(build_dir), "--config", "Release"], check=True)