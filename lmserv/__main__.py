"""
CLI de lmserv basado en Typer.

Comandos:
  serve         – Arranca FastAPI + pool de workers
  llama [args]  – Reenvía args al binario llama-cli (help, etc.)
  update        – git pull + rebuild (si lo configuraste)
"""
import subprocess, sys, os
import typer
from .config import Config

cli = typer.Typer(add_completion=False, help="CLI para lmserv")

# --------------------------------------------------------------------
# COMANDO: serve
# --------------------------------------------------------------------
@cli.command()
def serve(
    model_path: str  = typer.Option(..., help="Ruta al modelo .gguf"),
    workers   : int  = typer.Option(2,   help="Número de workers paralelos"),
    llama_bin : str | None = typer.Option(None, help="Ruta al ejecutable llama-cli"),
    host      : str  = typer.Option("0.0.0.0"),
    port      : int  = typer.Option(8000, help="Puerto HTTP"),
    max_tokens: int  = typer.Option(128, help="Máximo tokens a generar por petición"),
):
    """
    Arranca FastAPI + pool de workers.
    Exportamos los parámetros a variables de entorno.
    """
    env = os.environ.copy()
    env["MODEL_PATH"]  = model_path
    env["WORKERS"]     = str(workers)
    env["HOST"]        = host
    env["PORT"]        = str(port)
    env["MAX_TOKENS"]  = str(max_tokens)
    if llama_bin:
        env["LLAMA_BIN"] = llama_bin

    subprocess.run(
        [
            sys.executable, "-m", "uvicorn", "lmserv.api:app",
            "--host", host, "--port", str(port)
        ],
        check=True,
        env=env,
    )


# --------------------------------------------------------------------
# COMANDO: llama (proxy de ayuda)
# --------------------------------------------------------------------
@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def llama(ctx: typer.Context):
    """
    Re-envía cualquier argumento a llama-cli y muestra su salida.
    Ejemplos:
      python -m lmserv llama --help
      python -m lmserv llama --log-disable --version
    """
    cfg = Config()
    cmd = [cfg.llama_bin, *ctx.args]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        typer.echo("llama-cli no encontrado; pasa --llama-bin o exporta $LLAMA_BIN", err=True)
        raise typer.Exit(1)

# --------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------
if __name__ == "__main__":
    cli()
