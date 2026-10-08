#[path = "../tests/support/schema.rs"]
mod schema;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    serde_json::to_writer_pretty(std::io::stdout().lock(), &schema::document()?)?;
    println!();
    Ok(())
}
