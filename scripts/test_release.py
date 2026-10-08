"""Release invariants and recovery without publishing to either service."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import release


def candidate(directory: Path) -> dict:
    identity = {
        "name": "herdr-api", "version": "0.9.3", "tag": "v0.9.3",
        "commit": "1" * 40, "repository": "carlory/herdr-api",
    }
    prefix = "herdr-api-0.9.3"
    with tarfile.open(directory / f"{prefix}.crate", "w:gz") as archive:
        for name, content in {
            "Cargo.toml": '[package]\nname = "herdr-api"\nversion = "0.9.3"\n',
            ".cargo_vcs_info.json": json.dumps({"git": {"sha1": identity["commit"]}}),
        }.items():
            data = content.encode()
            entry = tarfile.TarInfo(f"{prefix}/{name}")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    for name, content in {
        "release.json": json.dumps(identity), "release-notes.md": "release notes\n",
        "upstream.toml": 'version = "0.9.3"\n',
        "upstream.schema.json": "{}", "extracted.schema.json": "{}",
    }.items():
        (directory / name).write_text(content, encoding="utf-8")
    (directory / "SHA256SUMS").write_text(
        "".join(f"{release.sha256(p)}  {p.name}\n" for p in sorted(directory.iterdir())),
        encoding="utf-8",
    )
    return identity


class ReleaseTests(unittest.TestCase):
    def test_pinned_metadata_and_candidate_tag(self):
        pinned = tomllib.loads((release.ROOT / "upstream.toml").read_text())
        self.assertEqual(release.metadata(release.ROOT, pinned["tag"])["version"], pinned["version"])
        for tag in ["v999.999.999", pinned["version"], pinned["tag"] + "-rc.1", pinned["tag"] + "\nkey=value"]:
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                release.metadata(release.ROOT, tag)

    def test_protocol_constant_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["Cargo.toml", "Cargo.lock", "upstream.toml", "src/lib.rs"]:
                target = root / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((release.ROOT / name).read_bytes())
            source = root / "src/lib.rs"
            pinned = tomllib.loads((root / "upstream.toml").read_text())
            before = f"PROTOCOL_VERSION: u32 = {pinned['protocol']}"
            after = f"PROTOCOL_VERSION: u32 = {pinned['protocol'] + 1}"
            source.write_text(source.read_text().replace(before, after))
            with self.assertRaisesRegex(RuntimeError, "PROTOCOL_VERSION"):
                release.metadata(root, pinned["tag"])

    def test_modified_or_unexpected_asset_fails_before_network(self):
        for kind in ["modified", "extra", "incomplete", "traversal"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                dist = Path(directory)
                candidate(dist)
                release.verify_candidate(dist)
                if kind == "modified":
                    (dist / "release-notes.md").write_text("changed")
                elif kind == "extra":
                    (dist / "extra.txt").write_text("extra")
                elif kind == "incomplete":
                    sums = dist / "SHA256SUMS"
                    sums.write_text("\n".join(sums.read_text().splitlines()[1:]))
                else:
                    (dist / "SHA256SUMS").write_text("0" * 64 + "  ../outside\n")
                with patch.object(release, "request") as network:
                    with self.assertRaises(RuntimeError):
                        release.registry(dist)
                    network.assert_not_called()

    def test_registry_retry_requires_identical_non_yanked_package(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            candidate(dist)
            checksum = release.sha256(dist / "herdr-api-0.9.3.crate")
            with patch.object(release, "request", return_value=None):
                self.assertFalse(release.registry(dist))
            with patch.object(release, "request", return_value={"version": {"checksum": checksum, "yanked": False}}):
                self.assertTrue(release.registry(dist))
            for digest, yanked in [("0" * 64, False), (checksum, True)]:
                with patch.object(release, "request", return_value={"version": {"checksum": digest, "yanked": yanked}}):
                    with self.assertRaises(RuntimeError):
                        release.registry(dist)

    def test_http_errors_are_not_mistaken_for_absent_versions(self):
        url = "https://crates.io/api/v1/crates/herdr-api/0.9.3"
        for status in [401, 403, 429, 500, 503]:
            error = HTTPError(url, status, "error", {}, None)
            with patch.object(release, "urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                    release.request(url, missing_ok=True)
        with patch.object(release, "urlopen", side_effect=HTTPError(url, 404, "missing", {}, None)):
            self.assertIsNone(release.request(url, missing_ok=True))

    def test_github_draft_resumes_after_partial_upload_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            identity = candidate(dist)
            state = {"release": None, "creates": 0, "fail_once": True, "uploads": []}

            def api(url, *, method="GET", data=None, **kwargs):
                if method == "GET" and "/git/ref/" in url:
                    return {"object": {"type": "commit", "sha": identity["commit"]}}
                if method == "GET" and "/tags/" in url:
                    # GitHub's tag endpoint cannot find a draft.
                    return copy.deepcopy(state["release"]) if state["release"] and not state["release"]["draft"] else None
                if method == "GET":
                    return [copy.deepcopy(state["release"])] if state["release"] else []
                if method == "POST" and url.endswith("/releases"):
                    state["creates"] += 1
                    state["release"] = dict(data, id=42, assets=[], upload_url="https://uploads.github.com/repos/carlory/herdr-api/releases/42/assets{?name,label}")
                    return copy.deepcopy(state["release"])
                if method == "POST":
                    name = parse_qs(urlparse(url).query)["name"][0]
                    if state["fail_once"] and state["uploads"]:
                        state["fail_once"] = False
                        raise RuntimeError("interrupted upload")
                    self.assertNotIn(name, state["uploads"])
                    asset = {"name": name, "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
                    state["release"]["assets"].append(asset)
                    state["uploads"].append(name)
                    return asset
                self.assertEqual(method, "PATCH")
                self.assertEqual(len(state["uploads"]), len(list(dist.iterdir())))
                state["release"]["draft"] = False
                return copy.deepcopy(state["release"])

            environment = {
                "GH_TOKEN": "test-token", "GITHUB_REPOSITORY": release.REPOSITORY,
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/tags/v0.9.3", "GITHUB_SHA": identity["commit"],
            }
            with patch.dict("os.environ", environment), patch.object(release, "request", side_effect=api):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    release.github_release(dist)
                self.assertTrue(state["release"]["draft"])
                release.github_release(dist)
                self.assertFalse(state["release"]["draft"])
                self.assertEqual(state["creates"], 1)
                release.github_release(dist)
                self.assertEqual(state["creates"], 1)
                state["release"]["assets"][0]["digest"] = "sha256:" + "0" * 64
                with self.assertRaisesRegex(RuntimeError, "existing GitHub asset"):
                    release.github_release(dist)

    def test_github_cannot_publish_from_a_manual_branch_run(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            identity = candidate(dist)
            with patch.dict("os.environ", {
                "GITHUB_REPOSITORY": release.REPOSITORY,
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": identity["commit"],
            }), patch.object(release, "request") as network:
                with self.assertRaisesRegex(RuntimeError, "tag event"):
                    release.github_release(dist)
                network.assert_not_called()

    def test_remote_annotated_tag_must_still_identify_the_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            identity = candidate(dist)
            environment = {
                "GH_TOKEN": "test-token", "GITHUB_REPOSITORY": release.REPOSITORY,
                "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/tags/v0.9.3",
                "GITHUB_SHA": identity["commit"],
            }
            annotated = {"object": {"type": "tag", "sha": "2" * 40}}
            commit = {"object": {"type": "commit", "sha": identity["commit"]}}
            with patch.dict("os.environ", environment), patch.object(
                release, "request", side_effect=[annotated, commit]
            ) as network:
                self.assertEqual(release.guard(dist)["commit"], identity["commit"])
                self.assertEqual(network.call_count, 2)
            moved = {"object": {"type": "commit", "sha": "3" * 40}}
            with patch.dict("os.environ", environment), patch.object(
                release, "request", return_value=moved
            ):
                with self.assertRaisesRegex(RuntimeError, "remote release tag"):
                    release.github_release(dist)


if __name__ == "__main__":
    unittest.main()
