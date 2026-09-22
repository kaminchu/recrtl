use anyhow::{Result, bail, ensure};
use clap::Parser;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    version,
    disable_version_flag = true,
    about = "RTL-SDR ISDB-T one-segment recorder (Mode 3, GI 1/8, QPSK)",
    override_usage = "recrtl [OPTIONS] <CHANNEL> <RECTIME> <DESTFILE>"
)]
pub struct Args {
    /// Show version
    #[arg(short = 'v', long, action = clap::ArgAction::Version)]
    pub version: Option<bool>,
    /// Physical UHF channel (13..62)
    pub channel: Option<u8>,
    /// Seconds, H:M[:S], 1h30m, or '-' for unlimited
    pub rectime: Option<String>,
    /// TS output path, or '-' for stdout
    pub destfile: Option<PathBuf>,
    /// RTL-SDR device index
    #[arg(long = "dev", short = 'd', default_value_t = 0)]
    pub device: u32,
    /// Service IDs separated by commas; all, sd1, sd2, sd3, 1seg, epg, epg1seg
    #[arg(long, short = 'i', default_value = "all")]
    pub sid: String,
    /// Show physical channel frequencies
    #[arg(long, short = 'l')]
    pub list: bool,
    /// Show attached RTL-SDR receivers
    #[arg(long)]
    pub list_devices: bool,
    /// List preserved station database for a prefecture
    #[arg(long)]
    pub list_channels: Option<String>,
    #[arg(long)]
    pub list_regions: bool,
    /// Replay unsigned 8-bit interleaved IQ at 2.048 MS/s (no hardware needed)
    #[arg(long)]
    pub iq_file: Option<PathBuf>,
    /// Trim incomplete H.264/AAC recording edges (IQ file only; buffers TS until EOF)
    #[arg(long)]
    pub trim: bool,
    /// Tuner gain in dB (omit for automatic gain)
    #[arg(long, allow_hyphen_values = true)]
    pub gain: Option<f64>,
    /// Override channel frequency in MHz
    #[arg(long)]
    pub frequency: Option<f64>,
    /// Tuner frequency correction in ppm
    #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
    pub ppm: i32,
    /// Remove null TS packets
    #[arg(long, short = 's')]
    pub strip: bool,
    /// Report the one-seg service to Mirakurun as a full-seg digital TV service
    /// (rewrites the SDT service_type to 0x01; the stream stays one-seg)
    #[arg(long)]
    pub fullseg: bool,
    /// Print receiver statistics on stderr
    #[arg(long)]
    pub verbose: bool,
}

pub fn frequency(channel: u8) -> Result<u32> {
    ensure!((13..=62).contains(&channel), "channel must be 13..62");
    Ok((473_000_000.0 + 1_000_000.0 / 7.0 + 6_000_000.0 * (channel - 13) as f64).round() as u32)
}

pub fn duration(s: &str) -> Result<Option<f64>> {
    if s == "-" {
        return Ok(None);
    }
    let seconds = if s.contains(':') {
        let fields: Vec<_> = s.split(':').collect();
        ensure!(fields.len() == 2 || fields.len() == 3, "invalid rectime");
        let n: Vec<u64> = fields
            .iter()
            .map(|p| p.parse())
            .collect::<std::result::Result<_, _>>()?;
        ensure!(n[1] < 60 && (n.len() == 2 || n[2] < 60), "invalid rectime");
        n[0] as f64 * 3600.0 + n[1] as f64 * 60.0 + *n.get(2).unwrap_or(&0) as f64
    } else if s.bytes().any(|b| b.is_ascii_alphabetic()) {
        let mut total = 0.0;
        let mut start = 0;
        let mut previous = 4;
        for (i, c) in s.char_indices() {
            if c.is_ascii_digit() {
                continue;
            }
            let (order, scale) = match c {
                'h' | 'H' => (3, 3600.0),
                'm' | 'M' => (2, 60.0),
                's' | 'S' => (1, 1.0),
                _ => bail!("invalid rectime"),
            };
            ensure!(order < previous && i > start, "invalid rectime");
            total += s[start..i].parse::<u64>()? as f64 * scale;
            previous = order;
            start = i + 1;
        }
        if start < s.len() {
            ensure!(previous > 1, "invalid rectime");
            total += s[start..].parse::<u64>()? as f64;
        }
        total
    } else {
        s.parse::<f64>()?
    };
    ensure!(
        seconds.is_finite() && seconds > 0.0 && seconds <= u32::MAX as f64,
        "rectime must be positive and finite, or '-'"
    );
    Ok(Some(seconds))
}

impl Args {
    pub fn validate(&self) -> Result<(u32, Option<f64>)> {
        ensure!(
            !self.trim || self.iq_file.is_some(),
            "--trim requires --iq-file"
        );
        let channel = self
            .channel
            .ok_or_else(|| anyhow::anyhow!("CHANNEL RECTIME DESTFILE are required"))?;
        let mut hz = frequency(channel)?;
        if let Some(f) = self.frequency {
            ensure!(
                f.is_finite() && (470.0..=770.0).contains(&f),
                "frequency must be 470..770 MHz"
            );
            hz = (f * 1e6).round() as u32;
        }
        if let Some(g) = self.gain {
            ensure!(
                g.is_finite() && (-10.0..=60.0).contains(&g),
                "gain must be finite and -10..60 dB"
            );
        }
        ensure!(
            (-1000..=1000).contains(&self.ppm),
            "ppm must be -1000..1000"
        );
        let time = duration(
            self.rectime
                .as_deref()
                .ok_or_else(|| anyhow::anyhow!("RECTIME is required"))?,
        )?;
        ensure!(self.destfile.is_some(), "DESTFILE is required");
        Ok((hz, time))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn times() {
        for (s, n) in [
            ("60", 60.),
            ("1:30", 5400.),
            ("1:02:03", 3723.),
            ("1h2m3", 3723.),
            ("2M", 120.),
        ] {
            assert_eq!(duration(s).unwrap(), Some(n));
        }
        assert_eq!(duration("-").unwrap(), None);
        for s in [
            "",
            "0",
            "-1",
            "NaN",
            "inf",
            "1:60",
            "1m2h",
            "1s2",
            "junk",
            "1hgarbage",
            "1::2",
        ] {
            assert!(duration(s).is_err(), "{s}");
        }
    }
    #[test]
    fn channels() {
        assert_eq!(frequency(13).unwrap(), 473142857);
        assert_eq!(frequency(62).unwrap(), 767142857);
        assert!(frequency(12).is_err());
    }
    #[test]
    fn recdvb_syntax() {
        let a = Args::try_parse_from(["recrtl", "--dev", "1", "--sid", "32152", "19", "-", "-"])
            .unwrap();
        assert_eq!(a.validate().unwrap().1, None);
    }
}
