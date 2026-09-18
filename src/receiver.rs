use crate::{
    cli::Args,
    dsp::{Frontend, PERIOD, Resampler},
    fec::Fec,
    rtl::Rtl,
    ts::{Selection, Transport},
};
use anyhow::{Context, Result, ensure};
use rustfft::num_complex::Complex32 as C;
use std::{
    collections::VecDeque,
    fs::File,
    io::{Read, Write},
    os::fd::AsRawFd,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

pub struct Decoder {
    resampler: Resampler,
    pending: Vec<C>,
    pub frontend: Frontend,
    fec: Option<Fec>,
    transport: Transport,
    pub input_samples: u64,
    pub accepted: u64,
    pub rejected: u64,
    pub corrected: u64,
}
impl Decoder {
    pub fn new(selection: Selection, strip: bool) -> Self {
        Self {
            resampler: Resampler::new(),
            pending: vec![],
            frontend: Frontend::new(),
            fec: None,
            transport: Transport::new(selection, strip),
            input_samples: 0,
            accepted: 0,
            rejected: 0,
            corrected: 0,
        }
    }
    pub fn feed(&mut self, raw: &[u8]) -> Result<Vec<u8>> {
        ensure!(
            raw.len().is_multiple_of(2),
            "IQ input has an incomplete I/Q pair"
        );
        let samples: Vec<C> = raw
            .as_chunks::<2>()
            .0
            .iter()
            .map(|b| C::new((b[0] as f32 - 127.5) / 128., (b[1] as f32 - 127.5) / 128.))
            .collect();
        self.input_samples += samples.len() as u64;
        self.pending.extend(self.resampler.feed(&samples));
        let mut out = vec![];
        loop {
            if !self.frontend.locked {
                if self.pending.len() < Frontend::ACQUISITION {
                    break;
                }
                let n = self.frontend.acquire(&self.pending)?;
                self.pending.drain(..n);
                continue;
            }
            let count = ((self.pending.len().saturating_sub(64)) / PERIOD).min(32);
            if count == 0 {
                break;
            }
            let symbol = self.frontend.symbol;
            let (carriers, consumed) = match self.frontend.process(&self.pending, count) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("{e}; reacquiring");
                    self.frontend = Frontend::new();
                    self.fec = None;
                    self.transport.reset();
                    continue;
                }
            };
            self.pending.drain(..consumed);
            let frame = self.frontend.frame.as_ref().unwrap();
            for (i, c) in carriers.iter().enumerate() {
                if self.fec.is_none() {
                    if (symbol as i64 + i as i64 - frame.start as i64).rem_euclid(204) != 0 {
                        continue;
                    }
                    self.fec = Some(Fec::new(&frame.params));
                }
                let fec = self.fec.as_mut().unwrap();
                let a = fec.accepted;
                let r = fec.rejected;
                let corrected = fec.corrected;
                for packet in fec.symbol(c) {
                    for p in self.transport.feed(packet) {
                        out.extend(p);
                    }
                }
                self.accepted += fec.accepted - a;
                self.rejected += fec.rejected - r;
                self.corrected += fec.corrected - corrected;
            }
        }
        Ok(out)
    }
    pub fn packets(&self) -> u64 {
        self.transport.written
    }
    pub fn finish(&self) -> Result<()> {
        self.transport.finish()
    }
}

struct Output {
    file: File,
    flags: i32,
    pending: VecDeque<u8>,
    peak_pending: usize,
}
impl Output {
    // Buffer compressed TS rather than letting a paused player hold up the
    // much higher-rate IQ stream. Memory remains bounded for a stuck reader.
    const MAX_PENDING: usize = 4 * 1024 * 1024;
    fn new(path: &std::path::Path) -> Result<Self> {
        let file = if path == std::path::Path::new("-") {
            use std::os::fd::FromRawFd;
            let fd = unsafe { libc::dup(libc::STDOUT_FILENO) };
            ensure!(fd >= 0, "cannot duplicate stdout");
            unsafe { File::from_raw_fd(fd) }
        } else {
            File::options()
                .create_new(true)
                .write(true)
                .open(path)
                .with_context(|| {
                    format!(
                        "cannot create {} (existing files are not overwritten)",
                        path.display()
                    )
                })?
        };
        let fd = file.as_raw_fd();
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        ensure!(flags >= 0, "cannot read output flags");
        ensure!(
            unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } >= 0,
            "cannot set output nonblocking"
        );
        Ok(Self {
            file,
            flags,
            pending: VecDeque::new(),
            peak_pending: 0,
        })
    }
    fn write(&mut self, data: &[u8], stop: &AtomicBool, deadline: Option<Instant>) -> Result<bool> {
        if stop.load(Ordering::Relaxed) || deadline.is_some_and(|d| Instant::now() >= d) {
            return Ok(false);
        }
        if !self.flush_available()? {
            return Ok(false);
        }
        ensure!(
            self.pending.len() + data.len() <= Self::MAX_PENDING,
            "TS output stalled: reader has not drained the 4 MiB output buffer"
        );
        self.pending.extend(data);
        self.peak_pending = self.peak_pending.max(self.pending.len());
        self.flush_available()
    }

    fn flush_available(&mut self) -> Result<bool> {
        while !self.pending.is_empty() {
            match self.file.write(self.pending.as_slices().0) {
                Ok(0) => anyhow::bail!("output closed"),
                Ok(n) => {
                    self.pending.drain(..n);
                }
                Err(e) if e.kind() == std::io::ErrorKind::BrokenPipe => return Ok(false),
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(e) => return Err(e.into()),
            }
        }
        Ok(true)
    }

    fn finish(&mut self, stop: &AtomicBool, deadline: Option<Instant>) -> Result<bool> {
        while !self.pending.is_empty() {
            if stop.load(Ordering::Relaxed) || deadline.is_some_and(|d| Instant::now() >= d) {
                return Ok(false);
            }
            if !self.flush_available()? {
                return Ok(false);
            }
            if !self.pending.is_empty() {
                let mut fd = libc::pollfd {
                    fd: self.file.as_raw_fd(),
                    events: libc::POLLOUT,
                    revents: 0,
                };
                unsafe {
                    libc::poll(&mut fd, 1, 100);
                }
            }
        }
        Ok(true)
    }
}
impl Drop for Output {
    fn drop(&mut self) {
        unsafe {
            libc::fcntl(self.file.as_raw_fd(), libc::F_SETFL, self.flags);
        }
    }
}

pub fn run(args: &Args) -> Result<()> {
    let (frequency, seconds) = args.validate()?;
    let selection = Selection::parse(&args.sid)?;
    let mut decoder = Decoder::new(selection, args.strip);
    let stop = Arc::new(AtomicBool::new(false));
    let stopped = stop.clone();
    ctrlc::set_handler(move || stopped.store(true, Ordering::Relaxed))?;
    let mut input = if let Some(path) = &args.iq_file {
        let file = File::open(path)?;
        let meta = file.metadata()?;
        ensure!(meta.is_file(), "--iq-file must be a regular file");
        ensure!(meta.len() % 2 == 0, "IQ file length must be even");
        Some(file)
    } else {
        None
    };
    let rtl = if input.is_none() {
        Some(Rtl::open(args.device, frequency, args.gain, args.ppm)?)
    } else {
        None
    };
    let mut output = Output::new(args.destfile.as_ref().unwrap())?;
    let started = Instant::now();
    let deadline = if rtl.is_some() {
        seconds.map(|s| started + Duration::from_secs_f64(s))
    } else {
        None
    };
    let sample_limit = seconds.map(|s| (s * 2_048_000.) as u64);
    let mut raw = vec![0; 262144];
    let mut first = true;
    let mut recording = vec![];
    let mut output_closed = false;
    loop {
        if stop.load(Ordering::Relaxed) || deadline.is_some_and(|d| Instant::now() >= d) {
            break;
        }
        if !output.flush_available()? {
            output_closed = true;
            break;
        }
        let data = if let Some(file) = input.as_mut() {
            let remaining = sample_limit.map_or(raw.len(), |limit| {
                ((limit.saturating_sub(decoder.input_samples)) * 2).min(raw.len() as u64) as usize
            });
            if remaining == 0 {
                break;
            }
            let mut n = 0;
            while n < remaining {
                let got = file.read(&mut raw[n..remaining])?;
                if got == 0 {
                    break;
                }
                n += got;
            }
            if n == 0 {
                break;
            }
            raw[..n].to_vec()
        } else {
            let device = rtl.as_ref().unwrap();
            device.check()?;
            match device.receiver.recv_timeout(Duration::from_millis(100)) {
                Ok(data) => data,
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => continue,
                Err(_) => {
                    device.check()?;
                    anyhow::bail!("RTL-SDR stream stopped");
                }
            }
        };
        let ts = decoder.feed(&data)?;
        if args.trim {
            recording.extend(ts);
            continue;
        }
        if !ts.is_empty() {
            if first {
                eprintln!(
                    "TS output started after {:.2}s",
                    started.elapsed().as_secs_f64()
                );
                first = false;
            }
            if !output.write(&ts, &stop, deadline)? {
                output_closed = true;
                break;
            }
            // File replay can wait for the consumer; a live USB source cannot.
            if input.is_some() && !output.finish(&stop, deadline)? {
                output_closed = true;
                break;
            }
        }
    }
    eprintln!(
        "TS packets={}, RS accepted={}, rejected={}, corrected bytes={}, TMCC frames={}, elapsed={:.2}s",
        decoder.packets(),
        decoder.accepted,
        decoder.rejected,
        decoder.corrected,
        decoder.frontend.valid_frames,
        started.elapsed().as_secs_f64()
    );
    if args.verbose {
        eprintln!(
            "IQ samples={}, timing correction={} samples, fractional CFO={:.2} Hz",
            decoder.input_samples, decoder.frontend.timing, decoder.frontend.fractional
        );
        eprintln!("peak TS output buffer={} bytes", output.peak_pending);
    }
    if stop.load(Ordering::Relaxed) || output_closed {
        return Ok(());
    }
    decoder.finish()?;
    if args.trim {
        let data = crate::recording::trim(&recording)?;
        for chunk in data.chunks(188 * 1024) {
            if !output.write(chunk, &stop, deadline)? || !output.finish(&stop, deadline)? {
                return Ok(());
            }
        }
    }
    output.finish(&stop, deadline)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::fd::FromRawFd;

    fn pipe() -> (File, Output) {
        let mut fds = [0; 2];
        assert_eq!(
            unsafe { libc::pipe2(fds.as_mut_ptr(), libc::O_NONBLOCK) },
            0
        );
        // Both descriptors are newly created and uniquely owned here.
        let reader = unsafe { File::from_raw_fd(fds[0]) };
        let writer = unsafe { File::from_raw_fd(fds[1]) };
        (
            reader,
            Output {
                file: writer,
                flags: libc::O_NONBLOCK,
                pending: VecDeque::new(),
                peak_pending: 0,
            },
        )
    }
    #[test]
    fn blocked_output_obeys_deadline() {
        let (_reader, mut output) = pipe();
        let started = Instant::now();
        assert!(
            output
                .write(
                    &vec![0; 2_000_000],
                    &AtomicBool::new(false),
                    Some(started + Duration::from_millis(50)),
                )
                .unwrap()
        );
        let result = output
            .finish(
                &AtomicBool::new(false),
                Some(started + Duration::from_millis(50)),
            )
            .unwrap();
        assert!(!result);
        assert!(started.elapsed() < Duration::from_secs(1));
    }
    #[test]
    fn blocked_output_obeys_stop() {
        let (_reader, mut output) = pipe();
        let stop = Arc::new(AtomicBool::new(false));
        let stopper = stop.clone();
        let worker = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(50));
            stopper.store(true, Ordering::Relaxed);
        });
        let started = Instant::now();
        assert!(output.write(&vec![0; 2_000_000], &stop, None).unwrap());
        assert!(!output.finish(&stop, None).unwrap());
        assert!(started.elapsed() < Duration::from_secs(1));
        worker.join().unwrap();
    }
    #[test]
    fn closed_reader_is_a_clean_stop() {
        let (reader, mut output) = pipe();
        drop(reader);
        assert!(
            !output
                .write(&[0; 188], &AtomicBool::new(false), None)
                .unwrap()
        );
    }

    #[test]
    fn playback_pause_does_not_block_reception() {
        let (mut reader, mut output) = pipe();
        let data = vec![0x47; 188 * 4096];
        let started = Instant::now();
        // The player is not reading yet. The receive loop must still be able
        // to hand off TS and continue consuming the live IQ source.
        assert!(
            output
                .write(
                    &data,
                    &AtomicBool::new(false),
                    Some(started + Duration::from_millis(100))
                )
                .unwrap()
        );
        assert!(started.elapsed() < Duration::from_millis(100));
        let reader_thread = std::thread::spawn(move || {
            let mut received = Vec::new();
            let mut buffer = [0; 8192];
            loop {
                match reader.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(n) => received.extend_from_slice(&buffer[..n]),
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(1))
                    }
                    Err(e) => panic!("{e}"),
                }
            }
            received
        });
        assert!(
            output
                .finish(
                    &AtomicBool::new(false),
                    Some(Instant::now() + Duration::from_secs(2))
                )
                .unwrap()
        );
        drop(output);
        assert_eq!(reader_thread.join().unwrap(), data);
    }

    #[test]
    fn permanently_stalled_reader_has_a_bounded_buffer() {
        let (_reader, mut output) = pipe();
        let stop = AtomicBool::new(false);
        let data = vec![0; Output::MAX_PENDING];
        assert!(output.write(&data, &stop, None).unwrap());
        let error = output.write(&data, &stop, None).unwrap_err();
        assert!(error.to_string().contains("TS output stalled"));
        assert!(output.pending.len() <= Output::MAX_PENDING);
    }
}
