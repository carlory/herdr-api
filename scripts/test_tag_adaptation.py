"""Only a CI-verified adaptation merge can receive its immutable version tag."""

import os
import unittest
from unittest.mock import patch

import tag_adaptation
from test_merge_adaptation import ci_run, jobs, pull_request


class TagTests(unittest.TestCase):
    def test_tag_does_not_release_later_unrelated_main_commits(self):
        pr = pull_request()
        pr.update(merged_at="2026-10-08", merge_commit_sha="reviewed-merge")
        with patch.object(tag_adaptation.merge, "verify_origin", return_value=True), \
                patch.object(tag_adaptation.merge, "pages", return_value=[]) as pages:
            self.assertFalse(tag_adaptation.verified_merge(pr, "v0.9.3", "later-main"))
            pages.assert_not_called()

    def test_tag_requires_publication_auth_and_never_overwrites_other_commits(self):
        with patch.dict(os.environ, {"HAS_PUBLICATION_TOKEN": "false"}), patch.object(tag_adaptation.merge, "api") as api:
            with self.assertRaises(RuntimeError):
                tag_adaptation.main()
            api.assert_not_called()
        run = ci_run()
        run.update(event="push", head_sha="main")
        with patch.dict(os.environ, {"HAS_PUBLICATION_TOKEN": "true", "CI_RUN_ID": "200"}), \
                patch.object(tag_adaptation.merge, "api", side_effect=[{"object": {"sha": "main"}}, run]) as api, \
                patch.object(tag_adaptation.merge, "pages", side_effect=[jobs(), [pull_request()]]), \
                patch.object(tag_adaptation.merge, "metadata", return_value={"tag": "v0.9.3", "version": "0.9.3"}), \
                patch.object(tag_adaptation, "verified_merge", return_value=True), \
                patch.object(tag_adaptation, "tag_commit", return_value="different"):
            with self.assertRaisesRegex(RuntimeError, "already points elsewhere"):
                tag_adaptation.main()
            self.assertEqual(api.call_count, 2)



if __name__ == "__main__":
    unittest.main()
