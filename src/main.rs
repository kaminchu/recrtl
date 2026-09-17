use anyhow::{Context, Result};
use clap::Parser;
use recrtl::cli::{Args, frequency};
fn run() -> Result<()> {
    let args = Args::parse();
    if args.list {
        for ch in 13..=62 {
            eprintln!("{ch}: {:.6} MHz", frequency(ch)? as f64 / 1e6);
        }
        return Ok(());
    }
    if args.list_devices {
        for d in recrtl::rtl::list()? {
            eprintln!("{d}");
        }
        return Ok(());
    }
    if args.list_regions || args.list_channels.is_some() {
        let db: serde_json::Value = serde_json::from_str(include_str!("../data/stations.json"))?;
        if args.list_regions {
            for (code, p) in db.as_object().unwrap() {
                eprintln!("{code}: {}", p["name"].as_str().unwrap());
            }
        }
        if let Some(region) = args.list_channels {
            let p = db.get(&region).context("unknown prefecture")?;
            for t in p["transmitters"].as_object().unwrap().values() {
                for (ch, s) in t["stations"].as_object().unwrap() {
                    eprintln!(
                        "{ch}: {} [{}]",
                        s["name"].as_str().unwrap(),
                        t["name"].as_str().unwrap()
                    );
                }
            }
        }
        return Ok(());
    }
    recrtl::receiver::run(&args)
}
fn main() {
    if let Err(e) = run() {
        eprintln!("recrtl: {e:#}");
        std::process::exit(1);
    }
}
