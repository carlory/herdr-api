use herdr_api::*;
use serde_json::json;

#[test]
fn popup_sizes_preserve_numeric_limits_and_percent_rules() {
    for (wire, expected) in [
        (json!(0), PopupSize::Cells(0)),
        (json!(65535), PopupSize::Cells(65535)),
        (json!("1%"), PopupSize::Percent(1)),
        (json!("100%"), PopupSize::Percent(100)),
    ] {
        let parsed: PopupSize = serde_json::from_value(wire.clone()).unwrap();
        assert_eq!(parsed, expected);
        assert_eq!(serde_json::to_value(parsed).unwrap(), wire);
    }
    for invalid in [
        json!(-1),
        json!(65536),
        json!(1.5),
        json!("80"),
        json!("0%"),
        json!("101%"),
        json!(null),
    ] {
        assert!(
            serde_json::from_value::<PopupSize>(invalid.clone()).is_err(),
            "accepted {invalid}"
        );
    }
}

#[test]
fn unknown_fields_are_accepted_but_unknown_variants_are_rejected() {
    let request: Request = serde_json::from_value(json!({
        "id": "future", "method": "ping", "params": {"future": 1}, "extra": true
    }))
    .unwrap();
    assert_eq!(
        request,
        Request {
            id: "future".into(),
            method: Method::Ping(PingParams {})
        }
    );
    assert!(serde_json::from_value::<Request>(json!({
        "id": "future", "method": "future.method", "params": {}
    }))
    .is_err());
    assert!(serde_json::from_value::<EventKind>(json!("future_event")).is_err());
}

#[test]
fn omitted_and_null_optional_fields_have_the_same_meaning() {
    let omitted: WorktreeCreateParams = serde_json::from_value(json!({})).unwrap();
    let nulls: WorktreeCreateParams = serde_json::from_value(json!({
        "workspace_id": null, "cwd": null, "branch": null, "base": null,
        "path": null, "label": null
    }))
    .unwrap();
    assert_eq!(omitted, nulls);
    // focus is defaulted but emitted; trust_repository is omitted when false.
    assert_eq!(
        serde_json::to_value(omitted).unwrap(),
        json!({"focus": false})
    );
}

#[test]
fn integer_protocol_fields_reject_negative_overflow_and_fractions() {
    for invalid in [json!(-1), json!(4294967296u64), json!(1.5)] {
        assert!(serde_json::from_value::<AgentReadParams>(json!({
            "target": "w1:p1", "source": "visible", "lines": invalid
        }))
        .is_err());
    }
}

#[test]
fn external_consumers_can_construct_previously_runtime_coupled_types() {
    let request = Request {
        id: "read".into(),
        method: Method::PaneRead(PaneReadParams {
            pane_id: "w1:p1".into(),
            source: ReadSource::Visible,
            lines: None,
            format: ReadFormat::Text,
            strip_ansi: true,
        }),
    };
    let value = serde_json::to_value(request).unwrap();
    assert_eq!(
        value,
        json!({"id":"read", "method":"pane.read", "params": {
            "pane_id":"w1:p1", "source":"visible", "format":"text", "strip_ansi":true
        }})
    );
    let wait = AgentPromptWaitOptions {
        until: vec![AgentStatus::Done],
        timeout_ms: None,
    };
    assert_eq!(
        serde_json::to_value(wait).unwrap(),
        json!({"until":["done"]})
    );
}
