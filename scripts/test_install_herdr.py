"""Regression checks for release selection and integrity before execution."""

import io
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import install_herdr


class DownloadReached(Exception):
    pass


class ReleaseInstallerTests(unittest.TestCase):
    def test_all_supported_platforms_resolve_a_pinned_release_asset(self):
        # A dotted Windows archive name must be a literal TOML key, not a table.
        for system, arch, asset in [
            ("Linux", "x86_64", "herdr-linux-x86_64"),
            ("Linux", "aarch64", "herdr-linux-aarch64"),
            ("Darwin", "arm64", "herdr-macos-aarch64"),
            ("Darwin", "x86_64", "herdr-macos-x86_64"),
            ("Windows", "AMD64", "herdr-windows-x86_64.zip"),
        ]:
            with self.subTest(asset=asset), patch("platform.system", return_value=system), patch(
                "platform.machine", return_value=arch
            ), patch("urllib.request.urlopen", side_effect=DownloadReached) as download:
                with self.assertRaises(DownloadReached):
                    install_herdr.install(Path("unused-install-destination"))
                request = download.call_args.args[0]
                self.assertEqual(
                    request.full_url,
                    f"https://github.com/herdrdev/herdr/releases/download/{tomllib.loads((install_herdr.ROOT / 'upstream.toml').read_text())['tag']}/{asset}",
                )

    def test_corrupted_asset_is_never_installed_or_executed(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "platform.system", return_value="Linux"
        ), patch("platform.machine", return_value="x86_64"), patch(
            "urllib.request.urlopen", return_value=io.BytesIO(b"corrupted release")
        ), patch("subprocess.check_output") as execute:
            target = Path(directory) / "bin"
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                install_herdr.install(target)
            self.assertFalse(target.exists())
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
