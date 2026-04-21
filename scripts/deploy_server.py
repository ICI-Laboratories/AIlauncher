from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


EXCLUDE_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "paper",
    "runtime",
    "logs",
    ".env",
    ".venv",
    "env",
    "venv",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _require_command(name: str) -> None:
    if shutil.which(name):
        return
    raise SystemExit(f"No se encontro el comando requerido: {name}")


def _make_archive(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = Path(tempfile.gettempdir()) / f"ailauncher-release-{timestamp}.tar.gz"

    with tarfile.open(archive_path, "w:gz") as tar:
        for path in repo_root.rglob("*"):
            rel = path.relative_to(repo_root)
            if set(rel.parts) & EXCLUDE_PARTS:
                continue
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            tar.add(path, arcname=str(rel))

    return archive_path


def _run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _remote_script() -> str:
    return """#!/usr/bin/env bash
set -Eeuo pipefail

ARCHIVE_PATH="$1"
STAMP="$2"

APP_ROOT="/opt/ailauncher/app"
VENV_ROOT="/opt/ailauncher/venv"
BACKUP_DIR="/srv/ai-data/ailauncher/archive"
TMP_DIR="$(mktemp -d /tmp/ailauncher-update-XXXXXX)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

sudo -v

mkdir -p "$TMP_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$TMP_DIR"

if [ -d "$APP_ROOT" ]; then
  sudo mkdir -p "$BACKUP_DIR"
  sudo tar -czf "$BACKUP_DIR/app-${STAMP}.tar.gz" -C "$APP_ROOT" .
fi

sudo systemctl stop ailauncher
sudo mkdir -p "$APP_ROOT"
sudo rsync -a --delete "$TMP_DIR"/ "$APP_ROOT"/
sudo chown -R ailauncher:ailauncher "$APP_ROOT"
sudo "$VENV_ROOT/bin/python" -m pip install "$APP_ROOT"
sudo systemctl start ailauncher
sleep 3
curl -fsS http://127.0.0.1:8009/health
echo
sudo /usr/local/bin/ailauncher-check
echo
rm -f "$ARCHIVE_PATH"
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Despliega AIlauncher al servidor remoto.")
    parser.add_argument("--host", required=True, help="Host o IP del servidor")
    parser.add_argument("--user", required=True, help="Usuario SSH")
    parser.add_argument("--port", type=int, default=22, help="Puerto SSH")
    args = parser.parse_args()

    _require_command("ssh")
    _require_command("scp")

    repo_root = _repo_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = _make_archive(repo_root)
    remote_archive = f"/tmp/ailauncher-release-{stamp}.tar.gz"
    remote_script = f"/tmp/ailauncher-deploy-{stamp}.sh"
    ssh_target = f"{args.user}@{args.host}"

    try:
        local_script = Path(tempfile.gettempdir()) / f"ailauncher-deploy-{stamp}.sh"
        local_script.write_text(_remote_script(), encoding="utf-8")

        _run(["scp", "-P", str(args.port), str(archive_path), ssh_target + ":" + remote_archive])
        _run(["scp", "-P", str(args.port), str(local_script), ssh_target + ":" + remote_script])
        _run(
            [
                "ssh",
                "-t",
                "-p",
                str(args.port),
                ssh_target,
                f"bash {remote_script} {remote_archive} {stamp} && rm -f {remote_script}",
            ]
        )
    finally:
        if archive_path.exists():
            archive_path.unlink()
        if "local_script" in locals() and local_script.exists():
            local_script.unlink()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
