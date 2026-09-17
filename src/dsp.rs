use anyhow::{Result, ensure};
use rustfft::{Fft, FftPlanner, num_complex::Complex32 as C};
use std::{collections::VecDeque, f32::consts::TAU, sync::Arc};
pub const FFT: usize = 1024;
pub const GUARD: usize = 128;
pub const PERIOD: usize = FFT + GUARD;
pub const RATE: f32 = 1024.0 / 0.001008;
pub const TMCC: [i32; 4] = [-115, -85, 70, 133];
const AC: [i32; 8] = [-209, -127, -10, -7, 10, 28, 161, 191];

// Stateful rational low-pass resampler: 2.048 MS/s -> 64/63 MS/s.
// Each phase has a 65-tap windowed sinc, cutoff 0.235 input cycles/sample.
pub struct Resampler {
    taps: Vec<Vec<f32>>,
    samples: Vec<C>,
    base: usize,
    time: usize,
}
impl Default for Resampler {
    fn default() -> Self {
        Self::new()
    }
}
impl Resampler {
    pub fn new() -> Self {
        let taps = (0..125)
            .map(|phase| {
                let mut h: Vec<f32> = (-32..=32)
                    .map(|k| {
                        let x = k as f32 - phase as f32 / 125.;
                        let sinc = if x.abs() < 1e-6 {
                            0.47
                        } else {
                            (std::f32::consts::PI * 0.47 * x).sin() / (std::f32::consts::PI * x)
                        };
                        sinc * (0.42
                            + 0.5 * (std::f32::consts::PI * x / 33.).cos()
                            + 0.08 * (TAU * x / 33.).cos())
                    })
                    .collect();
                let sum: f32 = h.iter().sum();
                for v in &mut h {
                    *v /= sum;
                }
                h
            })
            .collect();
        Self {
            taps,
            samples: vec![C::default(); 32],
            base: 0,
            time: 32 * 125,
        }
    }
    pub fn feed(&mut self, input: &[C]) -> Vec<C> {
        self.samples.extend_from_slice(input);
        let mut out = Vec::with_capacity(input.len() / 2 + 1);
        while self.time / 125 + 32 < self.base + self.samples.len() {
            let center = self.time / 125 - self.base;
            let value = self.samples[center - 32..=center + 32]
                .iter()
                .zip(&self.taps[self.time % 125])
                .map(|(v, h)| v * *h)
                .sum();
            out.push(value);
            self.time += 252;
        }
        let discard = (self.time / 125)
            .saturating_sub(32)
            .saturating_sub(self.base)
            .min(self.samples.len());
        self.samples.drain(..discard);
        self.base += discard;
        out
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Parameters {
    pub layers: [[u8; 4]; 3],
    pub partial: bool,
}
impl Parameters {
    pub fn parse(b: &[u8]) -> Self {
        let get = |s, w| b[s..s + w].iter().fold(0, |a, b| (a << 1) | b);
        Self {
            partial: b[27] != 0,
            layers: [28, 41, 54].map(|s| [get(s, 3), get(s + 3, 3), get(s + 6, 3), get(s + 9, 4)]),
        }
    }
    pub fn validate(&self) -> Result<()> {
        let [m, r, i, n] = self.layers[0];
        ensure!(
            self.partial && m == 1 && r < 5 && i < 4 && n == 1,
            "unsupported TMCC Layer A: {:?}; need partial-reception QPSK, one segment",
            self.layers[0]
        );
        Ok(())
    }
}
pub fn remainder(bits: &[u8]) -> u128 {
    let generator = [
        82, 77, 76, 71, 67, 66, 56, 52, 48, 40, 36, 34, 24, 22, 18, 10, 4, 0,
    ]
    .iter()
    .fold(0u128, |a, b| a | (1u128 << b));
    bits.iter().fold(0, |a, b| {
        let v = (a << 1) | *b as u128;
        if v & (1 << 82) != 0 { v ^ generator } else { v }
    })
}
pub fn valid_tmcc(b: &[u8]) -> bool {
    if b.len() != 204 {
        return false;
    }
    let sync = b[1..17].iter().fold(0u16, |a, b| (a << 1) | *b as u16);
    (sync == 0x35ee || sync == !0x35ee) && remainder(&b[20..]) == 0
}
#[derive(Clone, Debug)]
pub struct Frame {
    pub shift: i32,
    pub start: usize,
    pub params: Parameters,
}

pub fn synchronize(samples: &[C]) -> Option<(usize, f32, f32)> {
    if samples.len() < PERIOD * 32 {
        return None;
    }
    let mut sums = vec![0f32; PERIOD];
    let mut counts = vec![0; PERIOD];
    let mut correlations = vec![C::default(); PERIOD];
    let mut corr = C::default();
    let mut ea = 0.;
    let mut eb = 0.;
    for i in 0..samples.len() - FFT {
        corr += samples[i].conj() * samples[i + FFT];
        ea += samples[i].norm_sqr();
        eb += samples[i + FFT].norm_sqr();
        if i >= GUARD {
            let j = i - GUARD;
            corr -= samples[j].conj() * samples[j + FFT];
            ea -= samples[j].norm_sqr();
            eb -= samples[j + FFT].norm_sqr();
        }
        if i + 1 >= GUARD {
            let p = (i + 1 - GUARD) % PERIOD;
            sums[p] += corr.norm() / (ea.max(0.) * eb.max(0.)).max(1e-24).sqrt();
            correlations[p] += corr;
            counts[p] += 1;
        }
    }
    for (s, n) in sums.iter_mut().zip(counts) {
        *s /= n.max(1) as f32;
    }
    let start = (0..PERIOD).max_by(|&a, &b| sums[a].total_cmp(&sums[b]))?;
    Some((
        start,
        correlations[start].arg() / (TAU * 0.001008),
        sums[start],
    ))
}
pub fn spectra(samples: &[C], start: usize, cfo: f32) -> Vec<Vec<C>> {
    let fft = FftPlanner::new().plan_fft_forward(FFT);
    let start = start + GUARD - 16;
    if samples.len() < start + FFT {
        return vec![];
    }
    (start..=samples.len() - FFT)
        .step_by(PERIOD)
        .map(|p| {
            let mut s: Vec<_> = (0..FFT)
                .map(|j| samples[p + j] * C::from_polar(1., -TAU * cfo * (p + j) as f32 / RATE))
                .collect();
            fft.process(&mut s);
            s.rotate_left(FFT / 2);
            s
        })
        .collect()
}
pub fn find_frames(spectra: &[Vec<C>]) -> Vec<Frame> {
    if spectra.len() < 205 {
        return vec![];
    }
    let mut frames = vec![];
    for shift in -40..=40 {
        let rotation = C::from_polar(1., -TAU * shift as f32 * PERIOD as f32 / FFT as f32);
        let bits: Vec<u8> = spectra
            .windows(2)
            .map(|s| {
                let d: C = TMCC
                    .iter()
                    .map(|b| {
                        let i = (512 + b + shift) as usize;
                        s[1][i] * s[0][i].conj() * rotation
                    })
                    .sum();
                (d.re < 0.) as u8
            })
            .collect();
        for (i, b) in bits.windows(204).enumerate() {
            if valid_tmcc(b) {
                frames.push(Frame {
                    shift,
                    start: i + 1,
                    params: Parameters::parse(b),
                });
            }
        }
    }
    frames
}
pub fn pilot_sequence() -> Vec<f32> {
    let mut reg = 2047;
    (0..5617)
        .map(|_| {
            let v = (1 - 2 * (reg & 1)) as f32 * 4. / 3.;
            reg = (reg >> 1) | (((reg ^ (reg >> 2)) & 1) << 10);
            v
        })
        .collect()
}
pub fn targets(phase: i32) -> Vec<i32> {
    (-216..216)
        .filter(|r| (r - 3 * phase).rem_euclid(12) != 0 && !TMCC.contains(r) && !AC.contains(r))
        .collect()
}
fn equalize(s: &[C], shift: i32, phase: i32, pilots: &[f32]) -> (Vec<C>, [C; 4]) {
    let locations: Vec<i32> = (-240 + 3 * phase..=240).step_by(12).collect();
    let gains: Vec<C> = locations
        .iter()
        .map(|&p| s[(512 + p + shift) as usize] / pilots[(2808 + p) as usize])
        .collect();
    let get = |p: i32| {
        let right = locations.partition_point(|&v| v <= p);
        let w = (p - locations[right - 1]) as f32 / 12.;
        let response = gains[right - 1] * (1. - w) + gains[right] * w;
        s[(512 + p + shift) as usize]
            / if response.norm_sqr() > 1e-16 {
                response
            } else {
                C::new(1e-8, 0.)
            }
    };
    (targets(phase).into_iter().map(get).collect(), TMCC.map(get))
}

pub struct Frontend {
    pub locked: bool,
    pub symbol: usize,
    pub frame: Option<Frame>,
    pub fractional: f32,
    pub valid_frames: u64,
    pub timing: i64,
    phase: f32,
    bad_cp: usize,
    last_tmcc: usize,
    bits: VecDeque<u8>,
    previous: Option<[C; 4]>,
    pilots: Vec<f32>,
    fft: Arc<dyn Fft<f32>>,
}
impl Default for Frontend {
    fn default() -> Self {
        Self::new()
    }
}
impl Frontend {
    pub const ACQUISITION: usize = PERIOD * 816;
    pub fn new() -> Self {
        Self {
            locked: false,
            symbol: 0,
            frame: None,
            fractional: 0.,
            valid_frames: 0,
            timing: 0,
            phase: 0.,
            bad_cp: 0,
            last_tmcc: 0,
            bits: VecDeque::new(),
            previous: None,
            pilots: pilot_sequence(),
            fft: FftPlanner::new().plan_fft_forward(FFT),
        }
    }
    pub fn acquire(&mut self, samples: &[C]) -> Result<usize> {
        let window = &samples[..Self::ACQUISITION];
        let (mut start, cfo, confidence) = synchronize(window).unwrap();
        if confidence < 0.25 {
            return Ok(PERIOD * 204);
        }
        let frames = find_frames(&spectra(window, start, cfo));
        if frames.len() < 2 {
            return Ok(PERIOD * 204);
        }
        let first = &frames[0];
        if frames.iter().any(|f| {
            f.shift != first.shift || f.start % 204 != first.start % 204 || f.params != first.params
        }) {
            return Ok(PERIOD * 204);
        }
        first.params.validate()?;
        self.frame = Some(first.clone());
        self.fractional = cfo;
        self.symbol = 0;
        if start < 32 {
            start += PERIOD;
            self.symbol = 1;
        }
        self.last_tmcc = self.symbol;
        self.locked = true;
        eprintln!(
            "lock: CP={confidence:.3}, CFO={:.1} Hz, Layer A={:?}",
            cfo + first.shift as f32 / 0.001008,
            first.params.layers[0]
        );
        Ok(start - 32)
    }
    pub fn process(&mut self, samples: &[C], count: usize) -> Result<(Vec<Vec<C>>, usize)> {
        let mut score = [0.; 17];
        let mut correlations = [C::default(); 17];
        for n in 0..count {
            for k in 0..17 {
                let p = 32 + n * PERIOD + k - 8;
                let mut c = C::default();
                let mut ea = 0.;
                let mut eb = 0.;
                for j in 0..GUARD {
                    let a = samples[p + j];
                    let b = samples[p + j + FFT];
                    c += a.conj() * b;
                    ea += a.norm_sqr();
                    eb += b.norm_sqr();
                }
                score[k] += c.norm() / (ea * eb).max(1e-24).sqrt() / count as f32;
                correlations[k] += c;
            }
        }
        let best = (0..17)
            .max_by(|&a, &b| score[a].total_cmp(&score[b]))
            .unwrap();
        let correction = best as i32 - 8;
        self.bad_cp = if score[best] < 0.25 {
            self.bad_cp + count
        } else {
            0
        };
        ensure!(self.bad_cp <= 204, "CP lock lost");
        if score[best] >= 0.25 {
            let spacing = 1. / 0.001008;
            let measured = correlations[best].arg() / TAU * spacing;
            self.fractional += 0.05
                * ((measured - self.fractional + spacing / 2.).rem_euclid(spacing) - spacing / 2.);
        }
        let slope = TAU * self.fractional / RATE;
        let frame = self.frame.as_ref().unwrap();
        let mut out = Vec::with_capacity(count);
        for n in 0..count {
            let p = (32 + n * PERIOD + GUARD - 16) as i32 + correction;
            let mut spectrum: Vec<C> = (0..FFT)
                .map(|j| {
                    let i = p as usize + j;
                    samples[i] * C::from_polar(1., -(self.phase + slope * i as f32))
                })
                .collect();
            self.fft.process(&mut spectrum);
            spectrum.rotate_left(512);
            let phase = (self.symbol as i64 + n as i64 - frame.start as i64).rem_euclid(4) as i32;
            let (data, current) = equalize(&spectrum, frame.shift, phase, &self.pilots);
            if let Some(previous) = self.previous {
                let d: f32 = current
                    .iter()
                    .zip(previous)
                    .map(|(a, b)| (a * b.conj()).re)
                    .sum();
                self.bits.push_back((d < 0.) as u8);
                if self.bits.len() > 204 {
                    self.bits.pop_front();
                }
            }
            self.previous = Some(current);
            if self.bits.len() == 204 {
                let b = self.bits.make_contiguous();
                if valid_tmcc(b) {
                    let s = self.symbol + n;
                    ensure!(
                        (s as i64 - 203 - frame.start as i64).rem_euclid(204) == 0
                            && Parameters::parse(b) == frame.params,
                        "TMCC settings or boundary changed"
                    );
                    self.last_tmcc = s;
                    self.valid_frames += 1;
                }
            }
            out.push(data);
        }
        self.symbol += count;
        ensure!(self.symbol - self.last_tmcc <= 204 * 8, "TMCC lock lost");
        let consumed = (count * PERIOD) as i32 + correction;
        self.phase = (self.phase + slope * consumed as f32).rem_euclid(TAU);
        self.timing += correction as i64;
        Ok((out, consumed as usize))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tmcc() -> Vec<u8> {
        let hex = "0650883d258b4b3fff258b4b3ffffffcafa0673eb9cb6ea3e296";
        hex.chars()
            .flat_map(|c| {
                let n = c.to_digit(16).unwrap() as u8;
                (0..4).rev().map(move |i| (n >> i) & 1)
            })
            .collect::<Vec<_>>()[4..]
            .to_vec()
    }
    #[test]
    fn broadcast_tmcc_and_errors() {
        let b = tmcc();
        assert_eq!(b.len(), 204);
        assert!(valid_tmcc(&b));
        assert_eq!(Parameters::parse(&b).layers[0], [1, 1, 3, 1]);
        for i in [1, 20, 28, 121, 122, 203] {
            let mut broken = b.clone();
            broken[i] ^= 1;
            assert!(!valid_tmcc(&broken));
        }
    }
    #[test]
    fn resampler_independent_of_chunks() {
        let data: Vec<_> = (0..12000)
            .map(|i| C::from_polar(1., TAU * 0.04 * i as f32))
            .collect();
        let reference = Resampler::new().feed(&data);
        let mut r = Resampler::new();
        let mut actual = vec![];
        for c in data.chunks(127) {
            actual.extend(r.feed(c));
        }
        assert_eq!(reference, actual);
        for (i, v) in actual.iter().enumerate().skip(100) {
            let expected = C::from_polar(1., TAU * 0.04 * (i as f32 * 252. / 125.));
            assert!((*v - expected).norm() < 0.001);
        }
    }
    #[test]
    fn tmcc_integer_frequency_offset() {
        for shift in [-11, 1, 7] {
            let bits: Vec<_> = std::iter::repeat_n(0, 17).chain(tmcc().repeat(3)).collect();
            let mut sign = 1.;
            let spectra: Vec<_> = bits
                .iter()
                .enumerate()
                .map(|(i, b)| {
                    if *b != 0 {
                        sign = -sign;
                    }
                    let mut s = vec![C::default(); FFT];
                    for bin in TMCC {
                        s[(512 + bin + shift) as usize] = C::from_polar(
                            sign,
                            TAU * shift as f32 * PERIOD as f32 / FFT as f32 * i as f32,
                        );
                    }
                    s
                })
                .collect();
            let frames = find_frames(&spectra);
            assert!(frames.len() >= 2);
            assert!(
                frames
                    .iter()
                    .all(|f| f.shift == shift && f.start % 204 == 17)
            );
        }
    }
    fn waveform(count: usize, slip: bool) -> (Frontend, Vec<C>, Vec<Vec<C>>) {
        let mut f = Frontend::new();
        f.locked = true;
        f.fractional = -410.;
        f.frame = Some(Frame {
            start: 0,
            shift: 1,
            params: Parameters::parse(&tmcc()),
        });
        let mut samples = vec![C::default(); 32];
        let mut expected = vec![];
        let inverse = FftPlanner::new().plan_fft_inverse(FFT);
        for i in 0..count {
            let phase = (i % 4) as i32;
            let mut s = vec![C::default(); FFT];
            for p in (-240 + 3 * phase..=240).step_by(12) {
                s[(513 + p) as usize] = C::new(f.pilots[(2808 + p) as usize], 0.);
            }
            for (n, p) in targets(phase).into_iter().enumerate() {
                s[(513 + p) as usize] = C::new(
                    if (n * 31 + i * 17) % 3 == 0 {
                        -0.707
                    } else {
                        0.707
                    },
                    if (n * 19 + i * 7) % 5 < 2 {
                        -0.707
                    } else {
                        0.707
                    },
                );
            }
            for p in TMCC {
                s[(513 + p) as usize] = C::new(1., 0.);
            }
            let shifted: Vec<_> = s
                .iter()
                .enumerate()
                .map(|(j, v)| v * C::from_polar(1., -TAU * (j as f32 - 512.) * 16. / 1024.))
                .collect();
            expected.push(equalize(&shifted, 1, phase, &f.pilots).0);
            s.rotate_left(512);
            inverse.process(&mut s);
            for v in &mut s {
                *v /= 1024.;
            }
            if slip && i == 64 {
                samples.push(s[FFT - GUARD]);
            }
            samples.extend_from_slice(&s[FFT - GUARD..]);
            samples.extend(s);
        }
        samples.extend([C::default(); 128]);
        for (i, v) in samples.iter_mut().enumerate() {
            *v *= C::from_polar(1., TAU * f.fractional * i as f32 / RATE);
        }
        (f, samples, expected)
    }
    #[test]
    fn tracking_cfo_and_clock_slip() {
        for slip in [false, true] {
            let (mut f, samples, expected) = waveform(128, slip);
            let mut position = 0;
            let mut result = vec![];
            for _ in 0..8 {
                let (out, n) = f.process(&samples[position..], 16).unwrap();
                result.extend(out);
                position += n;
            }
            for (a, b) in result.iter().flatten().zip(expected.iter().flatten()) {
                assert!((*a - *b).norm() < 0.01, "{a:?} {b:?}");
            }
            assert_eq!(f.timing, if slip { 1 } else { 0 });
        }
    }
    #[test]
    fn silence_and_lock_loss() {
        assert!(synchronize(&[C::default(); 16]).is_none());
        assert_eq!(synchronize(&vec![C::default(); PERIOD * 32]).unwrap().2, 0.);
        let (mut f, _, _) = waveform(1, false);
        for _ in 0..6 {
            f.process(&vec![C::default(); PERIOD * 32 + 128], 32)
                .unwrap();
        }
        assert!(
            f.process(&vec![C::default(); PERIOD * 32 + 128], 32)
                .is_err()
        );
    }
}
