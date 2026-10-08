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
                    and re.search(rf"\brun={run['id']}\b", review["body"])]
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
        comments = merge.pages(f"repos/{merge.REPOSITORY}/issues/{pr['number']}/comments")
        claims = [match for comment in comments if comment["user"]["login"] == "github-actions[bot]"
                  and (match := re.fullmatch(r"HERDR_REPAIR_ATTEMPT: round=(\d+) head=(\S+) source=(\d+) run=(\d+)", comment.get("body") or ""))]
        if any(claim[2] == pr["head"]["sha"] and int(claim[3]) == run["id"] for claim in claims):
            print("This feedback already has a reserved repair attempt.")
            return
        round_number = len(claims) + 1
        if round_number > MAX_ROUNDS:
            print(f"PR #{pr['number']} reached the repair limit; findings remain visible and no merge is authorized.")
            return
        current = merge.api(f"repos/{merge.REPOSITORY}/pulls/{pr['number']}")
        if current["state"] != "open" or current["head"]["sha"] != pr["head"]["sha"]:
            print("PR changed; waiting for feedback on its new head.")
            return
        merge.api(f"repos/{merge.REPOSITORY}/issues/{pr['number']}/comments", method="POST", token_name="GH_TOKEN", data={
            "body": f"HERDR_REPAIR_ATTEMPT: round={round_number} head={pr['head']['sha']} source={run['id']} run={os.environ['GITHUB_RUN_ID']}",
        })
        folder = Path("artifacts/repair-input")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "feedback.md").write_text(notes)
        outputs(ready="true", number=pr["number"], head=pr["head"]["sha"], branch=pr["head"]["ref"],
                tag=merge.adaptation_tag(pr), round=round_number, source_run=run["id"])
        return


if __name__ == "__main__":
    main()
