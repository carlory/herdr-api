#!/usr/bin/env python3
"""Validate and prepare releases; publishing commands are explicitly selected."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tomllib
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "carlory/herdr-api"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def output(**values) -> None:
    for key, value in values.items():
        print(f"{key}={value}")
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with open(destination, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


def metadata(root: Path, tag: str) -> dict:
    package = tomllib.loads((root / "Cargo.toml").read_text())["package"]
    if package.get("publish") is not False:
        raise RuntimeError("registry publication must be disabled in Cargo.toml")
    upstream = tomllib.loads((root / "upstream.toml").read_text())
    version = package["version"]
    if package["name"] != "herdr-api" or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("only stable herdr-api releases are supported")
    if tag != f"v{version}" or version != upstream["version"] or tag != upstream["tag"]:
        raise RuntimeError("release tag, Cargo version, and pinned Herdr version must match")
    lock = tomllib.loads((root / "Cargo.lock").read_text())
    own = [p for p in lock["package"] if p["name"] == package["name"] and "source" not in p]
    if len(own) != 1 or own[0]["version"] != version:
        raise RuntimeError("Cargo.lock does not match the crate version")
    source = (root / "src/lib.rs").read_text()
    for name, expected in [
        ("HERDR_VERSION", f'"{version}"'),
        ("PROTOCOL_VERSION", str(upstream["protocol"])),
        ("SCHEMA_VERSION", str(upstream["schema_version"])),
    ]:
        match = re.search(rf"pub const {name}: [^=]+ = ([^;]+);", source)
        if match is None or match[1] != expected:
            raise RuntimeError(f"{name} disagrees with upstream.toml")
    return {
        "name": package["name"], "version": version, "tag": tag,
        "repository": REPOSITORY, "herdr": upstream,
    }


def check(tag: str, require_tag: bool = False) -> dict:
    result = metadata(ROOT, tag)
    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("release checkout must be clean")
    commit = git("rev-parse", "HEAD")
    if require_tag and git("rev-parse", f"refs/tags/{tag}^{{commit}}") != commit:
        raise RuntimeError("tag must identify the checked-out commit")
    result["commit"] = commit
    return result


def validate_package(package: Path, identity: dict) -> None:
    prefix = f"{identity['name']}-{identity['version']}"
    with tarfile.open(package, "r:gz") as archive:
        vcs = json.load(archive.extractfile(f"{prefix}/.cargo_vcs_info.json"))
        manifest = tomllib.loads(archive.extractfile(f"{prefix}/Cargo.toml").read().decode())
    if manifest["package"].get("publish") is not False:
        raise RuntimeError("release package must disable registry publication")
    if manifest["package"]["name"] != identity["name"] or manifest["package"]["version"] != identity["version"]:
        raise RuntimeError("package identity differs from the checkout")
    if vcs["git"]["sha1"] != identity["commit"] or vcs["git"].get("dirty", False):
        raise RuntimeError("package must come from the clean release commit")


def prepare(tag: str, package_dir: Path, dist: Path) -> None:
    identity = check(tag)
    filename = f"{identity['name']}-{identity['version']}.crate"
    package = package_dir / filename
    validate_package(package, identity)
    # Never retain stale assets from an earlier local candidate.
    if dist.exists() and any(dist.iterdir()):
        raise RuntimeError("candidate directory must be empty; use a new --dist directory")
    for name in ["upstream.schema.json", "extracted.schema.json"]:
        document = json.loads((ROOT / "artifacts" / name).read_text())
        if document["protocol"] != identity["herdr"]["protocol"] or document["schema_version"] != identity["herdr"]["schema_version"]:
            raise RuntimeError(f"{name} has incorrect protocol metadata")
    if json.loads((ROOT / "artifacts/upstream.schema.json").read_text()) != json.loads((ROOT / "artifacts/extracted.schema.json").read_text()):
        raise RuntimeError("candidate schemas do not match")
    dist.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package, dist / filename)
    for name in ["upstream.schema.json", "extracted.schema.json"]:
        shutil.copyfile(ROOT / "artifacts" / name, dist / name)
    shutil.copyfile(ROOT / "upstream.toml", dist / "upstream.toml")
    (dist / "release.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    upstream = identity["herdr"]
    notes = (
        f"# herdr-api {identity['version']}\n\n"
        f"Unofficial Rust protocol types for [Herdr {upstream['version']}]"
        f"({upstream['repository']}/tree/{upstream['tag']}).\n\n"
        f"- Herdr protocol: {upstream['protocol']}; Schema document version: {upstream['schema_version']}.\n"
        f"- Source commit: `{identity['commit']}`.\n"
        "- Includes requests, responses, events, and referenced protocol types.\n"
        "- No Herdr runtime, socket client, or CLI wrapper.\n"
        "- Linux, macOS, and Windows checks install the pinned official binary and compare Schema.\n"
        "- Linux and macOS additionally verify real socket and plugin hook payloads.\n\n"
        f'```toml\nherdr-api = {{ git = "https://github.com/{REPOSITORY}", tag = "{identity["tag"]}" }}\n```\n\n'
        "Release assets include the crate, both Schema documents, extraction provenance, "
        "and SHA-256 checksums. Schema parity does not prove every server-side validation rule.\n"
    )
    (dist / "release-notes.md").write_text(notes, encoding="utf-8")
    sums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(dist.iterdir()))
    (dist / "SHA256SUMS").write_text(sums, encoding="utf-8")
    verify_candidate(dist)
    print(f"Prepared {tag} at {identity['commit']} in {dist}")


def verify_candidate(dist: Path) -> dict:
    identity = json.loads((dist / "release.json").read_text())
    if identity["repository"] != REPOSITORY or not re.fullmatch(r"\d+\.\d+\.\d+", identity["version"]) or identity["tag"] != f"v{identity['version']}":
        raise RuntimeError("invalid release candidate identity")
    expected = {
        f"herdr-api-{identity['version']}.crate", "upstream.schema.json",
        "extracted.schema.json", "upstream.toml", "release.json", "release-notes.md",
    }
    if {p.name for p in dist.iterdir()} != expected | {"SHA256SUMS"}:
        raise RuntimeError("unexpected or missing candidate files")
    listed = {}
    for line in (dist / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name not in expected or name in listed or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError("invalid checksum manifest")
        listed[name] = digest
        if sha256(dist / name) != digest:
            raise RuntimeError(f"candidate SHA-256 mismatch: {name}")
    if set(listed) != expected:
        raise RuntimeError("checksum manifest is incomplete")
    validate_package(dist / f"herdr-api-{identity['version']}.crate", identity)
    return identity


def request(url: str, *, method="GET", data=None, token=None, content_type="application/json", missing_ok=False):
    headers = {"User-Agent": "carlory-herdr-api-release", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if data is not None:
        headers["Content-Type"] = content_type
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
    try:
        with urlopen(Request(url, headers=headers, method=method, data=data), timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            if missing_ok and error.code == 404:
                return None
            # Do not expose response bodies or authorization headers in CI logs.
            raise RuntimeError(f"{method} {urlparse(url).hostname}: HTTP {error.code}") from None
        finally:
            error.close()


def guard(dist: Path) -> dict:
    identity = verify_candidate(dist)
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != f"refs/tags/{identity['tag']}" or os.environ.get("GITHUB_SHA") != identity["commit"]:
        raise RuntimeError("GitHub publishing requires the validated repository, tag event, and commit")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required")
    # A deleted or moved tag must never be recreated by the Releases API.
    base = f"https://api.github.com/repos/{REPOSITORY}/git"
    ref = request(f"{base}/ref/tags/{identity['tag']}", token=token)["object"]
    while ref["type"] == "tag":
        ref = request(f"{base}/tags/{ref['sha']}", token=token)["object"]
    if ref["type"] != "commit" or ref["sha"] != identity["commit"]:
        raise RuntimeError("remote release tag no longer identifies the reviewed commit")
    return identity


def github_release(dist: Path) -> None:
    identity = guard(dist)
    token = os.environ["GH_TOKEN"]
    base = f"https://api.github.com/repos/{REPOSITORY}/releases"
    body = (dist / "release-notes.md").read_text(encoding="utf-8")
    release = request(f"{base}/tags/{identity['tag']}", token=token, missing_ok=True)
    if release is None:
        # The tag endpoint only returns published releases. Resume an authenticated
        # draft through the list endpoint after an interrupted asset upload.
        page = 1
        while True:
            releases = request(f"{base}?per_page=100&page={page}", token=token)
            matches = [r for r in releases if r["tag_name"] == identity["tag"]]
            if len(matches) > 1:
                raise RuntimeError("multiple GitHub drafts identify the release tag")
            if matches:
                release = matches[0]
                break
            if len(releases) < 100:
                break
            page += 1
    if release is None:
        release = request(base, method="POST", token=token, data={
            "tag_name": identity["tag"], "target_commitish": identity["commit"],
            "name": f"herdr-api {identity['version']}", "body": body,
            "draft": True, "prerelease": False,
        })
    if release["tag_name"] != identity["tag"] or release["body"] != body or release["prerelease"]:
        raise RuntimeError("existing GitHub Release differs from the candidate")
    upload = release["upload_url"].split("{", 1)[0]
    if urlparse(upload).scheme != "https" or urlparse(upload).hostname != "uploads.github.com":
        raise RuntimeError("unexpected GitHub asset upload URL")
    assets = {asset["name"]: asset for asset in release["assets"]}
    if set(assets) - {p.name for p in dist.iterdir()}:
        raise RuntimeError("existing GitHub Release has unexpected assets")
    for path in sorted(dist.iterdir()):
        if path.name in assets:
            if assets[path.name].get("digest") != f"sha256:{sha256(path)}":
                raise RuntimeError(f"existing GitHub asset differs or has no verifiable digest: {path.name}")
            continue
        if not release["draft"]:
            raise RuntimeError("published GitHub Release is incomplete; refusing to mutate it")
        asset = request(f"{upload}?name={quote(path.name)}", method="POST", token=token,
                        data=path.read_bytes(), content_type="application/octet-stream")
        if asset.get("digest") != f"sha256:{sha256(path)}":
            raise RuntimeError(f"GitHub upload digest mismatch: {path.name}")
    if release["draft"]:
        request(f"{base}/{release['id']}", method="PATCH", token=token, data={"draft": False})
    print(f"GitHub Release complete: https://github.com/{REPOSITORY}/releases/tag/{identity['tag']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("check")
    preflight.add_argument("--tag", required=True)
    preflight.add_argument("--require-tag", action="store_true")
    candidate = commands.add_parser("prepare")
    candidate.add_argument("--tag", required=True)
    candidate.add_argument("--package-dir", type=Path, required=True)
    candidate.add_argument("--dist", type=Path, default=ROOT / "dist")
    publish = commands.add_parser("github")
    publish.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check":
        result = check(args.tag, args.require_tag)
        output(tag=result["tag"], version=result["version"])
    elif args.command == "prepare":
        prepare(args.tag, args.package_dir, args.dist)
    else:
        github_release(args.dist)


if __name__ == "__main__":
    main()
