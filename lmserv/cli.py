# lmserv/cli.py

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .config import Config

cli = typer.Typer(
    add_completion=False,
    help="CLI principal de LMServ. Usa ‘lmserv <comando> --help’ para detalles.",
    no_args_is_help=True,
)

# ───────────────── Opciones ─────────────────

ModelOpt = Annotated[
    str,
    typer.Option(
        "--model",
        "-m",
        help="Ruta a un .gguf local o un ID de repositorio de Hugging Face (ej: 'ggml-org/gemma-3-1b-it-GGUF').",
    ),
]

WorkersOpt = Annotated[
    int,
    typer.Option("--workers", "-w", min=1, show_default=True, help="Número de procesos llama-cli en paralelo."),
]
HostOpt = Annotated[str, typer.Option("--host", "-H", help="Interfaz en la que escuchará FastAPI.")]
PortOpt = Annotated[int, typer.Option("--port", "-p", help="Puerto HTTP para el endpoint REST.")]
MaxTokOpt = Annotated[int, typer.Option("--max-tokens", help="Límite de tokens a generar por petición.")]
LLamaBinOpt = Annotated[
    Optional[Path],
    typer.Option("--llama-bin", exists=True, dir_okay=False, readable=True, resolve_path=True,
                 help="Ruta al ejecutable `llama-cli`."),
]

# ─────────────── Utilidades internas ───────────────

def _is_executable_file(p: Path) -> bool:
    try:
        return p.is_file() and os.access(p, os.X_OK)
    except OSError:
        return False

def _with_windows_ext(p: Path) -> Path:
    if os.name == "nt" and p.suffix.lower() != ".exe":
        cand = p.with_suffix(p.suffix + ".exe") if p.suffix else p.with_suffix(".exe")
        return cand if cand.exists() else p
    return p

def _default_rel_llama() -> Path:
    return Path(__file__).resolve().parent / "build" / "bin" / "llama-cli"

def _resolve_llama_bin_from_opts_or_env(llama_bin_opt: Optional[Path]) -> str:
    candidates: list[Path] = []

    if llama_bin_opt:
        p = Path(llama_bin_opt)
        candidates.append(p)

    which = shutil.which("llama-cli")
    if which:
        candidates.append(Path(which))

    candidates.append(_default_rel_llama())

    seen: set[str] = set()
    for path in candidates:
        path = _with_windows_ext(Path(path))
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if _is_executable_file(path):
            return str(path.resolve())

    raise typer.BadParameter(
        "No se encontró `llama-cli`. "
        "Instálalo/compílalo (p.ej. `lmserv install llama`) o proporciona --llama-bin=/ruta/al/llama-cli."
    )

# ─────────────── Comandos ───────────────

@cli.command()
def serve(
    model: ModelOpt,
    workers: WorkersOpt = 2,
    host: HostOpt = "0.0.0.0",
    port: PortOpt = 8000,
    max_tokens: MaxTokOpt = 128,
    llama_bin: LLamaBinOpt = None,
) -> None:
    """Lanza la API REST y los *workers* de llama.cpp."""
    env = os.environ.copy()
    env.update(
        {
            "MODEL": model,
            "WORKERS": str(workers),
            "HOST": host,
            "PORT": str(port),
            "MAX_TOKENS": str(max_tokens),
        }
    )
    if llama_bin:
        env["LLAMA_BIN"] = str(llama_bin)

    typer.echo(f"🚀  Levantando LMServ: http://{host}:{port}/chat  (modelo='{model}')")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "lmserv.server.api:app", "--host", host, "--port", str(port)],
        check=True,
        env=env,
    )

install_app = typer.Typer(help="Sub-comandos para compilar llama.cpp.")
cli.add_typer(install_app, name="install")

OutputDirOpt = Annotated[
    Path,
    typer.Option("--output-dir", "-o", help="Directorio destino donde quedará la build de llama.cpp.", resolve_path=True),
]
CudaOpt = Annotated[
    bool,
    typer.Option("--cuda/--no-cuda", help="Compilar con soporte CUDA/cuBLAS.", rich_help_panel="Opciones de Build"),
]

@install_app.command("llama")
def install_llama(
    output_dir: OutputDirOpt = Path("build/"),
    cuda: CudaOpt = True,
) -> None:
    """Compila llama.cpp con (o sin) soporte CUDA."""
    from .install.llama_build import build_llama_cpp
    # --- INICIO DE LA CORRECCIÓN ---
    build_llama_cpp(output_dir, cuda=cuda)
    # --- FIN DE LA CORRECCIÓN ---
    typer.secho("✅  llama.cpp compilado correctamente.", fg=typer.colors.GREEN)

@cli.command()
def discover(timeout: Annotated[int, typer.Option("--timeout", "-t", help="Segundos de búsqueda.")] = 5) -> None:
    """Busca nodos LMServ vía mDNS."""
    from .discovery.mdns import discover_nodes
    nodes = discover_nodes(timeout=timeout)
    if nodes:
        typer.secho("🌐  Nodos LMServ encontrados:", bold=True)
        for n in nodes:
            typer.echo(f" • {n.host}:{n.port} – {n.info or 'sin descripción'}")
    else:
        typer.secho("🙁  No se detectaron nodos.", fg=typer.colors.YELLOW)

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def llama(ctx: typer.Context, llama_bin: LLamaBinOpt = None) -> None:
    """Reenvía cualquier argumento directamente a `llama-cli`."""
    llama_path = _resolve_llama_bin_from_opts_or_env(llama_bin)
    cmd = [str(llama_path), *ctx.args]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        typer.secho("❌  `llama-cli` no encontrado.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        typer.secho(f"❌  `llama-cli` devolvió código {e.returncode}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(e.returncode)

@cli.command()
def update() -> None:
    """Hace `git pull` y reinstala el paquete en editable."""
    typer.echo("🔄  git pull origin main …")
    subprocess.run(["git", "pull", "origin", "main"], check=True)
    typer.echo("🛠️   rebuild (si aplica) …")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=True)
    typer.secho("✅  Proyecto actualizado.", fg=typer.colors.GREEN)

def _main() -> None:
    cli()

if __name__ == "__main__":
    _main()