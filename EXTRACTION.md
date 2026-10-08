# Extraction from Herdr v0.9.2

Source commit: `48292af8e33a08c8030b7f1512c8d0da739f5ab1`.

The source `src/api/schema.rs` becomes `src/lib.rs`. Its protocol submodules are
copied to `src/` with their original names. Rustfmt may change formatting.
Upstream tests are adapted into `tests/upstream_serde.rs`. File fingerprints in
`upstream.toml` refer to the original files, before these modifications.

## Changes

| Upstream location | Extraction change | Wire effect |
| --- | --- | --- |
| `src/api/schema.rs` | Remove upstream test module; add public support module and version constants | None |
| `schema/agents.rs` | Remove skipped `submission_deadline`; redirect session kind to support module | None |
| `schema/panes.rs` | Remove skipped `intent` | None |
| `schema/common.rs` | Remove private `ReadIntent`; redirect toast position to support module | None |
| `schema/response.rs` | Redirect configuration reload status to support module | None |
| `schema/plugins.rs` | Redirect popup size; remove managed-path hashing, slug functions and their tests | None |
| `schema/integrations.rs` | Remove unused internal `IntegrationTarget::ALL` | None |
| Source comments | Replace em dash punctuation with plain dash; preserve the official `warnings` Schema description using a Unicode escape in an explicit attribute | None |
| `schema/tests.rs` | Remove artifact update test; adapt imports, version constant and removed runtime field | None |

The standalone `src/support.rs` extracts exactly the protocol dependencies:

- `ToastHerdrPosition` and `ConfigReloadStatus` from `src/config/model.rs`.
- `AgentSessionRefKind` from `src/agent_resume.rs`.
- `PopupSize` from `src/popup_size.rs`, including its custom serialization,
  deserialization and Schema implementation. Remove geometry resolution and
  terminal rendering dependencies; make the enum public.

No private terminal attach messages, socket transports, runtime configuration,
filesystem management, hashing dependencies, or skipped runtime state are included.
Small pure helpers used by protocol types (defaults and event dot names) remain.

## Schema generator

`tests/support/schema.rs` mirrors upstream's
`src/api/schema/tests.rs::protocol_schema_document`, including its five roots and
reference rewriting. It is verification tooling, not a runtime client API.

## Updating the extraction

1. Review an explicit upstream release tag and record its full commit.
2. Extract all protocol types and their data dependencies, preserving Serde and
   Schema behavior. Review every adaptation and update this document.
3. Obtain the release asset SHA-256 digests and update `upstream.toml`.
4. Align the version constants and Cargo version with the reviewed release.
5. Install the official binary and run all checks, including release parity and
   live integration tests. Never mask differences by removing constraints.
6. Review compatibility before merging. Tags and publication are separate actions.
