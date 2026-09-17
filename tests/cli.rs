use std::{fs, process::Command};
fn command() -> Command {
    Command::new(env!("CARGO_BIN_EXE_recrtl"))
}
#[test]
fn help_version_list_do_not_require_hardware() {
    for args in [
        vec!["--help"],
        vec!["--version"],
        vec!["-v"],
        vec!["--list"],
        vec!["--list-regions"],
        vec!["--list-channels", "niigata"],
    ] {
        let output = command().args(args).output().unwrap();
        assert!(output.status.success(), "{:?}", output);
    }
}
#[test]
fn invalid_settings_leave_no_output() {
    let path = std::env::temp_dir().join(format!("recrtl-invalid-{}.ts", std::process::id()));
    for args in [
        vec!["12", "10"],
        vec!["63", "10"],
        vec!["19", "NaN"],
        vec!["19", "0"],
        vec!["--gain", "NaN", "19", "10"],
        vec!["--frequency", "inf", "19", "10"],
        vec!["--sid", "65536", "19", "10"],
        vec!["--dev", "-1", "19", "10"],
        vec!["--trim", "19", "10"],
    ] {
        let output = command().args(args).arg(&path).output().unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert!(!path.exists());
    }
}
#[test]
fn malformed_and_silent_iq_fail_cleanly() {
    let dir = std::env::temp_dir().join(format!("recrtl-iq-{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let input = dir.join("input.u8iq");
    for data in [vec![127; 3], vec![127; 1000], vec![127; 4_000_000]] {
        fs::write(&input, data).unwrap();
        let output = command()
            .arg("--iq-file")
            .arg(&input)
            .args(["19", "-", "-"])
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
    }
    fs::remove_dir_all(dir).unwrap();
}
#[test]
fn existing_output_is_preserved() {
    let dir = std::env::temp_dir().join(format!("recrtl-existing-{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let input = dir.join("input.u8iq");
    let output = dir.join("out.ts");
    fs::write(&input, [127; 100]).unwrap();
    fs::write(&output, b"keep me").unwrap();
    let result = command()
        .arg("--iq-file")
        .arg(&input)
        .args(["19", "-"])
        .arg(&output)
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert_eq!(fs::read(&output).unwrap(), b"keep me");
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn sigterm_stops_an_unlocked_receiver() {
    use std::{
        process::Stdio,
        thread,
        time::{Duration, Instant},
    };
    let path = std::env::temp_dir().join(format!("recrtl-stop-{}.u8iq", std::process::id()));
    let file = fs::File::create(&path).unwrap();
    // Sparse no-signal input, long enough that EOF cannot race the signal.
    file.set_len(8_000_000_000).unwrap();
    let mut child = command()
        .arg("--iq-file")
        .arg(&path)
        .args(["19", "-", "-"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    thread::sleep(Duration::from_millis(250));
    assert_eq!(unsafe { libc::kill(child.id() as i32, libc::SIGTERM) }, 0);
    let started = Instant::now();
    while child.try_wait().unwrap().is_none() {
        if started.elapsed() > Duration::from_secs(3) {
            child.kill().unwrap();
            let _ = child.wait();
            fs::remove_file(&path).unwrap();
            panic!("SIGTERM did not stop receiver");
        }
        thread::sleep(Duration::from_millis(10));
    }
    let result = child.wait_with_output().unwrap();
    fs::remove_file(path).unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(result.stdout.is_empty());
}
