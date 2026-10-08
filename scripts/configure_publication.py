#!/usr/bin/env python3
"""Store a crates.io publishing token without exposing it or writing it locally."""

import getpass
import subprocess

REPOSITORY = "carlory/herdr-api"


def store_token(token):
    if len(token) < 16 or any(char.isspace() for char in token):
        raise ValueError("invalid crates.io token")
    result = subprocess.run(
        ["gh", "secret", "set", "CARGO_REGISTRY_TOKEN", "--repo", REPOSITORY, "--env", "crates-io"],
        input=token, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("could not store the publishing token; credential output suppressed")


def main():
    subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
    print("Store the herdr-api crates.io publishing token; input will be hidden.")
    token = getpass.getpass("crates.io token: ")
    try:
        store_token(token)
    finally:
        token = None
    print("Stored CARGO_REGISTRY_TOKEN in the crates-io environment. No package was published.")


if __name__ == "__main__":
    main()
