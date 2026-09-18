//! Opt-in acceptance test using a real recording, not synthetic TS.
use std::{
    io::Write,
    process::{Command, Stdio},
};
#[test]
#[ignore = "set RECRTL_TEST_IQ to a >= 5 second 2.048 MS/s u8 IQ capture; requires ffmpeg and ffprobe"]
fn real_iq_decodes_to_audio_and_video() {
    let path = std::env::var("RECRTL_TEST_IQ").expect("RECRTL_TEST_IQ is required");
    let output = Command::new(env!("CARGO_BIN_EXE_recrtl"))
        .args(["--iq-file", &path, "--trim", "19", "-", "-"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.len() > 188 * 100);
    assert_eq!(output.stdout.len() % 188, 0);
    assert!(
        output
            .stdout
            .as_chunks::<188>()
            .0
            .iter()
            .all(|p| p[0] == 0x47)
    );
    let mut probe = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,codec_name,nb_read_frames",
            "-of",
            "json",
            "-i",
            "pipe:0",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    probe
        .stdin
        .take()
        .unwrap()
        .write_all(&output.stdout)
        .unwrap();
    let result = probe.wait_with_output().unwrap();
    assert!(result.status.success());
    let json: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    for codec in ["h264", "aac"] {
        assert!(json["streams"].as_array().unwrap().iter().any(|s| {
            s["codec_name"] == codec
                && s["nb_read_frames"]
                    .as_str()
                    .and_then(|s| s.parse::<u64>().ok())
                    .unwrap_or(0)
                    > 10
        }));
    }
    let mut ffmpeg = Command::new("ffmpeg")
        .args([
            "-v", "error", "-xerror", "-i", "pipe:0", "-map", "0:v:0", "-map", "0:a:0", "-f",
            "null", "-",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    ffmpeg
        .stdin
        .take()
        .unwrap()
        .write_all(&output.stdout)
        .unwrap();
    let result = ffmpeg.wait_with_output().unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(
        result.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
#[ignore = "set RECRTL_TEST_IQ to a real 2.048 MS/s u8 IQ capture"]
fn receiver_reacquires_after_signal_loss() {
    use recrtl::{receiver::Decoder, ts::Selection};
    let path = std::env::var("RECRTL_TEST_IQ").expect("RECRTL_TEST_IQ is required");
    let data = std::fs::read(path).unwrap();
    let mut decoder = Decoder::new(Selection::All, false);
    for chunk in data.chunks(262144) {
        decoder.feed(chunk).unwrap();
    }
    let first = decoder.packets();
    assert!(first > 100);
    for _ in 0..32 {
        decoder.feed(&vec![127; 262144]).unwrap();
    }
    assert!(!decoder.frontend.locked);
    for chunk in data.chunks(262144) {
        decoder.feed(chunk).unwrap();
    }
    assert!(decoder.frontend.locked);
    assert!(decoder.packets() > first + 100);
    decoder.finish().unwrap();
}
