# Automated upstream adaptation

`Adapt Herdr` uses GitHub Agentic Workflows to detect new stable Herdr releases
and adapt the protocol crate in a draft PR. Completed adaptations pass CI,
become Ready for review, receive independent AI review, and merge automatically.
The merged main commit passes CI before its version tag is created, starting
crates.io publication followed by a GitHub Release. This unattended pipeline is
explicitly authorized; individual releases require no manual confirmation.

## Detection and delivery

The schedule checks the official `herdrdev/herdr` releases approximately every
six hours. It ignores drafts, preview tags, and prereleases, compares numeric
versions, and selects the oldest stable version newer than `upstream.toml`.
An open `adapt-herdr-*` PR targeting `main` pauses further adaptation. This
process handles successive stable releases without silently skipping versions.
Releases are paginated, so a page full of previews cannot hide a stable release.

The agent stages the official source at the tag's full commit SHA, obtains all
supported binary asset digests from the release API, installs the local platform
binary with digest verification, and exports Schema. It never builds Herdr.
It then updates wire types, metadata, tests, and documentation and runs Linux
Schema parity and real event integration tests before opening a draft PR.
The author includes `HERDR_ADAPTATION_STATUS: READY` only after local checks
pass and no blocker remains. A trusted handoff job verifies cross-platform CI
and marks the draft **Ready for review**. Incomplete adaptations stay draft;
the reviewer never starts on drafts.
The PR runs the normal Linux, macOS, and Windows CI. An independent
`Review Herdr adaptation` Copilot agent then reviews the pinned diff, upstream
protocol types, provenance, compatibility, and test quality. It submits a
consolidated GitHub review using the Actions bot identity; its structured
APPROVED/BLOCKED decision becomes the **Review Herdr adaptation** check.
Native GitHub approval permissions are not required. The independent
`Merge verified Herdr adaptation` workflow squash
merges it only after both CI and this review check pass on its current head/base.
A blocked review or CI failure returns current findings to `Repair Herdr
adaptation`, another author-agent turn on the same PR. Fixes trigger fresh CI
and review on the new head. The reviewer cannot edit code. After five repair
rounds the PR stays open with findings instead of entering an unbounded loop.
Incomplete review runs and release failures receive up to three retries.

The merge workflow runs only trusted code from `main`; it never checks out or
executes the PR's code with a write token. It verifies the originating successful
`Adapt Herdr` run, same-repository `adapt-herdr-v*` branch, `main` target, allowed
file paths, a newer stable pinned version, all four named CI jobs, and a successful
review workflow whose bot-authored decision matches the exact head and base. Failed,
skipped, missing, or stale checks do not authorize a merge. A changed main branch
is merged into the PR first, triggering fresh CI. The final merge request locks
the expected PR head SHA. Required, up-to-date branch checks protect `main`,
including merges by administrators, from a base change racing this verification.
Ordinary PRs and forks are not automatically merged. The AI agents cannot merge,
tag, or publish. Trusted deterministic jobs own those transitions. A tag requires
a merged adaptation with a successful exact-head review, passing current-main CI,
and configured publication authentication. Existing tags are never moved. The
release workflow verifies all platforms, compares the packaged candidate, publishes
crates.io, confirms its checksum, and only then completes the GitHub Release.

The manifest preserves the existing extraction boundary. Changes to workflows,
agent instructions, release gates, and the detector/staging scripts are excluded
from agent-created PRs. Missing assets, source relocations, or incompatible
protocol changes are investigated rather than bypassing checks. Upstream files
and release notes are treated as data, not agent instructions.

## Required setup

This is a personal repository. Create **one** dedicated fine-grained PAT with
the permissions below and store the same value in these two Actions secrets:

- `COPILOT_GITHUB_TOKEN`: a fine-grained PAT for your personal account with
  Copilot access and Account permissions > Copilot Requests > Read.
- `GH_AW_CI_TRIGGER_TOKEN`: a fine-grained PAT restricted to `carlory/herdr-api`
  with Contents read/write and Pull requests read/write. gh-aw uses this secret in
  the downstream PR safe output to push the adaptation branch and create its PR.
  This starts ordinary pull-request CI directly, without an extra empty commit.

The GitHub tools use a read-only Actions token, and the declared write output
is `create-pull-request`. The shared PAT authenticates both Copilot inference
and PR creation, so it has repository write permissions even when used for
inference. Using one PAT trades credential separation for a single token to
manage. Its repository access must be restricted to `herdr-api`.
No registry token is available to any AI workflow.

Without these credentials, detection still works and records the new target in
the run summary and `upstream-detection` artifact. Activation and inference are
skipped, with a warning that adaptation needs credentials. A missing credential
does not cause a release to be considered adapted. Actual inference and PR
creation require valid credentials. The PR uses the dedicated PAT's identity,
so the repository's default GITHUB_TOKEN remains read-only and its Actions PR
approval setting does not need to be enabled. The independent merge workflow
also uses this existing dedicated PAT for marking ready, branch updates, and
merging; no additional token or permissions are needed. The AI agent has no
merge safe output. The reviewer reuses `COPILOT_GITHUB_TOKEN` for inference;
its read-only agent cannot push changes or merge. Only trusted deterministic
jobs publish the review check and apply the merge.

Open [Create the adaptation token](https://github.com/settings/personal-access-tokens/new?name=herdr-api-adaptation&target_name=carlory&expires_in=none&user_copilot_requests=read&contents=write&pull_requests=write)
in your signed-in GitHub account. Verify these settings:

- Resource owner: `carlory`, with an active Copilot subscription.
- Expiration: **No expiration**.
- Repository access: **Only select repositories > herdr-api**.
- Account permissions: **Copilot Requests > Read**.
- Repository permissions: **Contents > Read and write**, **Pull requests > Read and write**.

The URL prefills permissions; verify all settings before generating the token.
The token has no expiration date. Existing broad CLI credentials are not
copied to the repository.
Tokens must never be pasted into a PR, issue, or chat message.

The account permission uses the URL parameter `user_copilot_requests=read`, as
in gh-aw's official Copilot authentication link. Verify **Account permissions >
Copilot Requests > Read** in the form. If the run reports that the PAT does not
have Copilot Requests permission, edit the existing token at
[Fine-grained personal access tokens](https://github.com/settings/personal-access-tokens),
add that account permission, save, and rerun the workflow. Permission changes
do not require creating another token or replacing the two secret values.

After generating it, run this command in a local terminal:

```sh
python3 scripts/configure_adaptation.py
```

The helper prompts once with hidden input, submits the same token to both fixed
repository secrets through `gh` standard input, verifies secret names, and dispatches the
adaptation workflow. It does not print tokens, put them in command arguments,
write them to local files, or change repository permissions. If configuration
partially fails, rerun the helper; it updates the same two secret names.

## One-time publication setup

Sign in to crates.io with GitHub and verify your email. Create a publishing token
at [API Tokens](https://crates.io/settings/tokens) with **Publish new crates** and
**Publish updates**. The crate filter may be `herdr-api` or **All crates**;
choose **No expiration** for the requested unattended setup. Configure a
`crates-io` environment without manual reviewers, then run locally:

```sh
python3 scripts/configure_publication.py
```

The hidden-input helper stores `CARGO_REGISTRY_TOKEN` in that fixed environment,
without local persistence, command arguments, or printed credential material.
The tag job receives only a boolean indicating whether the secret exists. Only
the release publish step receives the registry token. Missing credentials block
tag creation rather than presenting an unpublished tag as a finished release.

To resume tagging after authentication or infrastructure recovery:

```sh
gh workflow run tag-adaptation.yml --repo carlory/herdr-api --ref main
```

## Manual testing and maintenance

Run detection and adaptation from the default branch:

```sh
gh workflow run adapt-herdr.lock.yml --repo carlory/herdr-api --ref main
```

Optionally add `-f tag=v0.9.3` to select a specific newer stable release. The
target must exist upstream and be newer than the mirrored version. Selecting
the current version is rejected instead of creating a meaningless PR.

For an end-to-end upgrade test, keep the current implementation in a Git branch,
set `main` to a verified older mirror (for example v0.9.2), and run the workflow.
The detector should select v0.9.3. The full pipeline then adapts, reviews, merges,
tags, and publishes v0.9.3. Testing this authorized production path causes actual
publication; manual `Release` dispatch remains available for a dry run.

To review an existing adaptation PR after its CI passes:

```sh
gh workflow run review-herdr.lock.yml --repo carlory/herdr-api --ref main -f pull_request=3
```

The reviewer runs again on every successfully verified new PR head. Its approval
is invalid after head or base changes. A blocked or incomplete review leaves
the PR open, with findings and a failing check. Fix the findings and push a new
commit to obtain fresh CI and review. The independent author repair workflow
handles current blocking findings automatically; the reviewer never edits code.

To check an existing adaptation PR against its latest CI run:

```sh
gh workflow run merge-adaptation.yml --repo carlory/herdr-api --ref main -f pull_request=3
```

`main` requires **Validate generated agentic workflow**, **Check (ubuntu-latest)**,
**Check (macos-latest)**, **Check (windows-latest)** and **Review Herdr adaptation**, with up-to-date branches
and enforcement for administrators. Future maintenance changes to `main` must
also go through a PR with these checks; direct pushes are blocked. Same-repository
`maintain-herdr-*` PRs authored by `carlory` receive an independent Copilot review
under the same required Review check. This reviewer inspects the pinned diff and
trusted base context without tools or executing candidate code. Missing, blocked,
or incomplete review decisions fail the check. Other PRs do not receive a passing
Review check automatically. The adaptation
merge job additionally enforces the bot-authored review decision and successful
review workflow for the current head/base in addition to branch protection.

Authoritative inputs can also be staged locally:

```sh
python3 scripts/upstream.py detect
python3 scripts/upstream.py stage --tag v0.9.3
python3 scripts/upstream.py write-metadata .upstream/v0.9.3
```

Staging only writes ignored `.upstream/` files. `write-metadata` changes the
tracked provenance file and should be run only while implementing an adaptation.
It hashes every known source and all protocol schema modules. Add helper files
with `--extra-source`; omit a relocated source with `--omit-source` only after
it no longer exists in the new upstream tree. Existing sources cannot be omitted.

The authored workflow is `.github/workflows/adapt-herdr.md`; its `.lock.yml` and
`.github/aw/actions-lock.json` are generated. Never edit generated files manually.
Use the compiler version fixed in `.github/aw-version`:

```sh
gh extension install github/gh-aw --pin v0.89.21
gh aw compile adapt-herdr review-herdr repair-herdr --no-check-update
```

CI recompiles and rejects a stale generated workflow. Changing the engine also
requires updating the credential prerequisite check and recompiling. Review new
actions/secrets before accepting a compiler security-review prompt.

Initial compiler review: `dtolnay/rust-toolchain` installs the stable Rust
toolchain and is already used in CI; gh-aw pins it to a reviewed commit. The new
credential references are `COPILOT_GITHUB_TOKEN` for inference and
`GH_AW_CI_TRIGGER_TOKEN` for downstream PR creation and CI triggering. No deployment or registry
credential is available to AI agents. The registry credential is isolated in
`crates-io`. Compiler-supplied optional gh-aw telemetry/GitHub override
secrets remain unset. There are no workflow redirects.

References: [GitHub Agentic Workflows](https://docs.github.com/en/copilot/concepts/agents/about-github-agentic-workflows),
[Copilot authentication](https://github.github.com/gh-aw/reference/auth/),
and [triggering PR CI](https://github.github.com/gh-aw/reference/triggering-ci/).
