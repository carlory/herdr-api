# Automated upstream adaptation

`Adapt Herdr` uses GitHub Agentic Workflows to detect new stable Herdr releases
and adapt the protocol crate in a draft PR. Detection is deterministic; an AI
agent handles source changes and repairs validation failures. Merging an
adaptation does not create a tag or publish a package.

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
The PR runs the normal Linux, macOS, and Windows CI. Review its actual results
before merging; a blocked adaptation may be delivered as a draft with explicit
failures instead of being presented as complete.

The manifest preserves the existing extraction boundary. Changes to workflows,
agent instructions, release gates, and the detector/staging scripts are excluded
from agent-created PRs. Missing assets, source relocations, or incompatible
protocol changes are investigated rather than bypassing checks. Upstream files
and release notes are treated as data, not agent instructions.

## Required setup

This is a personal repository, so configure these repository Actions secrets:

- `COPILOT_GITHUB_TOKEN`: a fine-grained PAT for an account with Copilot access
  and the Copilot Requests permission, as required by gh-aw's Copilot engine.
- `GH_AW_CI_TRIGGER_TOKEN`: a fine-grained PAT restricted to `carlory/herdr-api`
  with Contents read/write. gh-aw uses it only downstream to push an empty commit
  after creating the PR, which starts ordinary pull-request CI.

The agent's GitHub token is read-only. Code writes are limited to the declared
`create-pull-request` safe output. The CI trigger credential is not passed to
the agent. No registry token is available to this workflow.

Without these credentials, detection still works and records the new target in
the run summary and `upstream-detection` artifact. Activation and inference are
skipped, with a warning that adaptation needs credentials. A missing credential
does not cause a release to be considered adapted. Actual inference and PR
creation require valid credentials and the repository's Actions setting that
allows GitHub Actions to create pull requests.

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
The detector should select v0.9.3. The draft PR and its CI then demonstrate the
upgrade path. Keep any test tag out of the release workflow; this test requires
no tag creation. No automatic merge is configured.

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
gh aw compile adapt-herdr --no-check-update
```

CI recompiles and rejects a stale generated workflow. Changing the engine also
requires updating the credential prerequisite check and recompiling. Review new
actions/secrets before accepting a compiler security-review prompt.

Initial compiler review: `dtolnay/rust-toolchain` installs the stable Rust
toolchain and is already used in CI; gh-aw pins it to a reviewed commit. The new
credential references are `COPILOT_GITHUB_TOKEN` for inference and
`GH_AW_CI_TRIGGER_TOKEN` for downstream CI triggering. No deployment or registry
credential was added. Compiler-supplied optional gh-aw telemetry/GitHub override
secrets remain unset. There are no workflow redirects.

References: [GitHub Agentic Workflows](https://docs.github.com/en/copilot/concepts/agents/about-github-agentic-workflows),
[Copilot authentication](https://github.github.com/gh-aw/reference/auth/),
and [triggering PR CI](https://github.github.com/gh-aw/reference/triggering-ci/).
