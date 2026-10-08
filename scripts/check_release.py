#!/usr/bin/env python3
"""Export the official binary's Schema and run parity and live protocol tests."""

import argparse
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def check(binary: Path) -> None:
    binary = binary.resolve()
    metadata = tomllib.loads((ROOT / "upstream.toml").read_text())
    manifest = tomllib.loads((ROOT / "Cargo.toml").read_text())
    if manifest["package"]["version"] != metadata["version"]:
        raise RuntimeError("Cargo version must match the pinned Herdr release")
    version = subprocess.check_output([str(binary), "--version"], text=True).strip()
    if version != f'herdr {metadata["version"]}':
        raise RuntimeError(f"expected Herdr {metadata['version']}, got {version}")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    schema = artifacts / "upstream.schema.json"
    subprocess.run([str(binary), "api", "schema", "--output", str(schema)], check=True)
    env = os.environ.copy()
    env["HERDR_API_SCHEMA"] = str(schema)
    env["HERDR_BIN_PATH"] = str(binary)
    subprocess.run(
        ["cargo", "test", "--locked", "--test", "schema_parity", "--", "--ignored"],
        cwd=ROOT, env=env, check=True,
    )
    if os.name != "nt":
        subprocess.run(
            ["cargo", "test", "--locked", "--test", "live_release", "--", "--ignored"],
            cwd=ROOT, env=env, check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    check(parser.parse_args().binary)
