"""Readiness, repair selection, tag identity, and publishing credential boundaries."""

import os
import subprocess
import unittest
from unittest.mock import patch

import configure_publication
import ready_adaptation
import repair_adaptation
import retry_automation
import tag_adaptation
from test_merge_adaptation import ci_run, jobs, pull_request


class AutonomousTests(unittest.TestCase):
    def test_ready_requires_author_completion_marker_and_verified_ci(self):
        pr = pull_request()
        pr.update(draft=True, body=pr["body"] + "\nHERDR_ADAPTATION_STATUS: READY")
        with patch.object(ready_adaptation.merge, "candidates", return_value=[(pr, ci_run())]), \
                patch.object(ready_adaptation.merge, "verified", return_value=("v0.9.3", "head", "base")), \
                patch.object(ready_adaptation.merge, "api") as api, patch("builtins.print"):
            ready_adaptation.main()
            self.assertEqual(api.call_args.args[0], "graphql")
            api.reset_mock()
            pr["body"] = pr["body"].replace("READY", "BLOCKED")
            ready_adaptation.main()
            api.assert_not_called()

    def test_only_current_failed_ci_or_bot_blocking_review_drives_repairs(self):
        pr, run = pull_request(), ci_run()
        run["conclusion"] = "failure"
        with patch.object(repair_adaptation.merge, "verify_origin", return_value=True), \
                patch.object(repair_adaptation.merge, "pages", return_value=[{"conclusion": "failure", "name": "tests", "html_url": "https://github.com/example"}]):
            self.assertIn("tests", repair_adaptation.feedback(pr, run))
            run["head_sha"] = "old"
            self.assertIsNone(repair_adaptation.feedback(pr, run))
        review_run = {"id": 300, "path": ".github/workflows/review-herdr.lock.yml"}
        review = {"id": 1, "user": {"login": "github-actions[bot]"}, "commit_id": "head",
                  "body": "HERDR_REVIEW: BLOCKED head=head base=base run=300\nFix default omission."}
        with patch.object(repair_adaptation.merge, "verify_origin", return_value=True), \
                patch.object(repair_adaptation.merge, "pages", return_value=[review]):
            self.assertIn("Fix default", repair_adaptation.feedback(pr, review_run))
            review["user"]["login"] = "someone"
            self.assertIsNone(repair_adaptation.feedback(pr, review_run))
            review["user"]["login"] = "github-actions[bot]"
            review_run["id"] = 30
            self.assertIsNone(repair_adaptation.feedback(pr, review_run))

    def test_failed_or_unpushed_repairs_still_count_toward_limit(self):
        pr = pull_request()
        run = {"id": 300, "status": "completed"}
        claims = [{"user": {"login": "github-actions[bot]"},
                   "body": f"HERDR_REPAIR_ATTEMPT: round={number} head=previous source={number} run={number}"}
                  for number in range(1, 6)]
        with patch.dict(os.environ, {"TRIGGER_RUN_ID": "300"}), \
                patch.object(repair_adaptation, "outputs"), \
                patch.object(repair_adaptation, "feedback", return_value="blocking finding"), \
                patch.object(repair_adaptation.merge, "api", return_value=run) as api, \
                patch.object(repair_adaptation.merge, "pages", side_effect=[[pr], claims]), patch("builtins.print"):
            repair_adaptation.main()
            self.assertEqual(api.call_count, 1)

    def test_tag_does_not_release_later_unrelated_main_commits(self):
        pr = pull_request()
        pr.update(merged_at="2026-10-08", merge_commit_sha="reviewed-merge")
        with patch.object(tag_adaptation.merge, "verify_origin", return_value=True), \
                patch.object(tag_adaptation.merge, "pages", return_value=[]) as pages:
            self.assertFalse(tag_adaptation.reviewed_merge(pr, "v0.9.3", "later-main"))
            pages.assert_not_called()

    def test_publication_token_is_only_sent_through_stdin_to_the_release_environment(self):
        token = "cio_fixture_not_a_real_token"
        with patch.object(configure_publication.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            configure_publication.store_token(token)
            self.assertEqual(run.call_args.kwargs["input"], token)
            self.assertNotIn(token, run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][-2:], ["--env", "crates-io"])
        with patch.object(configure_publication.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, token, token)):
            with self.assertRaises(RuntimeError) as failure:
                configure_publication.store_token(token)
            self.assertNotIn(token, str(failure.exception))

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
                patch.object(tag_adaptation, "reviewed_merge", return_value=True), \
                patch.object(tag_adaptation, "tag_commit", return_value="different"):
            with self.assertRaisesRegex(RuntimeError, "already points elsewhere"):
                tag_adaptation.main()
            self.assertEqual(api.call_count, 2)

    def test_release_retries_are_bounded_and_use_actions_token(self):
        run = {"id": 100, "status": "completed", "conclusion": "failure", "run_attempt": 2,
               "path": ".github/workflows/release.yml", "event": "push"}
        with patch.dict(os.environ, {"TRIGGER_RUN_ID": "100"}), \
                patch.object(retry_automation.merge, "api", side_effect=[run, {}]) as api, patch("builtins.print"):
            retry_automation.main()
            self.assertEqual(api.call_args.kwargs["token_name"], "GH_TOKEN")
            self.assertTrue(api.call_args.args[0].endswith("rerun-failed-jobs"))
            run["run_attempt"] = 3
            api.reset_mock()
            api.side_effect = [run]
            retry_automation.main()
            self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
