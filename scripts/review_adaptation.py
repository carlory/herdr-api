#!/usr/bin/env python3
"""Prepare pinned review inputs and publish a deterministic GitHub review check."""

import os
from pathlib import Path
import sys

import merge_adaptation as merge

CHECK_NAME = "Review Herdr adaptation"


def outputs(**values):
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def prepare():
    outputs(ready="false")
    for pr, run in merge.candidates():
        if pr["draft"]:
            continue
        result = merge.verified(pr, run)
        if not result:
            continue
        tag, head, base = result
        check = merge.api(f"repos/{merge.REPOSITORY}/check-runs", method="POST", token_name="CHECK_TOKEN", data={
            "name": CHECK_NAME, "head_sha": head, "status": "in_progress",
            "details_url": f"https://github.com/{merge.REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        })
        outputs(ready="true", number=pr["number"], head=head, base=base, tag=tag, check=check["id"])
        return
    print("No eligible adaptation with current passing CI to review.")


def verdict():
    number, head, base = int(os.environ["REVIEW_PR"]), os.environ["REVIEW_HEAD"], os.environ["REVIEW_BASE"]
    pr = merge.api(f"repos/{merge.REPOSITORY}/pulls/{number}")
    current_base = merge.api(f"repos/{merge.REPOSITORY}/git/ref/heads/main")["object"]["sha"]
    passed = (merge.adaptation_tag(pr) is not None and pr["head"]["sha"] == head and current_base == base
              and merge.review_decision(pr, head, base, expected_run=int(os.environ["GITHUB_RUN_ID"])))
    merge.api(f"repos/{merge.REPOSITORY}/check-runs/{int(os.environ['REVIEW_CHECK'])}", method="PATCH", token_name="CHECK_TOKEN", data={
        "status": "completed", "conclusion": "success" if passed else "failure",
        "output": {"title": "Review approved" if passed else "Review blocked or incomplete",
                   "summary": "Independent review approved this exact head and base." if passed else
                              "No valid approval for the current head/base. See the review run and PR findings."},
    })
    if not passed:
        raise SystemExit("Independent review did not approve the current adaptation.")


if __name__ == "__main__":
    {"prepare": prepare, "verdict": verdict}[sys.argv[1]]()
