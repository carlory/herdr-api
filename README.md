# herdr-api

Unofficial Rust protocol types for **Herdr 0.9.3**, maintained independently by
carlory. This crate mirrors the JSON protocol shipped in that release: protocol
22, schema document version 1.

The crate includes requests, success and error responses, lifecycle events,
subscription events, and their referenced data types. It includes no socket
client, CLI wrapper, terminal protocol, or Herdr runtime.

## Usage before a release

No tag, GitHub Release, or crates.io package has been published. Pin a reviewed
Git commit when consuming this repository:

```toml
[dependencies]
herdr-api = { git = "https://github.com/carlory/herdr-api", rev = "<full commit SHA>" }
serde_json = "1"
```

Construct a JSON request:

```rust
use herdr_api::{Method, PingParams, Request};

let request = Request {
    id: "ping-1".into(),
    method: Method::Ping(PingParams {}),
};
let json = serde_json::to_string(&request)?;
# Ok::<(), serde_json::Error>(())
```

Parse an event supplied to a plugin hook:

```rust,no_run
use herdr_api::{EventData, EventEnvelope, EventKind};

let json = std::env::var("HERDR_PLUGIN_EVENT_JSON")?;
let event: EventEnvelope = serde_json::from_str(&json)?;
if let (EventKind::WorktreeCreated, EventData::WorktreeCreated { worktree, .. }) =
    (event.event, event.data)
{
    println!("{}", worktree.path);
}
# Ok::<(), Box<dyn std::error::Error>>(())
```

Herdr uses dot names such as `worktree.created` for manifest hooks, but snake
case names such as `worktree_created` in lifecycle event envelopes. The example
checks both envelope and payload variants; the types preserve upstream behavior
and do not add validation that these two fields agree.

Socket responses and hook events can use these types directly. Only CLI output
that has the same JSON shape as a protocol type can be decoded as that type.

## Verification

Routine checks:

```sh
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all-targets
cargo test --locked --doc
```

Verify against the official release:

```sh
python3 scripts/install_herdr.py .tools
python3 scripts/check_release.py .tools/herdr
```

On Windows, use `python` and `.tools/herdr.exe`. Python 3.11 or newer is required.
The installer downloads the fixed official release asset, checks its pinned
SHA-256 digest, and verifies its reported version. **It does not compile Herdr.**

Every CI matrix job installs the official release afresh, exports its bundled
Schema with `herdr api schema`, and compares that document with a Schema generated
from this crate. Object key order and JSON formatting are ignored; array order,
references, required fields, defaults, descriptions, and constraints are preserved.
There is no fallback to a checked-in Schema. Exported documents and path-specific
differences are retained as CI artifacts.

On Linux and macOS, CI also starts an isolated official Herdr server and checks
real ping, snapshot, error, worktree creation, socket event, and plugin hook event
payloads. The server, sockets, Git checkout, and plugin registry use a temporary
directory and are cleaned up on success or failure. The Windows job checks Schema
parity and serialization but does not run the Unix socket integration harness.

Serialization tests are adapted from the pinned upstream protocol tests. They
cover defaults, field omission, discriminated unions, events, layouts, metadata,
plugins, and popup sizes. Schema parity alone cannot prove all Serde behavior or
server-side validation rules.

## Provenance and compatibility

See [upstream.toml](upstream.toml) for the upstream commit, source file fingerprints,
release asset digests, and compatibility versions. See [EXTRACTION.md](EXTRACTION.md)
for the extraction boundary and modifications. `schemars` is pinned to upstream's
version so generator changes cannot silently alter the comparison.

The crate preserves upstream names and JSON behavior. It does not promise
compatibility with other Herdr releases, accept unknown enum variants, or enforce
every runtime rule documented by Herdr. Schema-only constraints can be stricter
than a Rust `HashMap` or numeric field; the server remains authoritative.

The Cargo version identifies the mirrored Herdr release. No automatic update,
tagging, or publishing workflow is configured. Future local correction versions
will need an explicit versioning policy before publication.

## License

Apache-2.0. Protocol definitions and adapted tests originate from
[herdrdev/herdr](https://github.com/herdrdev/herdr/tree/v0.9.3).
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
