use anyhow::{Result, bail, ensure};
use std::collections::{BTreeMap, BTreeSet};
pub fn crc32(data: &[u8]) -> u32 {
    let mut c = 0xffffffffu32;
    for &b in data {
        c ^= (b as u32) << 24;
        for _ in 0..8 {
            c = (c << 1) ^ if c & 0x80000000 != 0 { 0x04c11db7 } else { 0 };
        }
    }
    c
}
pub fn pid(p: &[u8]) -> u16 {
    ((p[1] as u16 & 31) << 8) | p[2] as u16
}
pub fn payload(p: &[u8]) -> &[u8] {
    if p.len() != 188 || p[3] & 0x10 == 0 {
        return &[];
    }
    let start = if p[3] & 0x20 != 0 {
        5 + p[4] as usize
    } else {
        4
    };
    p.get(start..).unwrap_or(&[])
}
#[derive(Default)]
pub struct Sections {
    buffers: BTreeMap<u16, Vec<u8>>,
    cc: BTreeMap<u16, u8>,
}
impl Sections {
    pub fn feed(&mut self, p: &[u8; 188]) -> Vec<Vec<u8>> {
        let id = pid(p);
        let data = payload(p);
        let mut out = vec![];
        if p[0] != 0x47
            || p[1] & 0x80 != 0
            || p[3] & 0xc0 != 0
            || (p[3] & 0x20 != 0 && p[4] > 0 && p[5] & 0x80 != 0)
        {
            self.buffers.remove(&id);
            self.cc.remove(&id);
            return out;
        }
        if data.is_empty() {
            return out;
        }
        let cc = p[3] & 15;
        if let Some(old) = self.cc.insert(id, cc)
            && cc != (old + 1) % 16
        {
            self.buffers.remove(&id);
        }
        if p[1] & 0x40 != 0 {
            let pointer = data[0] as usize;
            if pointer + 1 > data.len() {
                self.buffers.remove(&id);
                return out;
            }
            if let Some(mut b) = self.buffers.remove(&id) {
                b.extend_from_slice(&data[1..1 + pointer]);
                Self::extract(&mut b, &mut out);
            }
            let mut b = data[1 + pointer..].to_vec();
            Self::extract(&mut b, &mut out);
            if !b.is_empty() {
                self.buffers.insert(id, b);
            }
        } else if let Some(b) = self.buffers.get_mut(&id) {
            b.extend_from_slice(data);
            Self::extract(b, &mut out);
        }
        out
    }
    fn extract(b: &mut Vec<u8>, out: &mut Vec<Vec<u8>>) {
        while !b.is_empty() {
            if b[0] == 0xff {
                b.clear();
                break;
            }
            if b.len() < 3 {
                break;
            }
            let size = 3 + ((b[1] as usize & 15) << 8) + b[2] as usize;
            if !(7..=4096).contains(&size) {
                b.clear();
                break;
            }
            if b.len() < size {
                break;
            }
            let section: Vec<u8> = b.drain(..size).collect();
            if crc32(&section) == 0 {
                out.push(section);
            }
        }
    }
}
/// Rewrite every service descriptor in an SDT section to the digital TV
/// service_type (0x01) and refresh the CRC. Other sections pass through.
fn fullseg_sdt(section: &[u8]) -> Vec<u8> {
    let mut s = section.to_vec();
    if s.len() < 15 || s[0] != 0x42 {
        return s;
    }
    let end = s.len() - 4;
    let mut i = 11;
    while i + 5 <= end {
        let dlen = ((s[i + 3] as usize & 15) << 8) + s[i + 4] as usize;
        let mut j = i + 5;
        let stop = j + dlen;
        if stop > end {
            break;
        }
        while j + 2 <= stop {
            let len = s[j + 1] as usize;
            if j + 2 + len > stop {
                break;
            }
            if s[j] == 0x48 && len >= 1 {
                s[j + 2] = 0x01;
            }
            j += 2 + len;
        }
        i = stop;
    }
    let crc = crc32(&s[..end]);
    s[end..].copy_from_slice(&crc.to_be_bytes());
    s
}
/// Wrap a complete PSI/SI section in TS packets with its own continuity counter.
fn emit_section(section: &[u8], id: u16, counter: &mut u8, out: &mut Vec<[u8; 188]>) {
    let mut data = vec![0]; // pointer_field
    data.extend_from_slice(section);
    for (i, chunk) in data.chunks(184).enumerate() {
        let mut p = [0xff; 188];
        p[..4].copy_from_slice(&[
            0x47,
            if i == 0 { 0x40 } else { 0 } | (id >> 8) as u8,
            id as u8,
            0x10 | *counter,
        ]);
        p[4..4 + chunk.len()].copy_from_slice(chunk);
        *counter = (*counter + 1) % 16;
        out.push(p);
    }
}
#[derive(Clone, Debug)]
pub enum Selection {
    All,
    Id(u16),
    Ordinal(usize),
    OneSeg,
    Epg(bool),
    Many(Vec<Selection>),
}
impl Selection {
    pub fn parse(s: &str) -> Result<Self> {
        if s.contains(',') {
            return Ok(Self::Many(
                s.split(',').map(Self::parse).collect::<Result<_>>()?,
            ));
        }
        Ok(match s.to_ascii_lowercase().as_str() {
            "all" => Self::All,
            "1seg" => Self::OneSeg,
            "epg" => Self::Epg(false),
            "epg1seg" => Self::Epg(true),
            "hd" | "sd1" => Self::Ordinal(0),
            "sd2" => Self::Ordinal(1),
            "sd3" => Self::Ordinal(2),
            _ => {
                let n = s.parse::<u16>()?;
                ensure!(n > 0, "SID must be nonzero");
                Self::Id(n)
            }
        })
    }
    fn program(&self, p: &Program, index: usize) -> bool {
        match self {
            Self::All => true,
            Self::Id(id) => *id == p.sid,
            Self::Ordinal(n) => index == *n,
            Self::OneSeg => p.pmt == 0x1fc8,
            Self::Epg(_) => false,
            Self::Many(items) => items.iter().any(|s| s.program(p, index)),
        }
    }
    fn all(&self) -> bool {
        match self {
            Self::All => true,
            Self::Many(items) => items.iter().any(Self::all),
            _ => false,
        }
    }
    fn epg(&self) -> bool {
        match self {
            Self::Epg(_) => true,
            Self::Many(items) => items.iter().any(Self::epg),
            _ => false,
        }
    }
    fn extra_pid(&self, id: u16) -> bool {
        match self {
            Self::Epg(true) => matches!(id, 0x11 | 0x27),
            Self::Epg(false) => matches!(id, 0x11 | 0x12 | 0x23 | 0x29),
            Self::Many(items) => items.iter().any(|s| s.extra_pid(id)),
            _ => false,
        }
    }
}
#[derive(Clone)]
struct Program {
    sid: u16,
    pmt: u16,
    pids: BTreeSet<u16>,
}
pub struct Transport {
    sections: Sections,
    programs: BTreeMap<u16, Program>,
    selection: Selection,
    counter: u8,
    count: usize,
    version: u8,
    tsid: u16,
    eit_counter: u8,
    sdt_counter: u8,
    strip: bool,
    fullseg: bool,
    pub written: u64,
}
impl Transport {
    pub fn new(selection: Selection, strip: bool, fullseg: bool) -> Self {
        Self {
            sections: Sections::default(),
            programs: BTreeMap::new(),
            selection,
            counter: 0,
            count: 0,
            version: 0,
            tsid: 1,
            eit_counter: 0,
            sdt_counter: 0,
            strip,
            fullseg,
            written: 0,
        }
    }
    pub fn feed(&mut self, p: [u8; 188]) -> Vec<[u8; 188]> {
        if p[0] != 0x47 || p[1] & 0x80 != 0 {
            return vec![];
        }
        let id = pid(&p);
        let mut sdt = vec![];
        if id == 0x11 {
            for s in self.sections.feed(&p) {
                // Only the current actual-TS SDT identifies this transport.
                if s[0] == 0x42 && s.len() >= 15 && s[5] & 1 != 0 {
                    let tsid = u16::from_be_bytes([s[3], s[4]]);
                    if self.tsid != tsid {
                        self.tsid = tsid;
                        self.version = (self.version + 1) & 31;
                        self.count = 0;
                    }
                }
                if self.fullseg {
                    sdt.push(s);
                }
            }
        }
        if (0x1fc8..=0x1fcf).contains(&id) {
            for s in self.sections.feed(&p) {
                if s[0] != 2 || s.len() < 16 || s[5] & 1 == 0 {
                    continue;
                }
                let sid = u16::from_be_bytes([s[3], s[4]]);
                let mut pids = BTreeSet::from([id, ((s[8] as u16 & 31) << 8) | s[9] as u16]);
                let mut offset = 12 + ((s[10] as usize & 15) << 8) + s[11] as usize;
                let end = s.len() - 4;
                if offset > end {
                    continue;
                }
                while offset + 5 <= end {
                    pids.insert(((s[offset + 1] as u16 & 31) << 8) | s[offset + 2] as u16);
                    offset += 5 + ((s[offset + 3] as usize & 15) << 8) + s[offset + 4] as usize;
                }
                if offset != end {
                    continue;
                }
                let changed = self
                    .programs
                    .get(&sid)
                    .is_none_or(|old| old.pids != pids || old.pmt != id);
                self.programs
                    .retain(|&old_sid, p| p.pmt != id || old_sid == sid);
                self.programs.insert(sid, Program { sid, pmt: id, pids });
                if changed {
                    self.version = (self.version + 1) & 31;
                    self.count = 0;
                }
            }
        }
        let selected: Vec<&Program> = self
            .programs
            .values()
            .enumerate()
            .filter(|(i, p)| self.selection.program(p, *i))
            .map(|(_, p)| p)
            .collect();
        if (selected.is_empty() && !self.selection.epg()) || id == 0 || (self.strip && id == 0x1fff)
        {
            return vec![];
        }
        let keep = self.selection.all()
            || matches!(id, 0x10 | 0x14)
            || self.selection.extra_pid(id)
            || (!selected.is_empty()
                && (matches!(id, 0x11..=0x13 | 0x27)
                    || selected.iter().any(|p| p.pids.contains(&id))));
        if !keep {
            return vec![];
        }
        let mut out = vec![];
        if self.count.is_multiple_of(100) {
            let mut s = vec![0, 0xb0, 0, 0, 1, 0xc1 | (self.version << 1), 0, 0];
            for program in selected {
                s.extend(program.sid.to_be_bytes());
                s.extend((0xe000 | program.pmt).to_be_bytes());
            }
            s[3..5].copy_from_slice(&self.tsid.to_be_bytes());
            s.extend([0, 0, 0xe0, 0x10]); // program 0 announces the NIT PID
            s[2] = (s.len() + 4 - 3) as u8;
            let crc = crc32(&s);
            s.extend(crc.to_be_bytes());
            let mut pat = [0xff; 188];
            pat[..5].copy_from_slice(&[0x47, 0x40, 0, 0x10 | self.counter, 0]);
            pat[5..5 + s.len()].copy_from_slice(&s);
            self.counter = (self.counter + 1) % 16;
            out.push(pat);
        }
        self.count += 1;
        if id == 0x11 && self.fullseg {
            // Rewrite the service_type of each SDT service to digital TV so
            // Mirakurun reports the one-seg service as full-seg (type=0x01).
            for section in &sdt {
                emit_section(&fullseg_sdt(section), 0x11, &mut self.sdt_counter, &mut out);
            }
        } else if id != 0x12 {
            out.push(p);
        }
        if matches!(id, 0x12 | 0x27) {
            // Mirakurun parses EIT on PID 0x12, not the one-seg PID 0x27.
            // Merge complete sections so native EIT and mirrored L-EIT cannot
            // interleave partial sections or clash in continuity counters.
            for s in self.sections.feed(&p) {
                let mut data = vec![0]; // pointer_field
                data.extend(s);
                for (i, chunk) in data.chunks(184).enumerate() {
                    let mut eit = [0xff; 188];
                    eit[..4].copy_from_slice(&[
                        0x47,
                        if i == 0 { 0x40 } else { 0 },
                        0x12,
                        0x10 | self.eit_counter,
                    ]);
                    eit[4..4 + chunk.len()].copy_from_slice(chunk);
                    self.eit_counter = (self.eit_counter + 1) % 16;
                    out.push(eit);
                }
            }
        }
        self.written += out.len() as u64;
        out
    }
    pub fn reset(&mut self) {
        self.sections = Sections::default();
        self.programs.clear();
        self.tsid = 1;
        self.count = 0;
        self.version = (self.version + 1) & 31;
    }
    pub fn finish(&self) -> Result<()> {
        if self.written == 0 {
            bail!("no valid TS for selected service (no signal, insufficient IQ, or SID absent)");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn section() -> Vec<u8> {
        let mut s = vec![
            2, 0xb0, 18, 0x7d, 0x98, 0xc1, 0, 0, 0xe1, 0x50, 0xf0, 0, 0x1b, 0xe1, 0x51, 0xf0, 0,
        ];
        s.extend(crc32(&s).to_be_bytes());
        s
    }
    fn packet(data: &[u8], cc: u8, start: bool) -> [u8; 188] {
        let mut p = [0xff; 188];
        p[..5].copy_from_slice(&[
            0x47,
            0x1f | if start { 0x40 } else { 0 },
            0xc8,
            0x30 | cc,
            (183 - data.len()) as u8,
        ]);
        if p[4] > 0 {
            p[5] = 0;
        }
        p[188 - data.len()..].copy_from_slice(data);
        p
    }
    fn psi(id: u16, mut s: Vec<u8>, cc: u8) -> [u8; 188] {
        let length = s.len() + 1;
        s[1] = 0xb0 | (length >> 8) as u8;
        s[2] = length as u8;
        s.extend(crc32(&s).to_be_bytes());
        let mut data = vec![0];
        data.extend(s);
        let mut p = packet(&data, cc, true);
        p[1] = 0x40 | (id >> 8) as u8;
        p[2] = id as u8;
        p
    }
    fn sdt(table: u8, current: bool) -> [u8; 188] {
        psi(
            0x11,
            vec![
                table,
                0,
                0,
                0x7e,
                3,
                0xc0 | u8::from(current),
                0,
                0,
                0x7e,
                3,
                0xff,
            ],
            0,
        )
    }
    #[test]
    fn mirakurun_scan_pat_matches_sdt_and_announces_nit() {
        let mut t = Transport::new(Selection::All, false, false);
        t.feed(psi(0x1fc8, section()[..17].to_vec(), 0));
        let out = t.feed(sdt(0x42, true));
        assert_eq!(pid(&out[0]), 0, "PAT must precede the actual SDT");
        let pat = Sections::default().feed(&out[0]).pop().unwrap();
        assert_eq!(&pat[3..5], &[0x7e, 3]);
        let programs = pat[8..pat.len() - 4].as_chunks::<4>().0;
        assert!(programs.contains(&[0, 0, 0xe0, 0x10]));
        assert!(programs.contains(&[0x7d, 0x98, 0xff, 0xc8]));
        assert_eq!(out.last(), Some(&sdt(0x42, true)));
        t.reset();
        let out = t.feed(psi(0x1fc8, section()[..17].to_vec(), 0));
        let pat = Sections::default().feed(&out[0]).pop().unwrap();
        assert_eq!(
            &pat[3..5],
            &[0, 1],
            "reset must forget the previous station"
        );
    }
    #[test]
    fn mirakurun_ignores_invalid_or_other_sdt() {
        for mut p in [sdt(0x46, true), sdt(0x42, false), sdt(0x42, true)] {
            if p == sdt(0x42, true) {
                p[187] ^= 1;
            }
            let mut t = Transport::new(Selection::All, false, false);
            t.feed(p);
            let out = t.feed(psi(0x1fc8, section()[..17].to_vec(), 0));
            let pat = Sections::default().feed(&out[0]).pop().unwrap();
            assert_eq!(&pat[3..5], &[0, 1]);
        }
    }
    #[test]
    fn mirakurun_receives_one_seg_eit_on_standard_pid() {
        let mut t = Transport::new(Selection::All, false, false);
        t.feed(psi(0x1fc8, section()[..17].to_vec(), 0));
        let eit = psi(
            0x27,
            vec![
                0x4e, 0, 0, 0x7d, 0x98, 0xc1, 0, 0, 0x7e, 3, 0x7e, 3, 0, 0x4e,
            ],
            7,
        );
        let expected = Sections::default().feed(&eit);
        let out = t.feed(eit);
        assert!(out.contains(&eit), "retain the original one-seg EIT");
        let mut parser = Sections::default();
        let actual: Vec<_> = out
            .iter()
            .filter(|p| pid(*p) == 0x12)
            .flat_map(|p| parser.feed(p))
            .collect();
        assert_eq!(actual, expected);
    }
    #[test]
    fn mirakurun_merges_split_eit_without_corrupting_sections() {
        let mut t = Transport::new(Selection::All, false, false);
        t.feed(psi(0x1fc8, section()[..17].to_vec(), 0));
        // A long EIT section, with a native PID 0x12 section arriving midway.
        let mut s = vec![
            0x4e, 0xf1, 0x2b, 0x7d, 0x98, 0xc1, 0, 0, 0x7e, 3, 0x7e, 3, 0, 0x4e,
        ];
        s.resize(298, 0);
        s.extend(crc32(&s).to_be_bytes());
        let mut first = vec![0];
        first.extend(&s[..150]);
        let mut a = packet(&first, 5, true);
        a[1] = 0x40;
        a[2] = 0x27;
        let mut b = packet(&s[150..], 6, false);
        b[1] = 0;
        b[2] = 0x27;
        let native = psi(
            0x12,
            vec![
                0x4e, 0, 0, 0x7d, 0x98, 0xc1, 0, 0, 0x7e, 3, 0x7e, 3, 0, 0x4e,
            ],
            11,
        );
        let mut expected = Sections::default().feed(&native);
        expected.push(s);
        let mut out = vec![];
        for p in [a, native, b] {
            out.extend(t.feed(p).into_iter().filter(|p| pid(p) == 0x12));
        }
        assert_eq!(out.len(), 3);
        for pair in out.windows(2) {
            assert_eq!(pair[1][3] & 15, (pair[0][3] + 1) & 15);
        }
        let mut parser = Sections::default();
        let actual: Vec<_> = out.iter().flat_map(|p| parser.feed(p)).collect();
        assert_eq!(actual, expected);
        // A corrupt L-EIT section must never be mirrored to the standard PID.
        let mut corrupt = native;
        corrupt[2] = 0x27;
        corrupt[187] ^= 1;
        assert!(t.feed(corrupt).iter().all(|p| pid(p) != 0x12));
    }
    #[test]
    fn crc_known_vector() {
        assert_eq!(crc32(b"123456789"), 0x0376e6e7);
        assert_eq!(crc32(&section()), 0);
    }
    #[test]
    fn split_sections_and_discontinuity() {
        let s = section();
        let mut first = vec![0];
        first.extend(&s[..10]);
        let mut parser = Sections::default();
        assert!(parser.feed(&packet(&first, 0, true)).is_empty());
        assert_eq!(parser.feed(&packet(&s[10..], 1, false)), vec![s.clone()]);
        parser.feed(&packet(&first, 2, true));
        assert!(parser.feed(&packet(&s[10..], 4, false)).is_empty());
    }
    #[test]
    fn pat_and_service_filter() {
        let mut s = vec![0];
        s.extend(section());
        let p = packet(&s, 0, true);
        let mut t = Transport::new(Selection::parse("32152").unwrap(), false, false);
        let out = t.feed(p);
        assert_eq!(out.len(), 2);
        assert_eq!(pid(&out[0]), 0);
        let pat = Sections::default().feed(&out[0]).pop().unwrap();
        assert_eq!(&pat[8..12], &[0x7d, 0x98, 0xff, 0xc8]);
        let mut es = [0xff; 188];
        es[..4].copy_from_slice(&[0x47, 1, 0x51, 0x10]);
        assert_eq!(t.feed(es), vec![es]);
        es[2] = 0x52;
        assert!(t.feed(es).is_empty());
        let mut missing = Transport::new(Selection::parse("1").unwrap(), false, false);
        assert!(missing.feed(p).is_empty());
        assert!(missing.finish().is_err());
    }
    #[test]
    fn corrupt_and_malformed_psi() {
        let mut s = vec![0];
        s.extend(section());
        s[8] ^= 1;
        assert!(Sections::default().feed(&packet(&s, 0, true)).is_empty());
        for s in ["", "0", "-1", "1,", "65536", "foo"] {
            assert!(Selection::parse(s).is_err());
        }
    }

    #[test]
    fn service_replacement_does_not_leave_stale_pat_entries() {
        let mut transport = Transport::new(Selection::All, false, false);
        for index in 0..32u16 {
            let mut s = section();
            s[3..5].copy_from_slice(&(100 + index).to_be_bytes());
            let end = s.len() - 4;
            let crc = crc32(&s[..end]);
            s[end..].copy_from_slice(&crc.to_be_bytes());
            let mut data = vec![0];
            data.extend(s);
            let output = transport.feed(packet(&data, (index % 16) as u8, true));
            let pat = Sections::default().feed(&output[0]).pop().unwrap();
            assert_eq!(pat.len(), 20);
            assert_eq!(u16::from_be_bytes([pat[8], pat[9]]), 100 + index);
        }
    }

    #[test]
    fn recdvb_service_aliases_and_epg_union() {
        let primary = Program {
            sid: 32152,
            pmt: 0x1fc8,
            pids: BTreeSet::new(),
        };
        let secondary = Program {
            sid: 32153,
            pmt: 0x1fc9,
            pids: BTreeSet::new(),
        };
        assert!(Selection::parse("HD").unwrap().program(&primary, 0));
        assert!(!Selection::parse("1seg").unwrap().program(&secondary, 1));
        let selection = Selection::parse("32153,epg1seg").unwrap();
        assert!(!selection.program(&primary, 0));
        assert!(selection.program(&secondary, 1));
        assert!(selection.extra_pid(0x27));
        assert!(!selection.extra_pid(0x12));
        let mut t = Transport::new(selection, false, false);
        let mut eit = [0xff; 188];
        eit[..4].copy_from_slice(&[0x47, 0, 0x27, 0x10]);
        assert_eq!(t.feed(eit).last(), Some(&eit));
    }

    #[test]
    fn fullseg_rewrites_sdt_service_type_to_digital_tv() {
        // SDT with one service (SID 0x7d98) whose service_type is data (0xC0).
        let sdt = vec![
            0x42, 0, 0, 0x7e, 0x03, 0xc1, 0, 0, 0x7e, 0x03, 0xff, 0x7d, 0x98, 0xf3, 0x00, 0x07,
            0x48, 0x05, 0xc0, 0x00, 0x02, b'A', b'B',
        ];
        let pmt = psi(0x1fc8, section()[..17].to_vec(), 0);
        let mut t = Transport::new(Selection::All, false, true);
        t.feed(pmt);
        let out = t.feed(psi(0x11, sdt.clone(), 0));
        let section = Sections::default()
            .feed(out.iter().find(|p| pid(*p) == 0x11).unwrap())
            .pop()
            .unwrap();
        assert_eq!(section[0], 0x42);
        assert_eq!(section[18], 0x01, "service_type must become digital TV");
        assert_eq!(crc32(&section), 0);

        let mut t = Transport::new(Selection::All, false, false);
        t.feed(pmt);
        let out = t.feed(psi(0x11, sdt, 0));
        let section = Sections::default()
            .feed(out.iter().find(|p| pid(*p) == 0x11).unwrap())
            .pop()
            .unwrap();
        assert_eq!(section[18], 0xc0, "unmodified without --fullseg");
    }
}
