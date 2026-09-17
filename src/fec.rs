use crate::{dsp::Parameters, permutation::PERMUTATION};
use rustfft::num_complex::Complex32 as C;
use std::collections::VecDeque;

pub const PUNCTURE: [&[u8]; 5] = [
    &[1, 1],
    &[1, 1, 0, 1],
    &[1, 1, 0, 1, 1, 0],
    &[1, 1, 0, 1, 1, 0, 0, 1, 1, 0],
    &[1, 1, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0],
];

// K=7, G1=171 octal and G2=133 octal, in shift-left representation.
// Register exchange keeps a 128-bit survivor history per state.
pub struct Viterbi {
    metrics: [f32; 64],
    paths: [u128; 64],
    steps: usize,
    puncture: &'static [u8],
    position: usize,
    pair: Vec<f32>,
    byte: u8,
    bits: usize,
}
impl Viterbi {
    pub fn new(rate: usize) -> Self {
        Self {
            metrics: [0.; 64],
            paths: [0; 64],
            steps: 0,
            puncture: PUNCTURE[rate],
            position: 0,
            pair: vec![],
            byte: 0,
            bits: 0,
        }
    }
    fn step(&mut self, a: f32, b: f32) -> Option<u8> {
        let mut m = [0.; 64];
        let mut p = [0; 64];
        for state in 0..64 {
            let pred = state >> 1;
            let cost = |prev: usize| {
                let reg = (prev << 1) | (state & 1);
                let x = (reg & 0x4f).count_ones() & 1;
                let y = (reg & 0x6d).count_ones() & 1;
                self.metrics[prev] + if x == 0 { a } else { -a } + if y == 0 { b } else { -b }
            };
            let lo = cost(pred);
            let hi = cost(pred | 32);
            let chosen = if lo >= hi { pred } else { pred | 32 };
            m[state] = lo.max(hi);
            p[state] = (self.paths[chosen] << 1) | (state & 1) as u128;
        }
        let best = (0..64).max_by(|&a, &b| m[a].total_cmp(&m[b])).unwrap();
        let max = m[best];
        for x in &mut m {
            *x -= max;
        }
        self.metrics = m;
        self.paths = p;
        self.steps += 1;
        if self.steps < 128 {
            return None;
        }
        self.byte = (self.byte << 1) | ((p[best] >> 127) as u8);
        self.bits += 1;
        if self.bits == 8 {
            self.bits = 0;
            Some(self.byte)
        } else {
            None
        }
    }
    pub fn feed(&mut self, soft: f32, out: &mut Vec<u8>) {
        loop {
            let keep = self.puncture[self.position];
            self.position = (self.position + 1) % self.puncture.len();
            self.pair.push(if keep == 1 { soft } else { 0. });
            if self.pair.len() == 2 {
                let a = self.pair[0];
                let b = self.pair[1];
                self.pair.clear();
                if let Some(v) = self.step(a, b) {
                    out.push(v);
                }
            }
            if keep == 1 {
                break;
            }
        }
    }
}
fn delay<T: Copy>(q: &mut VecDeque<T>, value: T) -> T {
    q.push_back(value);
    q.pop_front().unwrap()
}
pub fn prbs_byte(reg: &mut u16) -> u8 {
    let mut out = 0;
    for _ in 0..8 {
        let b = ((*reg >> 13) ^ (*reg >> 14)) & 1;
        *reg = ((*reg << 1) | b) & 0x7fff;
        out = (out << 1) | b as u8;
    }
    out
}

pub struct Fec {
    time: Vec<VecDeque<C>>,
    bit: VecDeque<f32>,
    viterbi: Viterbi,
    bytes: Vec<VecDeque<u8>>,
    byte_index: usize,
    packet: [u8; 204],
    prbs: u16,
    frame_bytes: usize,
    rs: reed_solomon::Decoder,
    pub accepted: u64,
    pub rejected: u64,
    pub corrected: u64,
}
impl Fec {
    pub fn new(params: &Parameters) -> Self {
        let depth = [0, 1, 2, 4][params.layers[0][2] as usize];
        let rate = params.layers[0][1] as usize;
        let (k, n) = [(1, 2), (2, 3), (3, 4), (5, 6), (7, 8)][rate];
        Self {
            time: (0..384)
                .map(|i| VecDeque::from(vec![C::default(); depth * (95 - (5 * i) % 96)]))
                .collect(),
            bit: VecDeque::from(vec![0.; 120]),
            viterbi: Viterbi::new(rate),
            bytes: (0..12)
                .map(|i| VecDeque::from(vec![0; 17 * (11 - i)]))
                .collect(),
            byte_index: 0,
            packet: [0; 204],
            prbs: 0xa9,
            frame_bytes: 204 * 384 * 2 * k / n / 8,
            rs: reed_solomon::Decoder::new(16),
            accepted: 0,
            rejected: 0,
            corrected: 0,
        }
    }
    pub fn symbol(&mut self, carriers: &[C]) -> Vec<[u8; 188]> {
        let mut decoded = vec![];
        for (i, &location) in PERMUTATION.iter().enumerate() {
            let c = delay(&mut self.time[i], carriers[location]);
            let real = delay(&mut self.bit, c.re);
            self.viterbi.feed(real.clamp(-2., 2.), &mut decoded);
            self.viterbi.feed(c.im.clamp(-2., 2.), &mut decoded);
        }
        let mut out = vec![];
        for value in decoded {
            let i = self.byte_index;
            let v = delay(&mut self.bytes[i % 12], value);
            if i.is_multiple_of(self.frame_bytes) {
                self.prbs = 0xa9;
            }
            let mask = prbs_byte(&mut self.prbs);
            let offset = i % 204;
            if offset == 203 {
                self.packet[0] = v;
            } else {
                self.packet[offset + 1] = v ^ mask;
            }
            self.byte_index += 1;
            if offset == 203 {
                match self.rs.correct_err_count(&self.packet, None) {
                    Ok((fixed, n)) if fixed[0] == 0x47 => {
                        let mut packet = [0; 188];
                        packet.copy_from_slice(fixed.data());
                        self.accepted += 1;
                        self.corrected += n as u64;
                        out.push(packet);
                    }
                    _ => self.rejected += 1,
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn viterbi_all_rates_and_chunk_boundaries() {
        let data: Vec<u8> = (0..200).map(|i| ((i * 71 + 9) % 256) as u8).collect();
        for rate in 0..5 {
            let mut decoder = Viterbi::new(rate);
            let mut state = 0u32;
            let mut pos = 0;
            let mut output = vec![];
            for byte in data.iter().copied().chain([0; 32]) {
                for bit in (0..8).rev() {
                    state = ((state << 1) | ((byte >> bit) & 1) as u32) & 127;
                    for poly in [0x4f, 0x6d] {
                        let b = (state & poly).count_ones() & 1;
                        if PUNCTURE[rate][pos % PUNCTURE[rate].len()] == 1 {
                            decoder.feed(if b == 0 { 1. } else { -1. }, &mut output);
                        }
                        pos += 1;
                    }
                }
            }
            assert_eq!(&output[..data.len()], data, "rate {rate}");
        }
    }
    #[test]
    fn rs_corrects_eight_errors_and_rejects_nine() {
        let data: Vec<u8> = (0..188).map(|n| n as u8).collect();
        let enc = reed_solomon::Encoder::new(16).encode(&data);
        let dec = reed_solomon::Decoder::new(16);
        let mut bad = enc.to_vec();
        for i in 0..8 {
            bad[i * 23] ^= 0x91;
        }
        assert_eq!(dec.correct(&bad, None).unwrap().data(), data);
        bad[185] ^= 0x91;
        assert!(dec.correct(&bad, None).is_err());
    }
    #[test]
    fn permutation_is_bijective() {
        let mut p = PERMUTATION;
        p.sort();
        assert_eq!(p, (0..384).collect::<Vec<_>>().as_slice());
    }
}
