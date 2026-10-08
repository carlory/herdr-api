#!/usr/bin/env python3
"""Store one dedicated token in both secrets and run the adaptation test."""

import getpass
import json
import subprocess

REPOSITORY = "carlory/herdr-api"
SECRETS = ("COPILOT_GITHUB_TOKEN", "GH_AW_CI_TRIGGER_TOKEN")


def store_secret(name: str, token: str) -> None:
    if name not in SECRETS:
        raise ValueError("unsupported credential destination")
    if not token.startswith("github_pat_") or any(char.isspace() for char in token):
        raise ValueError("use a dedicated fine-grained GitHub PAT, not a broad classic token")
    result = subprocess.run(
        ["gh", "secret", "set", name, "--repo", REPOSITORY],
        input=token, text=True, capture_output=True,
    )
    if result.returncode:
        # Do not relay subprocess output that could echo credential material.
        raise RuntimeError(f"could not store {name}; verify gh authentication and repository access")


def main() -> None:
    subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
    print("Configure one dedicated fine-grained token; input will be hidden.")
    print("Personal owner, Copilot Requests Read; only herdr-api, Contents and Pull requests Read/Write.")
    token = getpass.getpass("Herdr adaptation token: ")
    try:
        for name in SECRETS:
            store_secret(name, token)
            print(f"Stored {name}.")
    finally:
        token = None
    result = subprocess.run(
        ["gh", "secret", "list", "--repo", REPOSITORY, "--json", "name"],
        check=True, text=True, capture_output=True,
    )
    if not set(SECRETS).issubset({secret["name"] for secret in json.loads(result.stdout)}):
        raise RuntimeError("secret names were not confirmed in the repository")
    subprocess.run(
        ["gh", "workflow", "run", "adapt-herdr.lock.yml", "--repo", REPOSITORY, "--ref", "main"],
        check=True,
    )
    print("Adaptation dispatched; its PR will merge automatically after CI and independent review pass.")


if __name__ == "__main__":
    main()
