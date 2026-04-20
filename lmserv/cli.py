from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

cli = typer.Typer(
    add_completion=False,
    help="CLI principal de LMLauncher. Usa `lmserv <comando> --help` para detalles.",
    no_args_is_help=True,
)


ModelOpt = Annotated[
    Optional[str],
    typer.Option(
        "--model",
        "-m",
        help="ID de Hugging Face, etiqueta de Ollama o ruta a un .gguf local.",
        rich_help_panel="Parametros del Servidor",
    ),
]
CatalogOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--catalog",
        exists=True,
        dir_okay=False,
        help="Ruta a un catalogo JSON de modelos/backends.",
        rich_help_panel="Parametros del Servidor",
    ),
]
BackendOpt = Annotated[
    str,
    typer.Option(
        "--backend",
        help="Backend para el modo simple: llama_cpp u ollama.",
        rich_help_panel="Parametros del Servidor",
    ),
]
WorkersOpt = Annotated[
    int,
    typer.Option(
        "--workers",
        "-w",
        min=1,
        help="Numero de workers para runtimes persistentes.",
        rich_help_panel="Parametros del Servidor",
    ),
]
HostOpt = Annotated[
    str,
    typer.Option("--host", "-H", help="Interfaz de red del gateway.", rich_help_panel="Parametros del Servidor"),
]
PortOpt = Annotated[
    int,
    typer.Option("--port", "-p", help="Puerto HTTP del gateway.", rich_help_panel="Parametros del Servidor"),
]
LLamaBinOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--llama-bin",
        exists=True,
        help="Ruta al binario `llama-cli`.",
        rich_help_panel="Parametros del Servidor",
    ),
]
OllamaBaseUrlOpt = Annotated[
    str,
    typer.Option(
        "--ollama-base-url",
        help="URL base del servidor Ollama.",
        rich_help_panel="Parametros del Servidor",
    ),
]
CtxSizeOpt = Annotated[
    int,
    typer.Option("--ctx-size", help="Tamano del contexto en tokens.", rich_help_panel="Parametros del Modelo"),
]
NGpuLayersOpt = Annotated[
    int,
    typer.Option("--n-gpu-layers", help="Capas descargadas a GPU.", rich_help_panel="Parametros del Modelo"),
]
MaxTokOpt = Annotated[
    int,
    typer.Option("--max-tokens", help="Limite de tokens por respuesta.", rich_help_panel="Parametros del Modelo"),
]
LoraOpt = Annotated[
    Optional[Path],
    typer.Option("--lora", exists=True, dir_okay=False, help="Ruta a un adaptador LoRA (.gguf)."),
]
ToolsOpt = Annotated[
    Optional[Path],
    typer.Option("--tools", exists=True, dir_okay=False, help="Ruta a un fichero JSON con herramientas."),
]
RequestLogPathOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--request-log-path",
        help="Ruta JSONL para auditar prompts, respuestas y uso del gateway.",
        rich_help_panel="Observabilidad",
    ),
]
RequestLogContentOpt = Annotated[
    bool,
    typer.Option(
        "--request-log-include-content/--request-log-no-content",
        help="Guarda contenido truncado de prompts y respuestas en el log de auditoria.",
        rich_help_panel="Observabilidad",
    ),
]
RequestLogMaxCharsOpt = Annotated[
    int,
    typer.Option(
        "--request-log-max-chars",
        min=256,
        help="Maximo de caracteres guardados por prompt/respuesta en el log.",
        rich_help_panel="Observabilidad",
    ),
]


@cli.command()
def serve(
    model: ModelOpt = None,
    catalog: CatalogOpt = None,
    backend: BackendOpt = "llama_cpp",
    workers: WorkersOpt = 2,
    host: HostOpt = "0.0.0.0",
    port: PortOpt = 8000,
    llama_bin: LLamaBinOpt = None,
    ollama_base_url: OllamaBaseUrlOpt = "http://localhost:11434",
    ctx_size: CtxSizeOpt = 2048,
    n_gpu_layers: NGpuLayersOpt = 0,
    max_tokens: MaxTokOpt = 1024,
    lora: LoraOpt = None,
    tools: ToolsOpt = None,
    request_log_path: RequestLogPathOpt = None,
    request_log_include_content: RequestLogContentOpt = False,
    request_log_max_chars: RequestLogMaxCharsOpt = 12000,
) -> None:
    """Lanza el gateway HTTP y los runtimes configurados."""
    if not model and not catalog:
        typer.secho("Debes indicar --model o --catalog.", fg="red")
        raise typer.Exit(1)

    env = os.environ.copy()
    env.update(
        {
            "MODEL": model or "",
            "MODEL_BACKEND": backend,
            "WORKERS": str(workers),
            "HOST": host,
            "PORT": str(port),
            "OLLAMA_BASE_URL": ollama_base_url,
            "MAX_TOKENS": str(max_tokens),
            "CTX_SIZE": str(ctx_size),
            "N_GPU_LAYERS": str(n_gpu_layers),
        }
    )

    if catalog:
        env["MODEL_CATALOG_PATH"] = str(catalog.resolve())
    if llama_bin:
        env["LLAMA_BIN"] = str(llama_bin.resolve())
    if lora:
        env["LORA"] = str(lora.resolve())
    if tools:
        env["TOOLS_PATH"] = str(tools.resolve())
    if request_log_path:
        env["REQUEST_LOG_PATH"] = str(request_log_path.expanduser().resolve())
        env["REQUEST_LOG_INCLUDE_CONTENT"] = "1" if request_log_include_content else "0"
        env["REQUEST_LOG_MAX_CHARS"] = str(request_log_max_chars)

    typer.echo(f"Levantando LMLauncher Gateway en http://{host}:{port}")
    if catalog:
        typer.echo(f"  Catalogo: {catalog.name}")
    if model:
        typer.echo(f"  Modelo: {model}")
        typer.echo(f"  Backend: {backend}")
    if backend == "ollama":
        typer.echo(f"  Ollama base URL: {ollama_base_url}")
    typer.echo(f"  Workers: {workers}")
    typer.echo(f"  Contexto: {ctx_size} tokens")
    typer.echo(f"  GPU Layers: {n_gpu_layers}")
    if lora:
        typer.echo(f"  LoRA: {lora.name}")
    if tools:
        typer.echo(f"  Herramientas: {tools.name}")
    if request_log_path:
        typer.echo(f"  Request log: {request_log_path}")
        typer.echo(f"  Guardar contenido: {'si' if request_log_include_content else 'no'}")
        typer.echo(f"  Max chars log: {request_log_max_chars}")

    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "lmserv.server.api:app", "--host", host, "--port", str(port)],
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError:
        typer.echo("\nServidor detenido.")
    except Exception as exc:
        typer.secho(f"Error inesperado al lanzar Uvicorn: {exc}", fg="red")
        raise typer.Exit(1)


install_app = typer.Typer(help="Sub-comandos para compilar llama.cpp.")
cli.add_typer(install_app, name="install")


@install_app.command("llama")
def install_llama(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Directorio destino de la build.", resolve_path=True),
    ] = Path("build/"),
    cuda: Annotated[
        bool,
        typer.Option("--cuda/--no-cuda", help="Compilar con soporte CUDA/cuBLAS."),
    ] = True,
) -> None:
    """Compila llama.cpp con o sin soporte CUDA."""
    from .install.llama_build import build_llama_cpp

    build_llama_cpp(output_dir, cuda=cuda)
    typer.secho("llama.cpp compilado correctamente.", fg=typer.colors.GREEN)


@cli.command()
def discover(timeout: Annotated[int, typer.Option("--timeout", "-t", help="Segundos de busqueda.")] = 5) -> None:
    """Busca nodos LMLauncher via mDNS."""
    from .discovery.mdns import discover_nodes

    nodes = discover_nodes(timeout=timeout)
    if nodes:
        typer.secho("Nodos LMLauncher encontrados:", bold=True)
        for node in nodes:
            typer.echo(f" - {node.host}:{node.port} - {node.info or 'sin descripcion'}")
    else:
        typer.secho("No se detectaron nodos.", fg=typer.colors.YELLOW)


@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def llama(ctx: typer.Context, llama_bin: LLamaBinOpt = None) -> None:
    """Reenvia cualquier argumento directamente a `llama-cli`."""
    llama_path = _resolve_llama_bin_from_opts_or_env(llama_bin)
    cmd = [str(llama_path), *ctx.args]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        typer.secho("`llama-cli` no encontrado.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except subprocess.CalledProcessError as exc:
        typer.secho(f"`llama-cli` devolvio codigo {exc.returncode}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(exc.returncode)


@cli.command()
def update() -> None:
    """Hace `git pull` y reinstala el paquete en editable."""
    typer.echo("git pull origin main ...")
    subprocess.run(["git", "pull", "origin", "main"], check=True)
    typer.echo("rebuild ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=True)
    typer.secho("Proyecto actualizado.", fg=typer.colors.GREEN)


def _resolve_llama_bin_from_opts_or_env(llama_bin: Optional[Path]) -> Path:
    if llama_bin:
        return llama_bin.resolve()

    env_path = os.getenv("LLAMA_BIN")
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if candidate.is_dir():
            candidate = candidate / "llama-cli"
        if candidate.exists():
            return candidate

    if which := shutil.which("llama-cli"):
        return Path(which)

    raise FileNotFoundError("No se encontro `llama-cli`.")


def _main() -> None:
    cli()


if __name__ == "__main__":
    _main()
