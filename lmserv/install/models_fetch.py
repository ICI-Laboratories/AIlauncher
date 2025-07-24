# lmserv/install/models_fetch.py

from __future__ import annotations
import hashlib
import os
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Iterable, List, Tuple
import requests
from tqdm.auto import tqdm

_CATALOG: dict[str, Tuple[str, str]] = {
    "gemma-3-12b-it-GGUF": (
        "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q8_0.gguf?download=true",
        "3e85f7a1d0e6a4acaf7dc8e0e73de79099d32e905e8da3dfd5b0e353e1acf4ad",
    ),
    "phi3-mini": (
        "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-GGUF/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        "e19b2a96f8e74e770f13fd99a20c4d2c3fcf3ff0b1f5564a96b7c3aa5e5f3ca6",
    ),
    "mistral-7b-instruct": (
        "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/mistral-7b-instruct-v0.3.Q4_K_M.gguf",
        "d7e70b6d552bf4c59436b25d08e3f92b2101af97d9e0c1b09e4100e1bad7d0eb",
    ),
}
_CHUNK = 2 << 20

def download_models(names: Iterable[str], target_dir: Path | str) -> None:
    target_dir = Path(target_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    names = list(names)
    _validate_names(names)

    for n in names:
        url, sha = _CATALOG[n]
        dest = target_dir / Path(url).name
        _download_with_resume(url, dest)
        _verify_sha256(dest, sha)
        _maybe_decompress(dest)

def _validate_names(names: List[str]) -> None:
    unknown = [n for n in names if n not in _CATALOG]
    if unknown:
        raise ValueError(f"Modelos no reconocidos: {', '.join(unknown)}")

def _download_with_resume(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    headers = {}
    pos = tmp.stat().st_size if tmp.exists() else 0
    if pos:
        headers["Range"] = f"bytes={pos}-"

    with requests.get(url, stream=True, headers=headers, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        mode = "ab" if pos else "wb"

        with open(tmp, mode) as fh, tqdm(
            total=total + pos,
            initial=pos,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=dest.name,
        ) as bar:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                fh.write(chunk)
                bar.update(len(chunk))

    tmp.replace(dest)

def _verify_sha256(file: Path, sha_expected: str) -> None:
    sha = hashlib.sha256()
    with open(file, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    if digest != sha_expected:
        file.unlink(missing_ok=True)
        raise RuntimeError(f"SHA256 mismatch para {file.name}: {digest} ≠ {sha_expected}")
    print(f"✓ Checksum OK – {file.name}")

def _maybe_decompress(file: Path) -> None:
    if file.suffixes[-2:] in ([".tar", ".gz"], [".tar", ".zst"]):
        print(f"📦  Descomprimiendo {file.name} …")
        with tarfile.open(file, "r:*") as tar:
            tar.extractall(path=file.parent)
        file.unlink()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m lmserv.install.models_fetch <modelo1> <modelo2> ...")
        sys.exit(1)
    download_models(sys.argv[1:], Path("models/"))