"""
LMServ – mini-LM Studio
=======================

Paquete raíz.  Mantiene metadatos de la distribución y expone algunos
utilidades de alto nivel sin cargar toda la aplicación (evita ciclos
de importación innecesarios).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

# ---------------------------------------------------------------------------#
# Metadatos
# ---------------------------------------------------------------------------#
try:
    __version__: str = _pkg_version(__name__)
except PackageNotFoundError:  # running from source tree
    __version__ = "0.0.0.dev0"

# ---------------------------------------------------------------------------#
# API pública mínima
# ---------------------------------------------------------------------------#
from .config import Config  # noqa: E402  (import tardío para evitar ciclos)


def run_cli() -> None:
    """
    Punto de entrada “amigable” para lanzar la CLI desde código:

    ```python
    import lmserv
    lmserv.run_cli()
    ```
    """
    # Importación diferida para no forzar Typer si sólo se
    # usa `Config` en un entorno sin CLI.
    from .cli import cli  # noqa: WPS433, E402 (importación diferida)

    cli()


__all__ = [
    "__version__",
    "Config",
    "run_cli",
]
