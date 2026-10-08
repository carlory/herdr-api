#[path = "support/schema.rs"]
mod schema;

use serde_json::Value;

fn differences(expected: &Value, actual: &Value, path: &str, output: &mut Vec<String>) {
    match (expected, actual) {
        (Value::Object(left), Value::Object(right)) => {
            let keys: std::collections::BTreeSet<_> = left.keys().chain(right.keys()).collect();
            for key in keys {
                let path = format!("{path}/{}", key.replace('~', "~0").replace('/', "~1"));
                match (left.get(key), right.get(key)) {
                    (Some(a), Some(b)) => differences(a, b, &path, output),
                    (Some(a), None) => {
                        output.push(format!("{path}: missing locally; official={a}"))
                    }
                    (None, Some(b)) => output.push(format!("{path}: extra locally; local={b}")),
                    _ => unreachable!(),
                }
            }
        }
        (Value::Array(left), Value::Array(right)) if left.len() == right.len() => {
            for (index, (a, b)) in left.iter().zip(right).enumerate() {
                differences(a, b, &format!("{path}/{index}"), output);
            }
        }
        _ if expected != actual => {
            output.push(format!("{path}: official={expected}; local={actual}"));
        }
        _ => {}
    }
}

#[test]
#[ignore = "requires Schema freshly exported from the official release; run scripts/check_release.py"]
fn official_release_schema_matches() {
    let path = std::env::var_os("HERDR_API_SCHEMA").expect("HERDR_API_SCHEMA must be set");
    let expected: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let actual = schema::document().unwrap();
    let mut diff = Vec::new();
    differences(&expected, &actual, "", &mut diff);
    let artifacts = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("artifacts");
    std::fs::create_dir_all(&artifacts).unwrap();
    std::fs::write(
        artifacts.join("extracted.schema.json"),
        serde_json::to_string_pretty(&actual).unwrap(),
    )
    .unwrap();
    std::fs::write(artifacts.join("schema.diff.txt"), diff.join("\n")).unwrap();
    assert!(diff.is_empty(), "Schema mismatch:\n{}", diff.join("\n"));
}

#[test]
fn comparison_reports_changed_constraints_and_missing_fields() {
    let mut diff = Vec::new();
    differences(
        &serde_json::json!({"maximum": 65535, "required": ["id"], "type": "integer"}),
        &serde_json::json!({"maximum": 65536, "required": []}),
        "",
        &mut diff,
    );
    assert_eq!(diff.len(), 3);
    assert!(diff.iter().any(|line| line.starts_with("/maximum:")));
    assert!(diff.iter().any(|line| line.starts_with("/required:")));
    assert!(diff.iter().any(|line| line.starts_with("/type:")));
}

#[test]
fn schema_references_resolve() {
    fn visit(value: &Value, root: &Value) {
        match value {
            Value::Object(object) => {
                if let Some(Value::String(reference)) = object.get("$ref") {
                    let pointer = reference.strip_prefix('#').expect("local Schema reference");
                    assert!(root.pointer(pointer).is_some(), "unresolved {reference}");
                }
                for child in object.values() {
                    visit(child, root);
                }
            }
            Value::Array(items) => {
                for item in items {
                    visit(item, root);
                }
            }
            _ => {}
        }
    }
    let root = schema::document().unwrap();
    visit(&root, &root);
}
