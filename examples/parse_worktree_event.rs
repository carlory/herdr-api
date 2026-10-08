use herdr_api::{EventData, EventEnvelope, EventKind};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let json = std::env::var("HERDR_PLUGIN_EVENT_JSON")?;
    let event: EventEnvelope = serde_json::from_str(&json)?;
    match (event.event, event.data) {
        (EventKind::WorktreeCreated, EventData::WorktreeCreated { worktree, .. }) => {
            println!("{}", worktree.path);
            Ok(())
        }
        _ => Err("expected a matching worktree_created event envelope".into()),
    }
}
