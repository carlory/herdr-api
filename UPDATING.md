# Automated upstream adaptation

One GitHub Agentic Workflow, `Adapt Herdr`, detects stable Herdr releases every
six hours and prepares an adaptation PR. When its CI passes, deterministic
workflows merge the PR, tag the verified merge commit, publish to crates.io,
and complete the GitHub Release. There are no separate review or repair agents.

## Detection and adaptation

The detector paginates official `herdrdev/herdr` releases, ignores previews and
drafts, and selects the oldest stable version newer than `upstream.toml`.
An existing open `adapt-herdr-*` PR pauses further updates, avoiding duplicate
PRs and silently skipped versions.

The agent downloads upstream source at the tag's full commit SHA and verified
official binary assets. It adapts the protocol types, Serde behavior, provenance,
version and tests, then runs the local checks before creating one non-draft PR.
Herdr is installed from release assets, never compiled. Upstream content is data,
not instructions. The agent cannot change workflows, release gates or permissions.
If it cannot complete local verification, it records the blocker in the run and
the next scheduled run may retry. Failed PR CI leaves the PR open for correction;
there is no independent repair loop.

## Merge and publication

The merge workflow runs trusted code from `main`, without executing PR code with
its write token. It requires the originating successful adaptation workflow,
a same-repository `adapt-herdr-v*` branch targeting `main`, permitted changed files,
a newer stable pinned version, and all CI jobs passing on the current PR head.
If main changed since CI, it updates the PR branch and waits for fresh CI.
The merge request pins the expected head SHA.

`main` requires up-to-date **Validate generated agentic workflow**,
**Check (ubuntu-latest)**, **Check (macos-latest)** and **Check (windows-latest)**,
including for administrators. CI installs official Herdr and checks Schema parity;
Linux and macOS also test real server, socket and plugin hook events. Ordinary
PRs and forks are not automatically merged. Drafts are not automatically merged.

After CI passes on main, the tag workflow requires main to be the adaptation's
exact merge commit and the version to match the pinned Herdr release. It creates
an annotated immutable tag with the existing repository-scoped PAT. A separate
credential-presence job emits only a boolean, with no checkout or write token.
The tag job has no registry credential. Existing tags are never moved.

The tag push starts `Release`, which verifies the three platforms, packages a
candidate, publishes to crates.io and confirms its checksum before publishing
the GitHub Release. Only the registry upload step receives the registry token.
See [RELEASING.md](RELEASING.md) for validation and recovery. Manual Release
workflow dispatches are dry runs. No individual approval is required for this
configured unattended pipeline.

## Credentials

The repository uses the existing fine-grained GitHub PAT in two Actions secrets:

- `COPILOT_GITHUB_TOKEN`: Account permissions > Copilot Requests > Read.
- `GH_AW_CI_TRIGGER_TOKEN`: Contents and Pull requests read/write, restricted to
  `carlory/herdr-api`. It creates PRs, updates branches, merges and tags so those
  actions trigger downstream CI.

The same PAT supplies both secrets; its inference use also carries repository
write permissions. GitHub tools use a read-only Actions token and writes are
restricted to declared safe outputs. No AI agent receives the registry token.
The token has no expiration, as configured. To rotate credentials, update the
same secret names in GitHub settings; no setup scripts are required.

`CARGO_REGISTRY_TOKEN` is stored in the `crates-io` environment, which has no
manual reviewers. Its crates.io permissions support publishing new crates and
updates; the configured token may cover All crates.

## Operation and maintenance

To detect and adapt the next stable release manually:

```sh
gh workflow run adapt-herdr.lock.yml --repo carlory/herdr-api --ref main
```

Optionally add `-f tag=v0.9.3` to select a specific newer stable release. Current
or older versions are rejected. To resume a verified adaptation or tag operation:

```sh
gh workflow run merge-adaptation.yml --repo carlory/herdr-api --ref main -f pull_request=<number>
gh workflow run tag-adaptation.yml --repo carlory/herdr-api --ref main
```

The authored agent workflow is `.github/workflows/adapt-herdr.md`. Its lockfile
and `.github/aw/actions-lock.json` are generated. Use the pinned compiler in
`.github/aw-version`; never edit generated files manually:

```sh
gh aw compile adapt-herdr --no-check-update
```

CI recompiles and rejects stale output. Maintenance changes go through normal
PRs and the four required CI checks.
