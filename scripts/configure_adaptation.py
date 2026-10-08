#!/usr/bin/env python3
"""Store dedicated credentials with hidden input and run the adaptation test."""

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
    print("Configure dedicated tokens for carlory/herdr-api; input will be hidden.")
    print("COPILOT_GITHUB_TOKEN: personal owner, Copilot Requests Read.")
    print("GH_AW_CI_TRIGGER_TOKEN: only herdr-api, Contents and Pull requests Read/Write.")
    for name in SECRETS:
        token = getpass.getpass(f"{name}: ")
        try:
            store_secret(name, token)
        finally:
            token = None
        print(f"Stored {name}.")
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
    print("Adaptation dispatched; check the run and resulting draft PR before merging.")


if __name__ == "__main__":
    main()
