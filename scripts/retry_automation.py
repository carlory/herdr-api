#!/usr/bin/env python3
"""Bounded retries for infrastructure/incomplete reviews and release failures."""

import os
import re

import merge_adaptation as merge


def main():
    run = merge.api(f"repos/{merge.REPOSITORY}/actions/runs/{int(os.environ['TRIGGER_RUN_ID'])}")
    if run["status"] != "completed" or run["conclusion"] != "failure" or run["run_attempt"] >= 3:
        return
    if run["path"] == ".github/workflows/review-herdr.lock.yml":
        for pr in merge.pages(f"repos/{merge.REPOSITORY}/pulls?state=open&base=main"):
            if not merge.adaptation_tag(pr):
                continue
            reviews = merge.pages(f"repos/{merge.REPOSITORY}/pulls/{pr['number']}/reviews")
            if any(item["user"]["login"] == "github-actions[bot]" and
                   re.search(rf"HERDR_REVIEW: (APPROVED|BLOCKED) head=[a-f0-9]{{40}} base=[a-f0-9]{{40}} run={run['id']}\b", item.get("body") or "")
                   for item in reviews):
                print("Reviewer reached a decision; the author repair workflow handles blockers.")
                return
        path = f"repos/{merge.REPOSITORY}/actions/runs/{run['id']}/rerun"
    elif run["path"] == ".github/workflows/release.yml" and run["event"] == "push":
        path = f"repos/{merge.REPOSITORY}/actions/runs/{run['id']}/rerun-failed-jobs"
    else:
        return
    merge.api(path, method="POST", token_name="GH_TOKEN")
    print(f"Retried failed automation run {run['id']}; maximum three attempts.")


if __name__ == "__main__":
    main()
