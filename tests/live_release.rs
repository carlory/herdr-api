//! Exercises the installed official release, not a mock server.
#![cfg(unix)]

use herdr_api::*;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

struct Server {
    child: Child,
    socket: PathBuf,
    _directory: tempfile::TempDir,
}

impl Drop for Server {
    fn drop(&mut self) {
        // Stop only the isolated test server, even if an assertion panics.
        if let Ok(mut stream) = UnixStream::connect(&self.socket) {
            let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
            let _ = stream
                .write_all(b"{\"id\":\"cleanup\",\"method\":\"server.stop\",\"params\":{}}\n");
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Server {
    fn start() -> Self {
        let binary = std::env::var_os("HERDR_BIN_PATH").expect("HERDR_BIN_PATH must be set");
        let directory = tempfile::Builder::new()
            .prefix("hapi-")
            .tempdir_in("/tmp")
            .unwrap();
        let root = directory.path();
        let config = root.join("config.toml");
        std::fs::write(&config, "onboarding = false\n[update]\nversion_check = false\nmanifest_check = false\n[ui.sound]\nenabled = false\n").unwrap();
        let socket = root.join("api.sock");
        let logs = Path::new(env!("CARGO_MANIFEST_DIR")).join("artifacts");
        std::fs::create_dir_all(&logs).unwrap();
        let log = std::fs::File::create(logs.join("live-server.log")).unwrap();
        let child = Command::new(binary)
            .arg("server")
            .current_dir(root)
            .env("XDG_CONFIG_HOME", root.join("config"))
            .env("XDG_RUNTIME_DIR", root)
            .env("HERDR_CONFIG_PATH", &config)
            .env("HERDR_SOCKET_PATH", &socket)
            .env("SHELL", "/bin/sh")
            .env_remove("HERDR_ENV")
            .env_remove("HERDR_SESSION")
            .env_remove("HERDR_CLIENT_SOCKET_PATH")
            .env_remove("HERDR_WORKSPACE_ID")
            .env_remove("HERDR_TAB_ID")
            .env_remove("HERDR_PANE_ID")
            .stdin(Stdio::null())
            .stdout(log.try_clone().unwrap())
            .stderr(log)
            .spawn()
            .unwrap();
        let mut server = Self {
            child,
            socket,
            _directory: directory,
        };
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            if UnixStream::connect(&server.socket).is_ok() {
                return server;
            }
            assert!(
                server.child.try_wait().unwrap().is_none(),
                "server exited; see artifacts/live-server.log"
            );
            assert!(
                Instant::now() < deadline,
                "server startup timed out; see artifacts/live-server.log"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn connect(&self) -> UnixStream {
        let stream = UnixStream::connect(&self.socket).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(15)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(15)))
            .unwrap();
        stream
    }

    fn call(&self, method: Method) -> SuccessResponse {
        let mut stream = self.connect();
        write_request(&mut stream, method);
        let mut reader = BufReader::new(stream);
        let json = read_line(&mut reader);
        let response: SuccessResponse = serde_json::from_str(&json)
            .unwrap_or_else(|error| panic!("response failed to decode: {error}: {json}"));
        assert_eq!(response.id, "live-test");
        response
    }
}

fn write_request(stream: &mut UnixStream, method: Method) {
    serde_json::to_writer(
        &mut *stream,
        &Request {
            id: "live-test".into(),
            method,
        },
    )
    .unwrap();
    stream.write_all(b"\n").unwrap();
}

fn read_line(reader: &mut BufReader<UnixStream>) -> String {
    let mut line = String::new();
    assert!(
        reader.read_line(&mut line).unwrap() > 0,
        "server closed connection"
    );
    line
}

fn git(directory: &Path, args: &[&str]) {
    let output = Command::new("git")
        .current_dir(directory)
        .args(args)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "git failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
#[ignore = "requires installed official Herdr; run scripts/check_release.py"]
fn official_release_responses_socket_events_and_hook_events_decode() {
    let server = Server::start();
    match server.call(Method::Ping(PingParams {})).result {
        ResponseResult::Pong {
            version, protocol, ..
        } => {
            assert_eq!(version, HERDR_VERSION);
            assert_eq!(protocol, PROTOCOL_VERSION);
        }
        result => panic!("unexpected ping: {result:?}"),
    }
    assert!(matches!(
        server.call(Method::SessionSnapshot(EmptyParams {})).result,
        ResponseResult::SessionSnapshot { .. }
    ));

    // Invalid public resource IDs yield a real, typed error response.
    let mut stream = server.connect();
    write_request(
        &mut stream,
        Method::WorkspaceGet(WorkspaceTarget {
            workspace_id: "missing-workspace".into(),
        }),
    );
    let error: ErrorResponse =
        serde_json::from_str(&read_line(&mut BufReader::new(stream))).unwrap();
    assert_eq!(error.id, "live-test");
    assert!(!error.error.code.is_empty());

    let root = server._directory.path();
    let plugin = root.join("plugin");
    std::fs::create_dir(&plugin).unwrap();
    let capture = root.join("hook-event.json");
    let script = plugin.join("capture.sh");
    std::fs::write(
        &script,
        "printf '%s\\n' \"$HERDR_PLUGIN_EVENT_JSON\" > \"$1\"\n",
    )
    .unwrap();
    std::fs::write(plugin.join("herdr-plugin.toml"), format!(
        "id = \"test.herdr-api\"\nname = \"Protocol test\"\nversion = \"0.1.0\"\nmin_herdr_version = \"0.9.3\"\nplatforms = [\"linux\", \"macos\"]\n[[events]]\non = \"worktree.created\"\ncommand = [\"sh\", {}, {}]\n",
        serde_json::to_string(&script.to_string_lossy()).unwrap(),
        serde_json::to_string(&capture.to_string_lossy()).unwrap(),
    )).unwrap();
    assert!(matches!(
        server
            .call(Method::PluginLink(PluginLinkParams {
                path: plugin.to_string_lossy().into(),
                enabled: true,
                source: None
            }))
            .result,
        ResponseResult::PluginLinked { .. }
    ));

    let repository = root.join("repo");
    std::fs::create_dir(&repository).unwrap();
    git(&repository, &["init", "--initial-branch=main"]);
    git(
        &repository,
        &[
            "-c",
            "user.name=Protocol Test",
            "-c",
            "user.email=protocol@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "Initialize protocol fixture",
        ],
    );

    let mut subscription = server.connect();
    write_request(
        &mut subscription,
        Method::EventsSubscribe(EventsSubscribeParams {
            subscriptions: vec![Subscription::WorktreeCreated {}],
        }),
    );
    let mut subscription = BufReader::new(subscription);
    let ack: SuccessResponse = serde_json::from_str(&read_line(&mut subscription)).unwrap();
    assert!(matches!(ack.result, ResponseResult::SubscriptionStarted {}));

    let target = root.join("checkout");
    let response = server.call(Method::WorktreeCreate(WorktreeCreateParams {
        cwd: Some(repository.to_string_lossy().into()),
        branch: Some("protocol-fixture".into()),
        path: Some(target.to_string_lossy().into()),
        trust_repository: true,
        ..Default::default()
    }));
    assert!(matches!(
        response.result,
        ResponseResult::WorktreeCreated { .. }
    ));
    let socket_json = read_line(&mut subscription);
    let socket_event: EventEnvelope = serde_json::from_str(&socket_json).unwrap();
    assert_eq!(socket_event.event, EventKind::WorktreeCreated);
    match &socket_event.data {
        EventData::WorktreeCreated { worktree, .. } => {
            assert_eq!(Path::new(&worktree.path), target)
        }
        data => panic!("unexpected event: {data:?}"),
    }
    let deadline = Instant::now() + Duration::from_secs(10);
    let hook_event = loop {
        if let Ok(json) = std::fs::read_to_string(&capture) {
            if let Ok(event) = serde_json::from_str::<EventEnvelope>(&json) {
                break event;
            }
        }
        assert!(
            Instant::now() < deadline,
            "event hook did not produce valid JSON"
        );
        std::thread::sleep(Duration::from_millis(20));
    };
    assert_eq!(hook_event, socket_event);
}
