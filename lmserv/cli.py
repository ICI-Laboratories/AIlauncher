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
        default=2,  # <-- CORREGIDO
        min=1,
        show_default=True,
        help="Número de procesos llama-cli en paralelo.",
    ),
]

HostOpt = Annotated[
    str, typer.Option(default="0.0.0.0", help="Interfaz en la que escuchará FastAPI.")  # <-- CORREGIDO
]

PortOpt = Annotated[
    int, typer.Option(default=8000, help="Puerto HTTP para el endpoint REST.")  # <-- CORREGIDO
]

MaxTokOpt = Annotated[
    int, typer.Option(default=128, help="Límite de tokens a generar por petición.")  # <-- CORREGIDO
]

LLamaBinOpt = Annotated[
    Optional[Path],
    typer.Option(
        default=None,  # <-- CORREGIDO
        exists=True,
        dir_okay=False,
        writable=False,
        help="Ruta al ejecutable `llama-cli` (si no está en $PATH).",
    ),
]

@cli.command()
def serve(
    # --- La firma de la función ahora usa las anotaciones directamente ---
    model_path: ModelPathOpt,
    workers: WorkersOpt,
    host: HostOpt,
    port: PortOpt,
    max_tokens: MaxTokOpt,
    llama_bin: LLamaBinOpt,
) -> None:
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

install_app = typer.Typer(
    help="Sub-comandos para compilar llama.cpp y descargar modelos .gguf."
)
cli.add_typer(install_app, name="install")

@install_app.command("llama")
def install_llama(
    output_dir: Annotated[
        Path,
        typer.Option(
            "build/",
            help="Directorio destino donde quedará la build de llama.cpp.",
        ),
    ],
    cuda: Annotated[
        bool,
        typer.Option(
            True,
            "--cuda/--no-cuda",
            help="Compilar con soporte CUDA/cuBLAS.",
        ),
    ] = True,
) -> None:
    from .install.llama_build import build_llama_cpp

    build_llama_cpp(output_dir, cuda)
    typer.secho("✅  llama.cpp compilado correctamente.", fg=typer.colors.GREEN)

@install_app.command("models")
def install_models(
    names: Annotated[
        list[str],
        typer.Argument(
            ...,
            help="Nombre corto de modelos a bajar (p.e. ‘gemma-2b’, ‘phi3-mini’).",
        ),
    ],
    target_dir: Annotated[
        Path,
        typer.Option("models/", help="Carpeta destino de los .gguf"),
    ] = Path("models/"),
) -> None:
    from .install.models_fetch import download_models

    download_models(names, target_dir)
    typer.secho("✅  Modelos descargados.", fg=typer.colors.GREEN)

@cli.command()
def discover(timeout: Annotated[int, typer.Option(5, help="Segundos de búsqueda.")] = 5) -> None:
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
    cmd = [cfg.llama_bin, *ctx.args]
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