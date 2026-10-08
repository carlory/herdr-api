#!/usr/bin/env python3
"""Merge workflow-created adaptations only after CI on their current head/base."""

import base64
import fnmatch
import json
import os
from pathlib import PurePosixPath
import re
import tomllib
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = "carlory/herdr-api"
REQUIRED_JOBS = {
    "Validate generated agentic workflow",
    "Check (ubuntu-latest)", "Check (macos-latest)", "Check (windows-latest)",
}
ALLOWED_FILES = (
    "src/**", "tests/**", "examples/**", "Cargo.toml", "Cargo.lock",
    "upstream.toml", "README.md", "EXTRACTION.md", "RELEASING.md", "NOTICE",
    "scripts/install_herdr.py", "scripts/check_release.py",
    "scripts/test_install_herdr.py", "scripts/test_release.py",
)


def api(path, *, method="GET", data=None, token_name=None):
    token = os.environ[token_name or ("GH_TOKEN" if method == "GET" else "MERGE_TOKEN")]
    if not token:
        raise RuntimeError("required automation credential is missing")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"}
    body = None if data is None else json.dumps(data).encode()
    request = Request("https://api.github.com/" + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read()
            result = json.loads(payload) if payload else {}
    except HTTPError as error:
        # Response bodies can contain credential material. Report only status.
        try:
            raise RuntimeError(f"GitHub API HTTP {error.code}; merge was not confirmed") from None
        finally:
            error.close()
    if isinstance(result, dict) and result.get("errors"):
        raise RuntimeError("GitHub GraphQL operation failed; merge was not confirmed")
    return result


def pages(path, key=None):
    items = []
    for page in range(1, 101):
        response = api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        batch = response[key] if key else response
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise RuntimeError("pagination limit reached; refusing incomplete verification")


def adaptation_tag(pr):
    if (pr["state"] != "open" or pr["base"]["ref"] != "main"
            or pr["base"]["repo"]["full_name"] != REPOSITORY
            or not pr["head"].get("repo")
            or pr["head"]["repo"]["full_name"] != REPOSITORY):
        return None
    match = re.fullmatch(r"adapt-herdr-(v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))(?:-[a-f0-9]+)?", pr["head"]["ref"])
    if not match or not pr["title"].startswith("Adapt Herdr: "):
        return None
    body = pr.get("body") or ""
    if "<!-- gh-aw-workflow-id: adapt-herdr -->" not in body:
        return None
    return match[1]


def ci_passed(run, jobs, head, expected_event="pull_request"):
    return (run["path"] == ".github/workflows/ci.yml" and run["event"] == expected_event
            and run["status"] == "completed" and run["conclusion"] == "success"
            and run["head_sha"] == head and REQUIRED_JOBS.issubset({job["name"] for job in jobs})
            and all(job["status"] == "completed" and
                    (job["conclusion"] == "success" or
                     (job["name"] == "Maintenance review (not applicable)" and job["conclusion"] == "skipped"))
                    for job in jobs))


def verify_origin(pr):
    match = re.search(r"<!-- gh-aw-agentic-workflow: Adapt Herdr, [^\n]*?\bid: (\d+),", pr["body"])
    if not match:
        return False
    run = api(f"repos/{REPOSITORY}/actions/runs/{match[1]}")
    return (run["path"] == ".github/workflows/adapt-herdr.lock.yml"
            and run["status"] == "completed" and run["conclusion"] == "success")


def metadata(ref):
    result = api(f"repos/{REPOSITORY}/contents/upstream.toml?{urlencode({'ref': ref})}")
    return tomllib.loads(base64.b64decode(result["content"]).decode())


def verified(pr, run):
    tag = adaptation_tag(pr)
    if not tag or not verify_origin(pr):
        print("Skipped: PR is not a workflow-created Herdr adaptation.")
        return
    head = pr["head"]["sha"]
    jobs = pages(f"repos/{REPOSITORY}/actions/runs/{run['id']}/jobs", "jobs")
    if not ci_passed(run, jobs, head):
        print("Skipped: all required CI jobs must pass on the current PR head.")
        return
    files = pages(f"repos/{REPOSITORY}/pulls/{pr['number']}/files")
    for file in files:
        for path in (file["filename"], file.get("previous_filename", file["filename"])):
            protected = {".github", ".agents", ".codex", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md"}
            if protected.intersection(PurePosixPath(path).parts) or not any(fnmatch.fnmatchcase(path, pattern) for pattern in ALLOWED_FILES):
                raise RuntimeError(f"adaptation contains a protected path: {path}")
    main = api(f"repos/{REPOSITORY}/git/ref/heads/main")["object"]["sha"]
    tested = next((item for item in run["pull_requests"] if item["number"] == pr["number"]), None)
    if not tested or tested["head"]["sha"] != head:
        print("Skipped: CI has no matching PR provenance.")
        return
    if tested["base"]["sha"] != main:
        api(f"repos/{REPOSITORY}/pulls/{pr['number']}/update-branch", method="PUT", data={"expected_head_sha": head})
        print("Updated PR with current main; waiting for fresh CI.")
        return
    target, baseline = metadata(head), metadata(main)
    def numeric(value):
        return tuple(int(part) for part in value.removeprefix("v").split("."))
    if target["tag"] != tag or target["version"] != tag[1:] or numeric(tag) <= numeric(baseline["tag"]):
        raise RuntimeError("adaptation must advance the pinned stable Herdr version")
    return tag, head, main


def review_decision(pr, head, base, expected_run=None):
    reviews = pages(f"repos/{REPOSITORY}/pulls/{pr['number']}/reviews")
    matching = []
    for review in reviews:
        if review["user"]["login"] != "github-actions[bot]" or review["commit_id"] != head:
            continue
        match = re.search(r"HERDR_REVIEW: (APPROVED|BLOCKED) head=([a-f0-9]{40}) base=([a-f0-9]{40}) run=(\d+)\b", review.get("body") or "")
        if match and match[2] == head and match[3] == base and (expected_run is None or int(match[4]) == expected_run):
            matching.append((review["id"], match[1], int(match[4])))
    if not matching:
        return False
    _, decision, run_id = max(matching)
    if decision != "APPROVED":
        return False
    if expected_run is not None:
        return True  # Called only by the trusted verdict job after safe outputs.
    run = api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    return (run["path"] == ".github/workflows/review-herdr.lock.yml"
            and run["status"] == "completed" and run["conclusion"] == "success")


def merge(pr, run):
    if pr["draft"]:
        print("Skipped: adaptation is not ready for review.")
        return
    result = verified(pr, run)
    if not result:
        return
    tag, head, main = result
    if not review_decision(pr, head, main):
        print("Skipped: waiting for an approved independent review of this head and base.")
        return
    # Recheck after API reads; the merge endpoint also atomically checks the head.
    current = api(f"repos/{REPOSITORY}/pulls/{pr['number']}")
    if current["state"] != "open" or current["head"]["sha"] != head or current["base"]["sha"] != main:
        print("Skipped: PR or main changed during verification.")
        return
    if current["draft"]:
        print("Skipped: PR was returned to draft.")
        return
    result = api(f"repos/{REPOSITORY}/pulls/{pr['number']}/merge", method="PUT", data={
        "sha": head, "merge_method": "squash", "commit_title": f"Adapt Herdr {tag} (#{pr['number']})",
        "commit_message": "Protocol adaptation verified by CI and independent review.",
    })
    if not result.get("merged"):
        raise RuntimeError("GitHub declined the merge")
    print(f"Merged verified adaptation PR #{pr['number']}: {result['sha']}")


def candidates():
    if number := os.environ.get("REQUESTED_PR"):
        pr = api(f"repos/{REPOSITORY}/pulls/{int(number)}")
        if not adaptation_tag(pr):
            print("Skipped: ineligible PR.")
            return []
        query = urlencode({"branch": pr["head"]["ref"], "event": "pull_request"})
        runs = pages(f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs?{query}", "workflow_runs")
        matching = [run for run in runs if run["head_sha"] == pr["head"]["sha"]]
        if not matching:
            print("Skipped: current PR head has no CI run.")
            return []
        return [(pr, max(matching, key=lambda run: run["id"]))]
    else:
        run = api(f"repos/{REPOSITORY}/actions/runs/{int(os.environ['CI_RUN_ID'])}")
        return [(api(f"repos/{REPOSITORY}/pulls/{item['number']}"), run) for item in run["pull_requests"]]


def main():
    if os.environ.get("REVIEW_RUN_ID"):
        for pr in pages(f"repos/{REPOSITORY}/pulls?state=open&base=main"):
            if adaptation_tag(pr):
                os.environ["REQUESTED_PR"] = str(pr["number"])
                for candidate, run in candidates():
                    merge(candidate, run)
    else:
        for pr, run in candidates():
            merge(pr, run)


if __name__ == "__main__":
    main()
