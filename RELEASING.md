# GitHub releases

The release tag and Cargo version mirror the pinned stable Herdr release:
`v0.9.3` identifies crate version `0.9.3` for Herdr `v0.9.3`. This repository
uses Git tags and GitHub Releases; `publish = false` disables registry publication.

## Automatic releases

After an adaptation PR passes current-head CI, trusted automation merges it.
Once CI passes on its exact main merge commit, the tag workflow creates an
annotated version tag with the existing repository-scoped GitHub PAT. Tags are
immutable and individual releases need no manual approval.

A tag push starts `Release`:

1. Validate the tag, Cargo metadata, constants, clean checkout and main ancestry.
2. Run all CI checks on Linux, macOS and Windows, installing official Herdr
   binaries and checking Schema parity. Herdr is never compiled from source.
3. Build and verify the Cargo package, then prepare release assets and SHA-256 sums.
4. Confirm the remote tag still identifies the verified candidate commit.
5. Create a GitHub draft, upload and verify every asset, then publish the release.

Assets include the `.crate` package, official and extracted Schema documents,
`upstream.toml`, release identity, notes and `SHA256SUMS`. `scripts/release.py`
generates them; never edit them manually. The GitHub Release job uses the built-in
Actions token with `contents: write`. No registry account or token is needed.

Consumers use the matching Git tag:

```toml
[dependencies]
herdr-api = { git = "https://github.com/carlory/herdr-api", tag = "v0.9.3" }
```

## Rehearsal

Manual dispatches validate a candidate and retain artifacts without creating a
tag or GitHub Release:

```sh
gh workflow run release.yml --repo carlory/herdr-api --ref main -f tag=v0.9.3
```

The `release-candidate` artifact is retained for 14 days. Only a tag push in
`carlory/herdr-api` can reach the publishing job. Branch pushes and PRs cannot
publish. Runs for the same Git ref are serialized without cancelling publication.

## Recovery

Rerun a failed tag workflow without moving or deleting its tag. For interrupted
uploads, rerun the GitHub Release job with the original candidate artifact. A
matching draft is resumed and assets with matching GitHub SHA-256 digests are
skipped. A different existing asset fails; published releases are never mutated.

If a full rerun with a newer toolchain produces different package bytes, recover
the original candidate instead of overwriting assets. If artifacts have expired,
investigate and recover the original package before proceeding.

Reference: [GitHub Releases REST API](https://docs.github.com/en/rest/releases/releases).
