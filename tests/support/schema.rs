use herdr_api::*;
use serde_json::Value;

fn entry<T: schemars::JsonSchema>(name: &str) -> Result<Value, serde_json::Error> {
    let mut schema = serde_json::to_value(schemars::schema_for!(T))?;
    rewrite_refs(&mut schema, name);
    Ok(schema)
}

fn rewrite_refs(value: &mut Value, name: &str) {
    match value {
        Value::Object(object) => {
            if let Some(Value::String(reference)) = object.get_mut("$ref") {
                if let Some(path) = reference.strip_prefix("#/") {
                    *reference = format!("#/schemas/{name}/{path}");
                }
            }
            for child in object.values_mut() {
                rewrite_refs(child, name);
            }
        }
        Value::Array(items) => {
            for item in items {
                rewrite_refs(item, name);
            }
        }
        _ => {}
    }
}

// Mirrors src/api/schema/tests.rs::protocol_schema_document at the pinned tag.
pub fn document() -> Result<Value, serde_json::Error> {
    Ok(serde_json::json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Herdr API",
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_VERSION,
        "schemas": {
            "request": entry::<Request>("request")?,
            "success_response": entry::<SuccessResponse>("success_response")?,
            "error_response": entry::<ErrorResponse>("error_response")?,
            "event": entry::<EventEnvelope>("event")?,
            "subscription_event": entry::<SubscriptionEventEnvelope>("subscription_event")?,
        }
    }))
}
