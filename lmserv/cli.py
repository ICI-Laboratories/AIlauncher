# lmserv/cli.py

from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .config import Config

###############################################################################
# CLI raíz
###############################################################################

cli = typer.Typer(
    add_completion=False,
    help="CLI principal de LMServ. Usa ‘lmserv <comando> --help’ para detalles.",
    no_args_is_help=True,
)

###############################################################################
# Tipos reutilizables de opciones ─────────────────────────────────────────────
###############################################################################

ModelPathOpt = Annotated[
    Path,
    typer.Option(
        "--model-path",
        "-m",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Ruta al modelo .gguf que usarán los workers.",
    ),
]

WorkersOpt = Annotated[
    int,
    typer.Option(
        "--workers",
        "-w",
        min=1,
        show_default=True,
        help="Número de procesos llama-cli en paralelo.",
    ),
]

HostOpt = Annotated[
    str,
    typer.Option(
        "--host",
        "-H",
        help="Interfaz en la que escuchará FastAPI.",
    ),
]

PortOpt = Annotated[
    int,
    typer.Option(
        "--port",
        "-p",
        help="Puerto HTTP para el endpoint REST.",
    ),
]

MaxTokOpt = Annotated[
    int,
    typer.Option(
        "--max-tokens",
        help="Límite de tokens a generar por petición.",
    ),
]

LLamaBinOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--llama-bin",
        exists=True,
        dir_okay=False,
        writable=False,
        help="Ruta al ejecutable `llama-cli` (si no está en $PATH).",
    ),
]

###############################################################################
# Comando principal: serve
###############################################################################

@cli.command()
def serve(
    model_path: ModelPathOpt,
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
            "MODEL_PATH": str(model_path),
            "WORKERS": str(workers),
            "HOST": host,
            "PORT": str(port),
            "MAX_TOKENS": str(max_tokens),
        }
    )
    if llama_bin:
        env["LLAMA_BIN"] = str(llama_bin)

    typer.echo(f"🚀  Levantando LMServ: http://{host}:{port}/chat  (workers={workers})")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "lmserv.server.api:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        check=True,
        env=env,
    )

###############################################################################
# Sub-comandos de instalación
###############################################################################

install_app = typer.Typer(
    help="Sub-comandos para compilar llama.cpp y descargar modelos .gguf.",
)
cli.add_typer(install_app, name="install")

OutputDirOpt = Annotated[
    Path,
    typer.Option(
        "--output-dir",
        "-o",
        help="Directorio destino donde quedará la build de llama.cpp.",
    ),
]

CudaOpt = Annotated[
    bool,
    typer.Option(
        "--cuda/--no-cuda",
        help="Compilar con soporte CUDA/cuBLAS.",
        rich_help_panel="Opciones de Build",
    ),
]

ModelNamesArg = Annotated[
    list[str],
    typer.Argument(
        ...,
        help="Nombre corto de modelos a bajar (p.e. ‘gemma-2b’, ‘phi3-mini’).",
    ),
]

TargetDirOpt = Annotated[
    Path,
    typer.Option(
        "--target-dir",
        "-d",
        help="Carpeta destino de los .gguf.",
    ),
]

@install_app.command("llama")
def install_llama(
    output_dir: OutputDirOpt = Path("build/"),
    cuda: CudaOpt = True,
) -> None:
    """Compila llama.cpp con (o sin) soporte CUDA."""

    from .install.llama_build import build_llama_cpp

    build_llama_cpp(output_dir, cuda)
    typer.secho("✅  llama.cpp compilado correctamente.", fg=typer.colors.GREEN)

@install_app.command("models")
def install_models(
    names: ModelNamesArg,
    target_dir: TargetDirOpt = Path("models/"),
) -> None:
    """Descarga modelos .gguf predefinidos y los guarda en *target_dir*."""

    from .install.models_fetch import download_models

    download_models(names, target_dir)
    typer.secho("✅  Modelos descargados.", fg=typer.colors.GREEN)

###############################################################################
# Descubrimiento de nodos
###############################################################################

TimeoutOpt = Annotated[
    int,
    typer.Option(
        "--timeout",
        "-t",
        help="Segundos de búsqueda.",
    ),
]

@cli.command()
def discover(timeout: TimeoutOpt = 5) -> None:
    """Busca nodos LMServ vía mDNS."""

    from .discovery.mdns import discover_nodes

    nodes = discover_nodes(timeout=timeout)
    if nodes:
        typer.secho("🌐  Nodos LMServ encontrados:", bold=True)
        for n in nodes:
            typer.echo(f" • {n.host}:{n.port} – {n.info or 'sin descripción'}")
    else:
        typer.secho("🙁  No se detectaron nodos.", fg=typer.colors.YELLOW)

###############################################################################
# Passthrough a llama-cli
###############################################################################

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def llama(ctx: typer.Context) -> None:
    """Reenvía cualquier argumento directamente a `llama-cli`."""

    cfg = Config()
    cmd = [str(cfg.llama_bin), *ctx.args]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        typer.secho(
            "❌  `llama-cli` no encontrado. Usa `lmserv install llama` o pasa --llama-bin.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

###############################################################################
# Actualizar repositorio
###############################################################################

@cli.command()
def update() -> None:
    """Hace `git pull` y reinstala el paquete en editable."""

    typer.echo("🔄  git pull origin main …")
    subprocess.run(["git", "pull", "origin", "main"], check=True)
    typer.echo("🛠️   rebuild (si aplica) …")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=True)
    typer.secho("✅  Proyecto actualizado.", fg=typer.colors.GREEN)

###############################################################################
# Entry-point
###############################################################################

def _main() -> None:
    cli()

if __name__ == "__main__":
    _main()
