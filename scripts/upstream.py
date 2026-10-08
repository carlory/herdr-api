#!/usr/bin/env python3
"""Detect stable Herdr releases and stage verified inputs for protocol adaptation."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import install_herdr

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "herdrdev/herdr"
ASSETS = (
    "herdr-linux-x86_64", "herdr-linux-aarch64", "herdr-macos-aarch64",
    "herdr-macos-x86_64", "herdr-windows-x86_64.zip",
)


def version(tag: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError(f"not a stable release tag: {tag!r}")
    return tuple(int(part) for part in tag[1:].split("."))


def download(url: str, api=False) -> bytes:
    headers = {"User-Agent": "carlory-herdr-api-upstream"}
    if api and (token := os.environ.get("GH_TOKEN")):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=120) as response:
            return response.read()
    except HTTPError as error:
        try:
            raise RuntimeError(f"upstream HTTP {error.code}; no release decision was made") from None
        finally:
            error.close()


def api(path: str):
    return json.loads(download(f"https://api.github.com/repos/{path}", api=True))


def pages(path: str) -> list:
    items = []
    page = 1
    while True:
        batch = api(f"{path}?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("unexpected paginated GitHub API response")
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def next_release(releases: list, current: str, requested: str = ""):
    baseline = version(current)
    eligible = []
    for release in releases:
        if release["draft"] or release["prerelease"]:
            continue
        try:
            candidate = version(release["tag_name"])
        except ValueError:
            continue
        if candidate > baseline:
            eligible.append((candidate, release))
    eligible.sort(key=lambda entry: entry[0])
    if requested:
        version(requested)
        matches = [release for _, release in eligible if release["tag_name"] == requested]
        if len(matches) != 1:
            raise RuntimeError("requested version must be a newer published stable Herdr release")
        return matches[0]
    return eligible[0][1] if eligible else None


def decision(releases: list, pulls: list, current: str, requested: str = "") -> dict:
    target = next_release(releases, current, requested)
    result = {"current": current, "available": False, "tag": "", "reason": "up-to-date"}
    if target is None:
        return result
    result.update(tag=target["tag_name"], url=target["html_url"])
    for pull in pulls:
        if pull["state"] == "open" and pull["base"]["ref"] == "main" and pull["head"]["ref"].startswith("adapt-herdr-"):
            result.update(reason="adaptation-pr-open", pull_request=pull["html_url"])
            return result
    result.update(available=True, reason="new-stable-release")
    return result


def detect(requested: str, repository: str) -> dict:
    pinned = tomllib.loads((ROOT / "upstream.toml").read_text())
    result = decision(pages(f"{UPSTREAM}/releases"), pages(f"{repository}/pulls"), pinned["tag"], requested)
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with open(destination, "a", encoding="utf-8") as stream:
            for key in ["available", "tag", "reason"]:
                value = str(result[key]).lower() if isinstance(result[key], bool) else result[key]
                stream.write(f"{key}={value}\n")
    ROOT.joinpath("artifacts").mkdir(exist_ok=True)
    ROOT.joinpath("artifacts/upstream-detection.json").write_text(json.dumps(result, indent=2) + "\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"Pinned Herdr: `{result['current']}`. Detection: `{result['reason']}`.\n")
            if result["tag"]:
                stream.write(f"Target: [{result['tag']}]({result['url']}).\n")
            if "pull_request" in result:
                stream.write(f"Existing adaptation: {result['pull_request']}\n")
    print(json.dumps(result, indent=2))
    return result


def release_metadata(release: dict, commit: str) -> dict:
    version(release["tag_name"])
    if release["draft"] or release["prerelease"] or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("only a published stable release at a full commit SHA can be staged")
    assets = {asset["name"]: asset for asset in release["assets"]}
    digests = {}
    for name in ASSETS:
        asset = assets.get(name, {})
        digest = asset.get("digest") or ""
        if asset.get("state") != "uploaded" or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise RuntimeError(f"release lacks a verified asset digest for {name}; adaptation requires investigation")
        digests[name] = digest.removeprefix("sha256:")
    return {
        "repository": f"https://github.com/{UPSTREAM}",
        "version": release["tag_name"][1:], "tag": release["tag_name"],
        "commit": commit, "assets": digests,
    }


def extract_source(data: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            if not parts or ".." in parts or PurePosixPath(member.name).is_absolute():
                raise RuntimeError("unsafe upstream archive path")
            # Never extract symlinks, devices, or files outside the source root.
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                # Upstream has a CLAUDE.md -> AGENTS.md alias. It is not a
                # protocol input, and links are never materialized locally.
                continue
            if not member.isfile() or len(parts) < 2:
                raise RuntimeError("unexpected upstream archive entry")
            target = destination.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())


def stage(tag: str) -> Path:
    version(tag)
    release = api(f"{UPSTREAM}/releases/tags/{tag}")
    ref = api(f"{UPSTREAM}/git/ref/tags/{tag}")["object"]
    while ref["type"] == "tag":
        ref = api(f"{UPSTREAM}/git/tags/{ref['sha']}")["object"]
    if ref["type"] != "commit":
        raise RuntimeError("release tag does not identify a commit")
    metadata = release_metadata(release, ref["sha"])
    destination = ROOT / ".upstream" / tag
    if destination.exists():
        raise RuntimeError("staging destination already exists; inspect it before retrying")
    data = download(f"https://codeload.github.com/{UPSTREAM}/tar.gz/{metadata['commit']}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        work = Path(temporary) / "staged"
        extract_source(data, work / "source")
        binary = install_herdr.install(work / "bin", metadata)
        schema_path = work / "official.schema.json"
        subprocess.run([str(binary), "api", "schema", "--output", str(schema_path)], check=True)
        schema = json.loads(schema_path.read_text())
        metadata.update(protocol=schema["protocol"], schema_version=schema["schema_version"])
        (work / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        work.rename(destination)
    print(destination)
    return destination


def write_metadata(staged: Path, extra_sources: list[str], omit_sources: list[str]) -> None:
    metadata = json.loads((staged / "metadata.json").read_text())
    version(metadata["tag"])
    current = tomllib.loads((ROOT / "upstream.toml").read_text())
    source = staged / "source"
    paths = {entry["path"] for entry in current["sources"]}
    paths.update(path.relative_to(source).as_posix() for path in (source / "src/api/schema").rglob("*.rs"))
    paths.update(extra_sources)
    for name in omit_sources:
        if (source / name).exists():
            raise RuntimeError(f"cannot omit an existing source from provenance: {name}")
    paths.difference_update(omit_sources)
    fingerprints = []
    for name in sorted(paths):
        path = source / name
        if not path.resolve().is_relative_to(source.resolve()) or not path.is_file():
            raise RuntimeError(f"source moved or is missing: {name}; investigate before updating provenance")
        fingerprints.append((name, hashlib.sha256(path.read_bytes()).hexdigest()))
    lines = [f"{key} = {json.dumps(metadata[key])}" for key in ["repository", "version", "tag", "commit", "protocol", "schema_version"]]
    for name, digest in fingerprints:
        lines.extend(["", "[[sources]]", f"path = {json.dumps(name)}", f"sha256 = {json.dumps(digest)}"])
    lines.extend(["", "[assets]"])
    lines.extend(f"{json.dumps(name)} = {json.dumps(digest)}" for name, digest in metadata["assets"].items())
    ROOT.joinpath("upstream.toml").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    detect_command = commands.add_parser("detect")
    detect_command.add_argument("--tag", default="")
    detect_command.add_argument("--repository", default="carlory/herdr-api")
    stage_command = commands.add_parser("stage")
    stage_command.add_argument("--tag", required=True)
    promote = commands.add_parser("write-metadata")
    promote.add_argument("staged", type=Path)
    promote.add_argument("--extra-source", action="append", default=[])
    promote.add_argument("--omit-source", action="append", default=[])
    args = parser.parse_args()
    if args.command == "detect":
        detect(args.tag, args.repository)
    elif args.command == "stage":
        stage(args.tag)
    else:
        write_metadata(args.staged, args.extra_source, args.omit_source)


if __name__ == "__main__":
    main()
