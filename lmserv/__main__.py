"""CLI principal para correr el servicio o actualizar llama.cpp."""
import os, sys, subprocess
import typer
from .config import Config

cli = typer.Typer(add_completion=False, help="lmserv – servicio LLM sobre llama.cpp")

@cli.command()
def serve(
    model_path: str = typer.Option(None, help="Ruta al modelo .gguf"),
    workers: int = typer.Option(None, help="Número de procesos paralelos"),
    port: int = typer.Option(None, help="Puerto HTTP"),
):
    cfg = Config.from_cli(model_path=model_path, workers=workers, port=port)
    os.environ.update({
        "MODEL_PATH": cfg.model_path,
        "WORKERS": str(cfg.workers),
        "PORT": str(cfg.port),
    })
    # Arrancamos Uvicorn en el mismo intérprete
    subprocess.run([
        sys.executable, "-m", "uvicorn", "lmserv.api:app",
        "--host", cfg.host, "--port", str(cfg.port)
    ], check=True)

@cli.command()
def update():
    """Hace git pull y recompila llama.cpp a través de pip."""
    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "."], check=True)
    typer.echo("llama.cpp actualizado y recompilado ✔")

if __name__ == "__main__":
    cli()