"""An incomplete, blocked, or stale review must fail its GitHub check."""

import os
import unittest
from unittest.mock import patch

import review_adaptation as review
from test_merge_adaptation import pull_request


class ReviewTests(unittest.TestCase):
    def verdict(self, approved=True, head="head", base="base"):
        pr = pull_request()
        pr["head"]["sha"] = head
        writes = []

        def api(path, *, method="GET", data=None, token_name=None):
            if method == "PATCH":
                writes.append((data, token_name))
                return {}
            if path.endswith("pulls/3"):
                return pr
            return {"object": {"sha": base}}

        environment = {"REVIEW_PR": "3", "REVIEW_HEAD": "head", "REVIEW_BASE": "base", "REVIEW_CHECK": "123", "GITHUB_RUN_ID": "300"}
        with patch.dict(os.environ, environment), patch.object(review.merge, "api", side_effect=api), \
                patch.object(review.merge, "review_decision", return_value=approved):
            if approved and head == "head" and base == "base":
                review.verdict()
            else:
                with self.assertRaises(SystemExit):
                    review.verdict()
        return writes

    def test_approved_current_review_publishes_success_with_the_actions_check_token(self):
        writes = self.verdict()
        self.assertEqual(writes[0][0]["conclusion"], "success")
        self.assertEqual(writes[0][1], "CHECK_TOKEN")

    def test_blocked_missing_or_stale_review_publishes_failure(self):
        for options in ({"approved": False}, {"head": "new-head"}, {"base": "new-base"}):
            with self.subTest(options=options):
                self.assertEqual(self.verdict(**options)[0][0]["conclusion"], "failure")


if __name__ == "__main__":
    unittest.main()
