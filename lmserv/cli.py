from __future__ import annotations

import os
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

# --- Definiciones de opciones para el comando 'serve' ---
ModelPathOpt = Annotated[
    Path,
    typer.Option(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Ruta al modelo .gguf que usarán los workers.",
    ),
]
WorkersOpt = Annotated[
    int,
    typer.Option(
        default=2,
        min=1,
        show_default=True,
        help="Número de procesos llama-cli en paralelo.",
    ),
]
HostOpt = Annotated[
    str, typer.Option(default="0.0.0.0", help="Interfaz en la que escuchará FastAPI.")
]
PortOpt = Annotated[
    int, typer.Option(default=8000, help="Puerto HTTP para el endpoint REST.")
]
MaxTokOpt = Annotated[
    int, typer.Option(default=128, help="Límite de tokens a generar por petición.")
]
LLamaBinOpt = Annotated[
    Optional[Path],
    typer.Option(
        default=None,
        exists=True,
        dir_okay=False,
        writable=False,
        help="Ruta al ejecutable `llama-cli` (si no está en $PATH).",
    ),
]

@cli.command()
def serve(
    model_path: ModelPathOpt,
    workers: WorkersOpt,
    host: HostOpt,
    port: PortOpt,
    max_tokens: MaxTokOpt,
    llama_bin: LLamaBinOpt,
) -> None:
    # (El cuerpo de la función no cambia)
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
        [sys.executable, "-m", "uvicorn", "lmserv.server.api:app", "--host", host, "--port", str(port)],
        check=True,
        env=env,
    )

# --- Definiciones para los subcomandos 'install' ---
install_app = typer.Typer(
    help="Sub-comandos para compilar llama.cpp y descargar modelos .gguf."
)
cli.add_typer(install_app, name="install")

# --- CORRECCIÓN APLICADA A TODAS LAS OPCIONES ---
OutputDirOpt = Annotated[
    Path,
    typer.Option(
        default="build/", # CORREGIDO
        help="Directorio destino donde quedará la build de llama.cpp.",
    ),
]
CudaOpt = Annotated[
    bool,
    typer.Option(
        default=True, # CORREGIDO
        help="Compilar con soporte CUDA/cuBLAS.",
        rich_help_panel="Opciones de Build"
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
        default=Path("models/"), # CORREGIDO
        help="Carpeta destino de los .gguf"
    ),
]

@install_app.command("llama")
def install_llama(output_dir: OutputDirOpt, cuda: CudaOpt) -> None:
    from .install.llama_build import build_llama_cpp
    build_llama_cpp(output_dir, cuda)
    typer.secho("✅  llama.cpp compilado correctamente.", fg=typer.colors.GREEN)

@install_app.command("models")
def install_models(names: ModelNamesArg, target_dir: TargetDirOpt) -> None:
    from .install.models_fetch import download_models
    download_models(names, target_dir)
    typer.secho("✅  Modelos descargados.", fg=typer.colors.GREEN)

# --- CORRECCIÓN APLICADA AL COMANDO 'discover' ---
TimeoutOpt = Annotated[int, typer.Option(default=5, help="Segundos de búsqueda.")]

@cli.command()
def discover(timeout: TimeoutOpt) -> None:
    from .discovery.mdns import discover_nodes
    nodes = discover_nodes(timeout=timeout)
    if nodes:
        typer.secho("🌐  Nodos LMServ encontrados:", bold=True)
        for n in nodes:
            typer.echo(f" • {n.host}:{n.port} – {n.info or 'sin descripción'}")
    else:
        typer.secho("🙁  No se detectaron nodos.", fg=typer.colors.YELLOW)

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def llama(ctx: typer.Context) -> None:
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

@cli.command()
def update() -> None:
    typer.echo("🔄  git pull origin main …")
    subprocess.run(["git", "pull", "origin", "main"], check=True)
    typer.echo("🛠️   rebuild (si aplica) …")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=True)
    typer.secho("✅  Proyecto actualizado.", fg=typer.colors.GREEN)

def _main() -> None:
    cli()

if __name__ == "__main__":
    _main()