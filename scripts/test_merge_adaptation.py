"""Fail-closed merge gates and writes restricted to the verified PR head."""

import copy
import unittest
from unittest.mock import patch

import merge_adaptation as merge


def pull_request():
    return {
        "number": 3, "state": "open", "draft": False, "node_id": "PR_fixture",
        "title": "Adapt Herdr: Herdr v0.9.3",
        "body": "<!-- gh-aw-workflow-id: adapt-herdr -->\n"
                "<!-- gh-aw-agentic-workflow: Adapt Herdr, engine: copilot, model: auto, id: 100, workflow_id: adapt-herdr -->",
        "base": {"ref": "main", "sha": "base", "repo": {"full_name": merge.REPOSITORY}},
        "head": {"ref": "adapt-herdr-v0.9.3-abc", "sha": "head", "repo": {"full_name": merge.REPOSITORY}},
    }


def ci_run():
    return {
        "id": 200, "path": ".github/workflows/ci.yml", "event": "pull_request",
        "status": "completed", "conclusion": "success", "head_sha": "head",
        "pull_requests": [{"number": 3, "head": {"sha": "head"}, "base": {"sha": "base"}}],
    }


def jobs():
    return [{"name": name, "status": "completed", "conclusion": "success"} for name in merge.REQUIRED_JOBS]


class MergeTests(unittest.TestCase):
    def test_other_branches_forks_unmarked_and_nonstable_prs_are_ineligible(self):
        original = pull_request()
        self.assertEqual(merge.adaptation_tag(original), "v0.9.3")
        for mutate in (
            lambda pr: pr.update(state="closed"),
            lambda pr: pr.update(body="ordinary PR"),
            lambda pr: pr["base"].update(ref="other"),
            lambda pr: pr["head"]["repo"].update(full_name="other/herdr-api"),
            lambda pr: pr["head"].update(ref="adapt-herdr-v0.9.3-rc.1"),
            lambda pr: pr["head"].update(ref="adapt-herdr-v00.9.3"),
        ):
            pr = copy.deepcopy(original)
            mutate(pr)
            self.assertIsNone(merge.adaptation_tag(pr))

    def test_ci_requires_all_jobs_success_on_exact_head(self):
        self.assertTrue(merge.ci_passed(ci_run(), jobs(), "head"))
        self.assertFalse(merge.ci_passed(ci_run(), jobs(), "new-head"))
        self.assertFalse(merge.ci_passed(ci_run(), jobs()[1:], "head"))
        for conclusion in ("failure", "skipped", "cancelled", "neutral", None):
            checks = jobs()
            checks[0]["conclusion"] = conclusion
            self.assertFalse(merge.ci_passed(ci_run(), checks, "head"))
        for key, value in (("event", "push"), ("status", "in_progress"), ("path", ".github/workflows/other.yml")):
            run = ci_run()
            run[key] = value
            self.assertFalse(merge.ci_passed(run, jobs(), "head"))

    def exercise(self, *, run=None, files=None, base="base", current=None, target="v0.9.3", origin=True):
        writes = []

        def api(path, *, method="GET", data=None):
            if method != "GET":
                writes.append((path, method, data))
                return {"merged": True, "sha": "merged"}
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            if path.endswith("pulls/3"):
                return current or pull_request()
            raise AssertionError(f"unexpected read: {path}")

        with patch.object(merge, "api", side_effect=api), \
                patch.object(merge, "pages", side_effect=[jobs(), files or [{"filename": "upstream.toml"}]]), \
                patch.object(merge, "verify_origin", return_value=origin), \
                patch.object(merge, "metadata", side_effect=[{"tag": target, "version": target[1:]}, {"tag": "v0.9.2"}]), \
                patch("builtins.print"):
            merge.merge(pull_request(), run or ci_run())
        return writes

    def test_ci_verified_pr_is_merged_with_head_lock(self):
        writes = self.exercise()
        self.assertEqual(writes[0][0], f"repos/{merge.REPOSITORY}/pulls/3/merge")
        self.assertEqual(writes[0][2]["sha"], "head")
        self.assertEqual(writes[0][2]["merge_method"], "squash")

    def test_stale_base_updates_branch_and_waits_for_new_ci(self):
        writes = self.exercise(base="new-base")
        self.assertEqual(writes, [(f"repos/{merge.REPOSITORY}/pulls/3/update-branch", "PUT", {"expected_head_sha": "head"})])

    def test_failed_ci_unverified_origin_and_racing_head_never_merge(self):
        run = ci_run()
        run["conclusion"] = "failure"
        self.assertEqual(self.exercise(run=run), [])
        self.assertEqual(self.exercise(origin=False), [])
        current = pull_request()
        current["head"]["sha"] = "changed"
        self.assertEqual(self.exercise(current=current), [])

    def test_protected_paths_renames_and_nonadvancing_versions_are_blocked(self):
        for file in (
            {"filename": ".github/workflows/ci.yml"},
            {"filename": "src/AGENTS.md"},
            {"filename": "src/lib.rs", "previous_filename": ".github/workflows/ci.yml"},
        ):
            with self.assertRaisesRegex(RuntimeError, "protected path"):
                self.exercise(files=[file])
        with self.assertRaisesRegex(RuntimeError, "advance"):
                self.exercise(target="v0.9.2")



if __name__ == "__main__":
    unittest.main()
