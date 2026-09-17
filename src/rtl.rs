//! The only native dependency is the RTL-SDR USB driver, loaded at runtime.
use anyhow::{Context, Result, ensure};
use libloading::Library;
use std::{
    ffi::{CStr, c_char, c_int, c_void},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, SyncSender},
    },
    thread::{self, JoinHandle},
    time::Duration,
};
type Dev = *mut c_void;
type Callback = unsafe extern "C" fn(*mut u8, u32, *mut c_void);
struct Api {
    _library: Library,
    count: unsafe extern "C" fn() -> u32,
    name: unsafe extern "C" fn(u32) -> *const c_char,
    open: unsafe extern "C" fn(*mut Dev, u32) -> c_int,
    close: unsafe extern "C" fn(Dev) -> c_int,
    rate: unsafe extern "C" fn(Dev, u32) -> c_int,
    frequency: unsafe extern "C" fn(Dev, u32) -> c_int,
    gain_mode: unsafe extern "C" fn(Dev, c_int) -> c_int,
    gain: unsafe extern "C" fn(Dev, c_int) -> c_int,
    ppm: unsafe extern "C" fn(Dev, c_int) -> c_int,
    reset: unsafe extern "C" fn(Dev) -> c_int,
    read: unsafe extern "C" fn(Dev, Callback, *mut c_void, u32, u32) -> c_int,
    cancel: unsafe extern "C" fn(Dev) -> c_int,
}
impl Api {
    fn load() -> Result<Arc<Self>> {
        // SAFETY: all symbols use the signatures in rtl-sdr.h. Library outlives them.
        unsafe {
            let lib = Library::new("librtlsdr.so.2")
                .or_else(|_| Library::new("librtlsdr.so.0"))
                .or_else(|_| Library::new("librtlsdr.so"))
                .context(
                    "install librtlsdr to use an RTL-SDR receiver; --iq-file needs no driver",
                )?;
            Ok(Arc::new(Self {
                count: *lib.get(b"rtlsdr_get_device_count")?,
                name: *lib.get(b"rtlsdr_get_device_name")?,
                open: *lib.get(b"rtlsdr_open")?,
                close: *lib.get(b"rtlsdr_close")?,
                rate: *lib.get(b"rtlsdr_set_sample_rate")?,
                frequency: *lib.get(b"rtlsdr_set_center_freq")?,
                gain_mode: *lib.get(b"rtlsdr_set_tuner_gain_mode")?,
                gain: *lib.get(b"rtlsdr_set_tuner_gain")?,
                ppm: *lib.get(b"rtlsdr_set_freq_correction")?,
                reset: *lib.get(b"rtlsdr_reset_buffer")?,
                read: *lib.get(b"rtlsdr_read_async")?,
                cancel: *lib.get(b"rtlsdr_cancel_async")?,
                _library: lib,
            }))
        }
    }
}
pub fn list() -> Result<Vec<String>> {
    let api = Api::load()?;
    unsafe {
        Ok((0..(api.count)())
            .map(|i| {
                let p = (api.name)(i);
                if p.is_null() {
                    format!("{i}: unknown")
                } else {
                    format!("{i}: {}", CStr::from_ptr(p).to_string_lossy())
                }
            })
            .collect())
    }
}
struct CallbackState {
    sender: SyncSender<Vec<u8>>,
    stop: Arc<AtomicBool>,
    overflow: Arc<AtomicBool>,
    api: Arc<Api>,
    device: usize,
}
unsafe extern "C" fn receive(p: *mut u8, len: u32, context: *mut c_void) {
    // SAFETY: librtlsdr calls synchronously inside read_async, before state is dropped.
    let state = unsafe { &*(context as *const CallbackState) };
    if !state.stop.load(Ordering::Relaxed) {
        let data = unsafe { std::slice::from_raw_parts(p, len as usize) }.to_vec();
        if state.sender.try_send(data).is_err() {
            state.overflow.store(true, Ordering::Relaxed);
            state.stop.store(true, Ordering::Relaxed);
        }
    }
    if state.stop.load(Ordering::Relaxed) {
        unsafe {
            (state.api.cancel)(state.device as Dev);
        }
    }
}
pub struct Rtl {
    pub receiver: Receiver<Vec<u8>>,
    api: Arc<Api>,
    device: usize,
    stop: Arc<AtomicBool>,
    overflow: Arc<AtomicBool>,
    worker: Option<JoinHandle<i32>>,
}
impl Rtl {
    pub fn open(index: u32, frequency: u32, gain: Option<f64>, ppm: i32) -> Result<Self> {
        let api = Api::load()?;
        let mut device = std::ptr::null_mut();
        unsafe {
            ensure!(index < (api.count)(), "RTL-SDR device {index} not found");
            ensure!(
                (api.open)(&mut device, index) == 0,
                "cannot open RTL-SDR device {index}"
            );
        }
        let configure = (|| -> Result<()> {
            unsafe {
                for (status, label) in [
                    ((api.rate)(device, 2_048_000), "sample rate"),
                    ((api.frequency)(device, frequency), "frequency"),
                    ((api.gain_mode)(device, gain.is_some() as i32), "gain mode"),
                ] {
                    ensure!(status == 0, "RTL-SDR {label} failed: {status}");
                }
                if let Some(g) = gain {
                    ensure!(
                        (api.gain)(device, (g * 10.).round() as i32) == 0,
                        "RTL-SDR gain failed"
                    );
                }
                if ppm != 0 {
                    ensure!((api.ppm)(device, ppm) == 0, "RTL-SDR ppm correction failed");
                }
                ensure!((api.reset)(device) == 0, "RTL-SDR reset failed");
            }
            Ok(())
        })();
        if let Err(e) = configure {
            unsafe {
                (api.close)(device);
            }
            return Err(e);
        }
        let device = device as usize;
        let stop = Arc::new(AtomicBool::new(false));
        let overflow = Arc::new(AtomicBool::new(false));
        let (sender, receiver) = mpsc::sync_channel(64);
        let mut state = CallbackState {
            sender,
            stop: stop.clone(),
            overflow: overflow.clone(),
            api: api.clone(),
            device,
        };
        let worker = thread::spawn(move || unsafe {
            (state.api.read)(
                device as Dev,
                receive,
                &mut state as *mut _ as *mut c_void,
                0,
                262144,
            )
        });
        Ok(Self {
            receiver,
            api,
            device,
            stop,
            overflow,
            worker: Some(worker),
        })
    }
    pub fn check(&self) -> Result<()> {
        ensure!(
            !self.overflow.load(Ordering::Relaxed),
            "IQ queue overflow: processing cannot keep up with receiver"
        );
        Ok(())
    }
}
impl Drop for Rtl {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            while !worker.is_finished() {
                unsafe {
                    (self.api.cancel)(self.device as Dev);
                }
                thread::sleep(Duration::from_millis(10));
            }
            let _ = worker.join();
        }
        unsafe {
            (self.api.close)(self.device as Dev);
        }
    }
}
