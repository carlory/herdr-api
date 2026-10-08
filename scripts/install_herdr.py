#!/usr/bin/env python3
"""Install the pinned official release; never compile Herdr or use latest."""

import argparse
import hashlib
import io
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def install(destination: Path, metadata=None) -> Path:
    if metadata is None:
        metadata = tomllib.loads((ROOT / "upstream.toml").read_text())
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[platform.system()]
    arch = {"x86_64": "x86_64", "AMD64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}[
        platform.machine()
    ]
    asset = f"herdr-{system}-{arch}" + (".zip" if system == "windows" else "")
    expected = metadata["assets"][asset]
    url = f'{metadata["repository"]}/releases/download/{metadata["tag"]}/{asset}'
    request = urllib.request.Request(url, headers={"User-Agent": "carlory/herdr-api CI"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise RuntimeError(f"SHA-256 mismatch for {asset}: expected {expected}, got {digest}")
    if system == "windows":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates = [name for name in archive.namelist() if Path(name).name == "herdr.exe"]
            if len(candidates) != 1:
                raise RuntimeError("release archive must contain exactly one herdr.exe")
            data = archive.read(candidates[0])
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination.resolve() / ("herdr.exe" if system == "windows" else "herdr")
    with tempfile.NamedTemporaryFile(
        dir=destination, suffix=".exe" if system == "windows" else "", delete=False
    ) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.chmod(0o755)
        version = subprocess.check_output([str(temporary_path), "--version"], text=True).strip()
        if version != f'herdr {metadata["version"]}':
            raise RuntimeError(f"unexpected release version: {version}")
        os.replace(temporary_path, binary)
    finally:
        temporary_path.unlink(missing_ok=True)
    return binary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?", default=ROOT / ".tools")
    args = parser.parse_args()
    print(install(args.destination))
