#!/usr/bin/env python3
"""Select current CI/review feedback for a bounded author-agent repair turn."""

import os
from pathlib import Path
import re

import merge_adaptation as merge
from review_adaptation import outputs

MAX_ROUNDS = 5


def feedback(pr, run):
    if not merge.adaptation_tag(pr) or not merge.verify_origin(pr):
        return None
    if run["path"] == ".github/workflows/ci.yml":
        if run["event"] != "pull_request" or run["head_sha"] != pr["head"]["sha"] or run["conclusion"] != "failure":
            return None
        jobs = merge.pages(f"repos/{merge.REPOSITORY}/actions/runs/{run['id']}/jobs", "jobs")
        failed = [job for job in jobs if job["conclusion"] == "failure"]
        if not failed:
            return None
        return "CI failed. Inspect the actual logs for these jobs:\n" + "\n".join(f"- {job['name']}: {job['html_url']}" for job in failed)
    if run["path"] == ".github/workflows/review-herdr.lock.yml":
        reviews = merge.pages(f"repos/{merge.REPOSITORY}/pulls/{pr['number']}/reviews")
        matching = [review for review in reviews if review["user"]["login"] == "github-actions[bot]"
                    and review["commit_id"] == pr["head"]["sha"]
                    and f"HERDR_REVIEW: BLOCKED head={pr['head']['sha']} " in (review.get("body") or "")
                    and f"run={run['id']}" in review["body"]]
        if matching:
            return max(matching, key=lambda item: item["id"])["body"]
    return None


def main():
    outputs(ready="false")
    run = merge.api(f"repos/{merge.REPOSITORY}/actions/runs/{int(os.environ['TRIGGER_RUN_ID'])}")
    if run["status"] != "completed":
        return
    for pr in merge.pages(f"repos/{merge.REPOSITORY}/pulls?state=open&base=main"):
        notes = feedback(pr, run)
        if notes is None:
            continue
        commits = merge.pages(f"repos/{merge.REPOSITORY}/pulls/{pr['number']}/commits")
        rounds = [int(match[1]) for commit in commits
                  if (match := re.match(r"Repair Herdr round (\d+)\b", commit["commit"]["message"]))]
        round_number = max(rounds, default=0) + 1
        if round_number > MAX_ROUNDS:
            print(f"PR #{pr['number']} reached the repair limit; findings remain visible and no merge is authorized.")
            return
        folder = Path("artifacts/repair-input")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "feedback.md").write_text(notes)
        outputs(ready="true", number=pr["number"], head=pr["head"]["sha"], branch=pr["head"]["ref"],
                tag=merge.adaptation_tag(pr), round=round_number, source_run=run["id"])
        return


if __name__ == "__main__":
    main()
