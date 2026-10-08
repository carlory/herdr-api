#!/usr/bin/env python3
"""Tag a reviewed, merged adaptation after CI on the protected main commit."""

import os
import re

import merge_adaptation as merge


def reviewed_merge(pr, tag, commit):
    if not pr.get("merged_at") or not pr.get("merge_commit_sha") or merge.adaptation_tag(dict(pr, state="open")) != tag:
        return False
    if not merge.verify_origin(pr):
        return False
    comparison = merge.api(f"repos/{merge.REPOSITORY}/compare/{pr['merge_commit_sha']}...{commit}")
    if comparison["status"] not in ("ahead", "identical"):
        return False
    reviews = merge.pages(f"repos/{merge.REPOSITORY}/pulls/{pr['number']}/reviews")
    for review in sorted(reviews, key=lambda item: item["id"], reverse=True):
        match = re.search(r"HERDR_REVIEW: APPROVED head=([a-f0-9]{40}) base=([a-f0-9]{40}) run=(\d+)\b", review.get("body") or "")
        if match and match[1] == pr["head"]["sha"] and merge.review_decision(pr, match[1], match[2]):
            return True
    return False


def tag_commit(tag):
    refs = merge.pages(f"repos/{merge.REPOSITORY}/git/matching-refs/tags/{tag}")
    reference = next((item for item in refs if item["ref"] == f"refs/tags/{tag}"), None)
    if not reference:
        return None
    obj = reference["object"]
    for _ in range(8):
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = merge.api(f"repos/{merge.REPOSITORY}/git/tags/{obj['sha']}")["object"]
    raise RuntimeError("unexpected tag target; refusing to replace it")


def main():
    if os.environ.get("HAS_PUBLICATION_TOKEN") != "true":
        raise RuntimeError("configure the crates-io publishing token before creating a release tag")
    commit = merge.api(f"repos/{merge.REPOSITORY}/git/ref/heads/main")["object"]["sha"]
    if run_id := os.environ.get("CI_RUN_ID"):
        run = merge.api(f"repos/{merge.REPOSITORY}/actions/runs/{int(run_id)}")
    else:
        runs = merge.pages(f"repos/{merge.REPOSITORY}/actions/workflows/ci.yml/runs?branch=main&event=push", "workflow_runs")
        matching = [item for item in runs if item["head_sha"] == commit]
        if not matching:
            print("Waiting for CI on current main.")
            return
        run = max(matching, key=lambda item: item["id"])
    jobs = merge.pages(f"repos/{merge.REPOSITORY}/actions/runs/{run['id']}/jobs", "jobs")
    if not merge.ci_passed(run, jobs, commit, expected_event="push"):
        print("Waiting for successful CI on current main.")
        return
    pinned = merge.metadata(commit)
    tag = pinned["tag"]
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag) or pinned["version"] != tag[1:]:
        raise RuntimeError("invalid stable release identity")
    prs = merge.pages(f"repos/{merge.REPOSITORY}/pulls?state=closed&base=main&sort=updated&direction=desc")
    if not any(reviewed_merge(pr, tag, commit) for pr in prs):
        print("No independently reviewed merged adaptation for this version; no tag created.")
        return
    existing = tag_commit(tag)
    if existing:
        if existing != commit:
            raise RuntimeError("release tag already points elsewhere; never move a published tag")
        print(f"{tag} already identifies this commit; no tag replaced.")
        return
    if merge.api(f"repos/{merge.REPOSITORY}/git/ref/heads/main")["object"]["sha"] != commit:
        print("Main moved; waiting for its next CI run.")
        return
    obj = merge.api(f"repos/{merge.REPOSITORY}/git/tags", method="POST", data={
        "tag": tag, "message": f"herdr-api {tag}: CI and independent review verified",
        "object": commit, "type": "commit",
    })
    merge.api(f"repos/{merge.REPOSITORY}/git/refs", method="POST", data={"ref": f"refs/tags/{tag}", "sha": obj["sha"]})
    print(f"Created {tag} at {commit}; its push starts the existing Release workflow.")


if __name__ == "__main__":
    main()
