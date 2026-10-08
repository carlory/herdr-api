"""Deterministic update selection, authenticity requirements, and archive boundaries."""

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import upstream


def released(tag: str, prerelease=False, draft=False) -> dict:
    return {
        "tag_name": tag, "draft": draft, "prerelease": prerelease,
        "html_url": f"https://github.com/herdrdev/herdr/releases/tag/{tag}",
        "assets": [{"name": name, "state": "uploaded", "digest": "sha256:" + "a" * 64} for name in upstream.ASSETS],
    }


class UpstreamTests(unittest.TestCase):
    def test_versions_are_numeric_and_updates_are_processed_in_order(self):
        releases = [released("v0.10.0"), released("v0.9.3"), released("v0.9.10"), released("v0.9.2")]
        self.assertEqual(upstream.next_release(releases, "v0.9.2")["tag_name"], "v0.9.3")
        self.assertEqual(upstream.next_release(releases, "v0.9.3")["tag_name"], "v0.9.10")
        self.assertIsNone(upstream.next_release(releases, "v0.10.0"))

    def test_previews_prereleases_and_drafts_never_trigger_an_update(self):
        releases = [released("preview-2026-10-01"), released("v0.9.3-rc.1"), released("v0.9.3", prerelease=True), released("v0.9.4", draft=True)]
        self.assertIsNone(upstream.next_release(releases, "v0.9.2"))
        for invalid in ["v00.9.3", "v0.9", "v0.9.3+build", "v0.9.3\nkey=value"]:
            with self.subTest(tag=invalid), self.assertRaises(ValueError):
                upstream.version(invalid)

    def test_manual_target_requires_a_newer_existing_stable_release(self):
        releases = [released("v0.9.2"), released("v0.9.3"), released("v0.9.4")]
        self.assertEqual(upstream.next_release(releases, "v0.9.2", "v0.9.4")["tag_name"], "v0.9.4")
        for target in ["v0.9.2", "v9.9.9"]:
            with self.subTest(tag=target), self.assertRaises(RuntimeError):
                upstream.next_release(releases, "v0.9.2", target)

    def test_an_open_adaptation_pr_blocks_duplicates_and_concurrent_versions(self):
        releases = [released("v0.9.3")]
        pull = {"state": "open", "base": {"ref": "main"}, "head": {"ref": "adapt-herdr-v0.9.3-abcd"}, "html_url": "https://github.com/carlory/herdr-api/pull/1"}
        result = upstream.decision(releases, [pull], "v0.9.2")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "adaptation-pr-open")
        pull["state"] = "closed"
        self.assertTrue(upstream.decision(releases, [pull], "v0.9.2")["available"])
        self.assertEqual(upstream.decision(releases, [], "v0.9.3")["reason"], "up-to-date")

    def test_release_pagination_does_not_assume_first_page_has_stable_versions(self):
        first = [released(f"preview-{i}", prerelease=True) for i in range(100)]
        with patch.object(upstream, "api", side_effect=[first, [released("v0.9.3")]]) as api:
            releases = upstream.pages("herdrdev/herdr/releases")
            self.assertEqual(upstream.next_release(releases, "v0.9.2")["tag_name"], "v0.9.3")
            self.assertIn("page=2", api.call_args.args[0])

    def test_every_supported_asset_requires_an_authoritative_digest(self):
        release = released("v0.9.3")
        result = upstream.release_metadata(release, "1" * 40)
        self.assertEqual(set(result["assets"]), set(upstream.ASSETS))
        release["assets"][-1]["digest"] = None
        with self.assertRaisesRegex(RuntimeError, "windows"):
            upstream.release_metadata(release, "1" * 40)

    def test_archive_links_are_not_materialized_and_traversal_is_rejected(self):
        def archive(path, link=False):
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w:gz") as stream:
                entry = tarfile.TarInfo(path)
                if link:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = "../../outside"
                    stream.addfile(entry)
                else:
                    entry.size = 6
                    stream.addfile(entry, io.BytesIO(b"source"))
            return data.getvalue()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream.extract_source(archive("herdr-sha/src/api/schema.rs"), root)
            self.assertEqual((root / "src/api/schema.rs").read_text(), "source")
            upstream.extract_source(archive("herdr-sha/CLAUDE.md", link=True), root)
            self.assertFalse((root / "CLAUDE.md").exists())
            with self.assertRaisesRegex(RuntimeError, "unsafe"):
                upstream.extract_source(archive("herdr-sha/../../outside"), root)

    def test_network_errors_do_not_report_up_to_date(self):
        with patch.object(upstream, "urlopen", side_effect=HTTPError("https://api.github.com", 503, "unavailable", {}, None)):
            with self.assertRaisesRegex(RuntimeError, "no release decision"):
                upstream.download("https://api.github.com", api=True)


if __name__ == "__main__":
    unittest.main()
