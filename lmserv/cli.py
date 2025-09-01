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

# --- Opciones de Typer ---
ModelOpt = Annotated[str, typer.Option("--model", "-m", help="ID de Hugging Face o ruta a un .gguf local.", rich_help_panel="Parámetros del Servidor")]
WorkersOpt = Annotated[int, typer.Option("--workers", "-w", min=1, help="Número de workers de llama.cpp.", rich_help_panel="Parámetros del Servidor")]
HostOpt = Annotated[str, typer.Option("--host", "-H", help="Interfaz de red para el servidor.", rich_help_panel="Parámetros del Servidor")]
PortOpt = Annotated[int, typer.Option("--port", "-p", help="Puerto HTTP para el servidor.", rich_help_panel="Parámetros del Servidor")]
LLamaBinOpt = Annotated[Optional[Path], typer.Option("--llama-bin", exists=True, dir_okay=False, help="Ruta al binario `llama-cli`.", rich_help_panel="Parámetros del Servidor")]

# --- Opciones de Llama ---
CtxSizeOpt = Annotated[int, typer.Option("--ctx-size", help="Tamaño del contexto en tokens.", rich_help_panel="Parámetros del Modelo")]
NGpuLayersOpt = Annotated[int, typer.Option("--n-gpu-layers", help="Número de capas a descargar en GPU.", rich_help_panel="Parámetros del Modelo")]
MaxTokOpt = Annotated[int, typer.Option("--max-tokens", help="Límite de tokens por respuesta.", rich_help_panel="Parámetros del Modelo")]
LoraOpt = Annotated[Optional[Path], typer.Option("--lora", exists=True, dir_okay=False, help="Ruta a un adaptador LoRA (.gguf).", rich_help_panel="Parámetros del Modelo")]
ToolsOpt = Annotated[Optional[Path], typer.Option("--tools", exists=True, dir_okay=False, help="Ruta a un fichero JSON con la definición de herramientas.", rich_help_panel="Parámetros del Modelo")]


# ─────────────── Comandos ───────────────

@cli.command()
def serve(
    # --- Opciones del Servidor ---
    model: ModelOpt,
    workers: WorkersOpt = 2,
    host: HostOpt = "0.0.0.0",
    port: PortOpt = 8000,
    llama_bin: LLamaBinOpt = None,
    # --- Opciones del Modelo ---
    ctx_size: CtxSizeOpt = 2048,
    n_gpu_layers: NGpuLayersOpt = 0,
    max_tokens: MaxTokOpt = 1024,
    lora: LoraOpt = None,
    tools: ToolsOpt = None,
) -> None:
    """Lanza la API REST y los *workers* de llama.cpp."""
    # Configura el entorno para el proceso de Uvicorn
    env = os.environ.copy()
    env.update({
        "MODEL": model,
        "WORKERS": str(workers),
        "HOST": host,
        "PORT": str(port),
        "MAX_TOKENS": str(max_tokens),
        "CTX_SIZE": str(ctx_size),
        "N_GPU_LAYERS": str(n_gpu_layers),
    })
    if llama_bin:
        env["LLAMA_BIN"] = str(llama_bin.resolve())
    if lora:
        env["LORA"] = str(lora.resolve())
    if tools:
        env["TOOLS_PATH"] = str(tools.resolve())

    # Lanza el servidor
    typer.echo(f"🚀  Levantando LMServ en http://{host}:{port}")
    typer.echo(f"   • Modelo: {model}")
    if lora:
        typer.echo(f"   • LoRA: {lora.name}")
    if tools:
        typer.echo(f"   • Herramientas: {tools.name}")
    typer.echo(f"   • Workers: {workers}, Contexto: {ctx_size} tokens, GPU Layers: {n_gpu_layers}")

    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "lmserv.server.api:app", "--host", host, "--port", str(port)],
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError:
        # Uvicorn usualmente es interrumpido con Ctrl+C, lo cual es normal.
        typer.echo("\n👋  Servidor detenido.")
    except Exception as e:
        typer.secho(f"💥 Error inesperado al lanzar Uvicorn: {e}", fg="red")
        raise typer.Exit(1)

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