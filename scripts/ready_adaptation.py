#!/usr/bin/env python3
"""Hand a completed, CI-verified adaptation to the independent reviewer."""

import re

import merge_adaptation as merge


def main():
    for pr, run in merge.candidates():
        marker = re.findall(r"^HERDR_ADAPTATION_STATUS: (READY|BLOCKED)\s*$", pr.get("body") or "", re.MULTILINE)
        if not pr["draft"] or marker != ["READY"]:
            continue
        if not merge.verified(pr, run):
            continue
        merge.api("graphql", method="POST", data={
            "query": "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id}}}",
            "variables": {"id": pr["node_id"]},
        })
        print(f"PR #{pr['number']} is ready for independent review.")


if __name__ == "__main__":
    main()
