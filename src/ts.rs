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
/// KonomiTV compatibility: rewrite every service descriptor in an SDT section
/// to the digital TV service_type (0x01) and refresh the CRC. Other sections
/// pass through.
fn konomitv_sdt(section: &[u8]) -> Vec<u8> {
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
/// Add a synthesized audio component descriptor (0xC4) to every event in a
/// one-seg EIT section that lacks one. The one-seg L-EIT only carries
/// short-event/content descriptors, so Mirakurun exposes no `audio`/`audios`
/// and clients such as KonomiTV fail to parse the program. The descriptor is
/// filled with fixed one-seg values (AAC stereo, 48 kHz, Japanese, main).
/// Section length and CRC are refreshed. Other sections pass through.
fn konomitv_eit(section: &[u8]) -> Vec<u8> {
    // EIT table_ids are 0x4E..=0x6F; anything else passes through.
    if section.len() < 18 || !(0x4e..=0x6f).contains(&section[0]) {
        return section.to_vec();
    }
    let end = section.len() - 4;
    let mut out = section[..14].to_vec();
    let mut i = 14;
    while i + 12 <= end {
        let dlen = ((section[i + 10] as usize & 15) << 8) + section[i + 11] as usize;
        let stop = i + 12 + dlen;
        if stop > end {
            return section.to_vec();
        }
        let mut j = i + 12;
        let mut has_audio = false;
        while j + 2 <= stop {
            let len = section[j + 1] as usize;
            if j + 2 + len > stop {
                break;
            }
            if section[j] == 0xc4 {
                has_audio = true;
                break;
            }
            j += 2 + len;
        }
        let extra = if has_audio { 0 } else { 11 };
        let new_dlen = dlen + extra;
        if new_dlen > 0xfff {
            return section.to_vec();
        }
        // event_id/start_time/duration + refreshed running_status & length
        out.extend_from_slice(&section[i..i + 10]);
        out.push((section[i + 10] & 0xf0) | ((new_dlen >> 8) as u8 & 0x0f));
        out.push(new_dlen as u8);
        out.extend_from_slice(&section[i + 12..stop]);
        if extra != 0 {
            // stream_content=audio, component_type=stereo, tag=1, AAC,
            // no simulcast, main component, 48 kHz, Japanese.
            out.extend_from_slice(&[
                0xc4, 0x09, 0xf2, 0x03, 0x01, 0x0f, 0xff, 0x4f, 0x6a, 0x70, 0x6e,
            ]);
        }
        i = stop;
    }
    let length = out.len() + 1; // section_length counts bytes after byte 2, incl. CRC
    if length > 0xfff {
        return section.to_vec();
    }
    out[1] = (section[1] & 0xf0) | ((length >> 8) as u8 & 0x0f);
    out[2] = length as u8;
    let crc = crc32(&out);
    out.extend_from_slice(&crc.to_be_bytes());
    out
}
/// Service IDs of the current actual-TS SDT.
fn sdt_services(section: &[u8]) -> BTreeSet<u16> {
    let mut services = BTreeSet::new();
    if section.len() < 15 || section[0] != 0x42 {
        return services;
    }
    let end = section.len() - 4;
    let mut i = 11;
    while i + 5 <= end {
        let dlen = ((section[i + 3] as usize & 15) << 8) + section[i + 4] as usize;
        if i + 5 + dlen > end {
            break;
        }
        services.insert(u16::from_be_bytes([section[i], section[i + 1]]));
        i += 5 + dlen;
    }
    services
}
/// Synthesize an empty EIT schedule section (table_id 0x50..=0x5F) for one
/// service from a present/following section. One-seg never broadcasts EIT
/// schedule, so Mirakurun's EPG gatherer never marks the guide as complete and
/// always runs until the retrieval timeout. These sections carry no events;
/// they only move Mirakurun's readiness bookkeeping forward. `last_table_id`
/// is used so several services can be registered before any is declared ready.
fn konomitv_schedule(section: &[u8], service_id: u16, table_id: u8, last: u8) -> Vec<u8> {
    if section.len() < 14 || !(0x4e..=0x6f).contains(&section[0]) {
        return vec![];
    }
    let mut s = vec![
        table_id,
        0xb0,
        0x0f, // header plus CRC, no events
        (service_id >> 8) as u8,
        service_id as u8,
        section[5] | 1, // keep the version, force current_next_indicator
        0,              // section_number
        0,              // last_section_number
        section[8],
        section[9],
        section[10],
        section[11],
        0,    // segment_last_section_number
        last, // last_table_id
    ];
    let crc = crc32(&s);
    s.extend_from_slice(&crc.to_be_bytes());
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
/// Packetize a PES into TS packets, stuffing the final packet with an
/// adaptation field. Used for rewritten captions.
fn packetize(data: &[u8], id: u16, counter: &mut u8) -> Vec<[u8; 188]> {
    data.chunks(184)
        .enumerate()
        .map(|(i, chunk)| {
            let mut p = [0xff; 188];
            p[..4].copy_from_slice(&[
                0x47,
                (id >> 8) as u8 | if i == 0 { 0x40 } else { 0 },
                id as u8,
                0x10 | *counter,
            ]);
            if chunk.len() < 184 {
                p[3] |= 0x20;
                p[4] = (183 - chunk.len()) as u8;
                if p[4] > 0 {
                    p[5] = 0;
                }
            }
            p[188 - chunk.len()..].copy_from_slice(chunk);
            *counter = (*counter + 1) % 16;
            p
        })
        .collect()
}
/// CRC-16/CCITT (poly 0x1021, init 0) used by ARIB caption data groups.
fn crc16(data: &[u8]) -> u16 {
    let mut c = 0u16;
    for &b in data {
        c ^= (b as u16) << 8;
        for _ in 0..8 {
            c = if c & 0x8000 != 0 {
                (c << 1) ^ 0x1021
            } else {
                c << 1
            };
        }
    }
    c
}
/// Insert the "designate G2 as Kanji" escape (ESC 0x24 0x2A 0x42) at the start
/// of every caption statement data unit in a statement data group.
///
/// One-seg captions are ARIB STD-B24 Profile C, whose default G2 set is Kanji,
/// so the text is transmitted in the GR area without an explicit designation.
/// Profile A defaults G2 to Hiragana, so a Profile A decoder reads the two-byte
/// kanji codes as one-byte hiragana. Making the designation explicit lets both
/// profiles decode the text correctly.
fn caption_designate(gdata: &mut Vec<u8>, group_id: u8) -> Option<usize> {
    // Caption management data groups (low nibble 0) carry no statement text.
    if group_id & 0x0f == 0 {
        return Some(0);
    }
    if gdata.len() < 4 {
        return None;
    }
    let tmd = gdata[0] >> 6;
    let mut pos = 1;
    if tmd == 0b01 || tmd == 0b10 {
        pos += 5; // STM (start time)
    }
    if pos + 3 > gdata.len() {
        return None;
    }
    let loop_len =
        ((gdata[pos] as usize) << 16) | ((gdata[pos + 1] as usize) << 8) | gdata[pos + 2] as usize;
    let loop_end = pos + 3 + loop_len;
    if loop_end > gdata.len() {
        return None;
    }
    let mut units = Vec::with_capacity(loop_len + 4);
    let mut p = pos + 3;
    let mut added = 0usize;
    while p < loop_end {
        if p + 5 > loop_end || gdata[p] != 0x1f {
            return None;
        }
        let size = ((gdata[p + 2] as usize) << 16)
            | ((gdata[p + 3] as usize) << 8)
            | gdata[p + 4] as usize;
        let data_end = p + 5 + size;
        if data_end > loop_end {
            return None;
        }
        if gdata[p + 1] == 0x20 {
            // ESC 0x24 0x2A 0x42 designates G2 as Kanji. `CS` (0x0C, clear
            // screen) resets the graphic sets, so re-designate after it too.
            let data = &gdata[p + 5..data_end];
            let mut body = Vec::with_capacity(data.len() + 4);
            body.extend_from_slice(&[0x1b, 0x24, 0x2a, 0x42]);
            let mut count = 1usize;
            for &b in data {
                body.push(b);
                if b == 0x0c {
                    body.extend_from_slice(&[0x1b, 0x24, 0x2a, 0x42]);
                    count += 1;
                }
            }
            let new_size = body.len();
            if new_size > 0xffffff {
                return None;
            }
            units.extend_from_slice(&[
                gdata[p],
                gdata[p + 1],
                (new_size >> 16) as u8,
                (new_size >> 8) as u8,
                new_size as u8,
            ]);
            units.extend_from_slice(&body);
            let delta = count * 4;
            added += delta;
        } else {
            units.extend_from_slice(&gdata[p..data_end]);
        }
        p = data_end;
    }
    let new_loop_len = loop_len + added;
    if new_loop_len > 0xffffff {
        return None;
    }
    let mut out = Vec::with_capacity(gdata.len() + added);
    out.extend_from_slice(&gdata[..pos]);
    out.extend_from_slice(&[
        (new_loop_len >> 16) as u8,
        (new_loop_len >> 8) as u8,
        new_loop_len as u8,
    ]);
    out.extend_from_slice(&units);
    out.extend_from_slice(&gdata[loop_end..]);
    *gdata = out;
    Some(added)
}
/// Convert a one-seg (Profile C) caption PES to a form any decoder accepts.
///
/// The escape that re-designates G2 as Kanji is inserted into every statement
/// data unit and all length fields (data unit, data group, PES) and the ARIB
/// CRC-16 are refreshed. PES packets with an unexpected layout pass through.
fn konomitv_caption(pes: &[u8]) -> Option<Vec<u8>> {
    if pes.len() < 9 || pes[..3] != [0x00, 0x00, 0x01] || pes[3] != 0xbd {
        return None;
    }
    let payload = 9 + pes[8] as usize;
    if payload + 3 > pes.len() || pes[payload] != 0x80 || pes[payload + 1] != 0xff {
        return None;
    }
    let mut pos = payload + 3 + (pes[payload + 2] & 0x0f) as usize;
    if pos > pes.len() {
        return None;
    }
    let declared = u16::from_be_bytes([pes[4], pes[5]]) as usize;
    let end = if declared == 0 {
        pes.len()
    } else {
        (6 + declared).min(pes.len())
    };
    let mut out = pes[..pos].to_vec();
    let mut added_total = 0usize;
    while pos + 7 <= end {
        let size = u16::from_be_bytes([pes[pos + 3], pes[pos + 4]]) as usize;
        let group_end = pos + 5 + size;
        if group_end + 2 > end {
            return None;
        }
        let mut gdata = pes[pos + 5..group_end].to_vec();
        let added = caption_designate(&mut gdata, pes[pos] >> 2)?;
        let new_size = size + added;
        if new_size > 0xffff {
            return None;
        }
        out.extend_from_slice(&[
            pes[pos],
            pes[pos + 1],
            pes[pos + 2],
            (new_size >> 8) as u8,
            new_size as u8,
        ]);
        out.extend_from_slice(&gdata);
        let start = out.len() - 5 - gdata.len();
        let crc = crc16(&out[start..]);
        out.extend_from_slice(&crc.to_be_bytes());
        added_total += added;
        pos = group_end + 2;
    }
    if added_total == 0 {
        return None;
    }
    // Preserve any trailing bytes after the last data group.
    if pos < end {
        out.extend_from_slice(&pes[pos..end]);
    }
    if declared != 0 {
        let new_len = declared + added_total;
        if new_len > 0xffff {
            return None;
        }
        out[4..6].copy_from_slice(&(new_len as u16).to_be_bytes());
    }
    Some(out)
}
/// Rewrite the caption data component descriptor's data_component_id from
/// Profile C (0x0012) to Profile A (0x0008) so full-segment-only decoders
/// accept the converted caption. Other PMT sections pass through unchanged.
fn konomitv_pmt(section: &[u8]) -> Vec<u8> {
    let mut s = section.to_vec();
    if s.len() < 16 || s[0] != 0x02 {
        return s;
    }
    let end = s.len() - 4;
    let mut offset = 12 + ((s[10] as usize & 0x0f) << 8) + s[11] as usize;
    let mut changed = false;
    while offset + 5 <= end {
        let mut j = offset + 5;
        let stop = j + ((s[offset + 3] as usize & 0x0f) << 8) + s[offset + 4] as usize;
        if stop > end {
            break;
        }
        while j + 2 <= stop {
            let len = s[j + 1] as usize;
            if j + 2 + len > stop {
                break;
            }
            if s[j] == 0xfd && len >= 2 && s[j + 2] == 0x00 && s[j + 3] == 0x12 {
                s[j + 3] = 0x08;
                changed = true;
            }
            j += 2 + len;
        }
        offset = stop;
    }
    if changed {
        let crc = crc32(&s[..end]);
        s[end..].copy_from_slice(&crc.to_be_bytes());
    }
    s
}
/// PID of the one-seg (Profile C) caption elementary stream in a PMT.
fn caption_pid(section: &[u8]) -> Option<u16> {
    if section.len() < 16 || section[0] != 0x02 {
        return None;
    }
    let end = section.len() - 4;
    let mut offset = 12 + ((section[10] as usize & 0x0f) << 8) + section[11] as usize;
    while offset + 5 <= end {
        let mut j = offset + 5;
        let stop = j + ((section[offset + 3] as usize & 0x0f) << 8) + section[offset + 4] as usize;
        if stop > end {
            break;
        }
        if section[offset] == 0x06 {
            while j + 2 <= stop {
                let len = section[j + 1] as usize;
                if j + 2 + len > stop {
                    break;
                }
                if section[j] == 0xfd
                    && len >= 2
                    && section[j + 2] == 0x00
                    && section[j + 3] == 0x12
                {
                    return Some(
                        ((section[offset + 1] as u16 & 0x1f) << 8) | section[offset + 2] as u16,
                    );
                }
                j += 2 + len;
            }
        }
        offset = stop;
    }
    None
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
    pmt_counter: u8,
    services: BTreeSet<u16>,
    caption_pid: Option<u16>,
    caption_pes: Vec<u8>,
    caption_counter: u8,
    strip: bool,
    konomitv: bool,
    pub written: u64,
}
impl Transport {
    pub fn new(selection: Selection, strip: bool, konomitv: bool) -> Self {
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
            pmt_counter: 0,
            services: BTreeSet::new(),
            caption_pid: None,
            caption_pes: Vec::new(),
            caption_counter: 0,
            strip,
            konomitv,
            written: 0,
        }
    }
    pub fn feed(&mut self, p: [u8; 188]) -> Vec<[u8; 188]> {
        if p[0] != 0x47 || p[1] & 0x80 != 0 {
            return vec![];
        }
        let id = pid(&p);
        let mut sdt = vec![];
        let mut pmt = vec![];
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
                    if self.konomitv {
                        self.services.extend(sdt_services(&s));
                    }
                }
                if self.konomitv {
                    sdt.push(s);
                }
            }
        }
        if (0x1fc8..=0x1fcf).contains(&id) {
            for s in self.sections.feed(&p) {
                if s[0] != 2 || s.len() < 16 || s[5] & 1 == 0 {
                    continue;
                }
                if self.konomitv {
                    // Remember the Profile C caption PID and present the caption
                    // descriptor as Profile A to full-segment-only decoders.
                    if let Some(pid) = caption_pid(&s) {
                        self.caption_pid = Some(pid);
                    }
                    pmt.push(konomitv_pmt(&s));
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
        if id == 0x11 && self.konomitv {
            // Rewrite the service_type of each SDT service to digital TV so
            // Mirakurun reports the one-seg service as full-seg (type=0x01).
            for section in &sdt {
                emit_section(
                    &konomitv_sdt(section),
                    0x11,
                    &mut self.sdt_counter,
                    &mut out,
                );
            }
        } else if (0x1fc8..=0x1fcf).contains(&id) && self.konomitv {
            // Replace the raw PMT with the rewritten one so the caption
            // descriptor advertises Profile A (full-seg).
            for section in &pmt {
                emit_section(section, id, &mut self.pmt_counter, &mut out);
            }
        } else if self.konomitv && Some(id) == self.caption_pid {
            self.feed_caption(&p, &mut out);
        } else if id != 0x12 {
            out.push(p);
        }
        if matches!(id, 0x12 | 0x27) {
            // Mirakurun parses EIT on PID 0x12, not the one-seg PID 0x27.
            // Merge complete sections so native EIT and mirrored L-EIT cannot
            // interleave partial sections or clash in continuity counters.
            for s in self.sections.feed(&p) {
                let one_seg = id == 0x27;
                // Fill in the audio metadata the one-seg L-EIT omits so
                // Mirakurun reports `audios` for the mirrored program.
                let s = if one_seg && self.konomitv {
                    konomitv_eit(&s)
                } else {
                    s
                };
                emit_section(&s, 0x12, &mut self.eit_counter, &mut out);
                // Wait for the SDT so every service is known before readiness
                // is declared; otherwise Mirakurun could finish gathering
                // after the first service.
                if !(one_seg && self.konomitv) || self.services.is_empty() {
                    continue;
                }
                // Register every known service before declaring any ready, so
                // Mirakurun does not finish gathering after the first one.
                let mut services: BTreeSet<u16> = self.services.clone();
                services.extend(self.programs.keys().copied());
                services.insert(u16::from_be_bytes([s[3], s[4]]));
                for &sid in &services {
                    for table_id in [0x50u8, 0x58] {
                        emit_section(
                            &konomitv_schedule(&s, sid, table_id, 0x5f),
                            0x12,
                            &mut self.eit_counter,
                            &mut out,
                        );
                    }
                }
                for &sid in &services {
                    for table_id in [0x50u8, 0x58] {
                        emit_section(
                            &konomitv_schedule(&s, sid, table_id, table_id),
                            0x12,
                            &mut self.eit_counter,
                            &mut out,
                        );
                    }
                }
            }
        }
        self.written += out.len() as u64;
        out
    }
    fn feed_caption(&mut self, p: &[u8; 188], out: &mut Vec<[u8; 188]>) {
        let data = payload(p);
        if data.is_empty() {
            return;
        }
        if p[1] & 0x40 != 0 {
            // A new PES starts; flush the previous one first.
            self.flush_caption(out);
        }
        self.caption_pes.extend_from_slice(data);
        let complete = self.caption_pes.len() >= 6 && {
            let declared = u16::from_be_bytes([self.caption_pes[4], self.caption_pes[5]]) as usize;
            declared != 0 && self.caption_pes.len() >= 6 + declared
        };
        if complete || self.caption_pes.len() > 6 + u16::MAX as usize {
            self.flush_caption(out);
        }
    }
    fn flush_caption(&mut self, out: &mut Vec<[u8; 188]>) {
        let Some(id) = self.caption_pid else {
            self.caption_pes.clear();
            return;
        };
        if self.caption_pes.is_empty() {
            return;
        }
        let pes = std::mem::take(&mut self.caption_pes);
        let rewritten = konomitv_caption(&pes).unwrap_or(pes);
        out.extend(packetize(&rewritten, id, &mut self.caption_counter));
    }
    pub fn reset(&mut self) {
        self.sections = Sections::default();
        self.programs.clear();
        self.services.clear();
        self.tsid = 1;
        self.count = 0;
        self.version = (self.version + 1) & 31;
        self.caption_pid = None;
        self.caption_pes.clear();
        self.caption_counter = 0;
        self.pmt_counter = 0;
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
    fn konomitv_rewrites_sdt_service_type_to_digital_tv() {
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
        assert_eq!(
            section[18], 0xc0,
            "unmodified without --compatible konomitv"
        );
    }

    #[test]
    fn konomitv_fills_missing_eit_audio_descriptor() {
        // EIT[p/f] for SID 0x7d98 with one event carrying only a short event
        // descriptor and a content descriptor, like a one-seg L-EIT.
        let eit = vec![
            0x4e, 0, 0, 0x7d, 0x98, 0xc1, 0, 0, 0x7e, 0x03, 0x7e, 0x03, 0, 0x4e, 0x1d, 0x3a, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x80, 0x0e, 0x4d, 0x08, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x54, 0x02, 0x00, 0x00,
        ];
        let pmt = psi(0x1fc8, section()[..17].to_vec(), 0);

        let mut t = Transport::new(Selection::All, false, false);
        t.feed(pmt);
        let out = t.feed(psi(0x27, eit.clone(), 0));
        let section = Sections::default()
            .feed(out.iter().find(|p| pid(*p) == 0x12).unwrap())
            .pop()
            .unwrap();
        assert!(
            !section.contains(&0xc4),
            "unmodified without --compatible konomitv"
        );

        let mut t = Transport::new(Selection::All, false, true);
        t.feed(pmt);
        let out = t.feed(psi(0x27, eit, 0));
        let section = Sections::default()
            .feed(out.iter().find(|p| pid(*p) == 0x12).unwrap())
            .pop()
            .unwrap();
        assert_eq!(crc32(&section), 0);
        let end = section.len() - 4;
        let dlen = ((section[24] as usize & 15) << 8) + section[25] as usize;
        assert_eq!(26 + dlen, end, "event descriptor loop must end at the CRC");
        let audio = section[26..26 + dlen]
            .windows(11)
            .find(|w| w[0] == 0xc4 && w[1] == 0x09)
            .expect("synthesized audio component descriptor");
        assert_eq!(
            audio,
            &[
                0xc4, 0x09, 0xf2, 0x03, 0x01, 0x0f, 0xff, 0x4f, 0x6a, 0x70, 0x6e
            ][..]
        );
    }

    fn sdt_with_services(tsid: u16, onid: u16, sids: &[u16]) -> [u8; 188] {
        let mut s = vec![0x42, 0, 0];
        s.extend(tsid.to_be_bytes());
        s.push(0xc1);
        s.push(0);
        s.push(0);
        s.extend(onid.to_be_bytes());
        s.push(0xff);
        for sid in sids {
            s.extend(sid.to_be_bytes());
            s.extend([0xfc, 0x00, 0x00]);
        }
        psi(0x11, s, 0)
    }

    fn eit_sections(output: &[[u8; 188]]) -> Vec<Vec<u8>> {
        let mut parser = Sections::default();
        output
            .iter()
            .filter(|p| pid(*p) == 0x12)
            .flat_map(|p| parser.feed(p))
            .collect()
    }

    #[test]
    fn konomitv_emits_empty_eit_schedule_for_mirakurun() {
        let eit = vec![
            0x4e, 0, 0, 0x7d, 0x98, 0xc1, 0, 0, 0x7e, 0x03, 0x7e, 0x03, 0, 0x4e, 0x1d, 0x3a, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x80, 0x0e, 0x4d, 0x08, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x54, 0x02, 0x00, 0x00,
        ];
        let pmt = psi(0x1fc8, section()[..17].to_vec(), 0);
        let sdt = sdt_with_services(0x7e03, 0x7e03, &[0x7d98, 0x7da0]);

        let mut t = Transport::new(Selection::All, false, false);
        t.feed(pmt);
        t.feed(sdt);
        let sections = eit_sections(&t.feed(psi(0x27, eit.clone(), 0)));
        assert!(sections.iter().all(|s| s[0] != 0x50 && s[0] != 0x58));

        let mut t = Transport::new(Selection::All, false, true);
        t.feed(pmt);
        t.feed(sdt);
        let sections = eit_sections(&t.feed(psi(0x27, eit, 0)));
        for sid in [0x7d98u16, 0x7da0] {
            for table_id in [0x50u8, 0x58] {
                for last in [0x5fu8, table_id] {
                    let s = sections
                        .iter()
                        .find(|s| {
                            s[0] == table_id
                                && s[13] == last
                                && u16::from_be_bytes([s[3], s[4]]) == sid
                        })
                        .unwrap_or_else(|| {
                            panic!("missing schedule table {table_id:#x}/{last:#x} for {sid:#x}")
                        });
                    assert_eq!(crc32(s), 0);
                    assert_eq!(s.len(), 18, "schedule sections carry no events");
                    assert_eq!(s[1] & 0xf0, 0xb0);
                    assert_eq!(s[5] & 1, 1, "current_next_indicator");
                    assert_eq!(s[6], 0, "section_number");
                    assert_eq!(s[7], 0, "last_section_number");
                    assert_eq!(&s[8..12], &[0x7e, 0x03, 0x7e, 0x03]);
                    assert_eq!(s[12], 0, "segment_last_section_number");
                }
            }
        }
    }

    // Real one-seg caption PES (Profile C) captured from a broadcast.
    fn caption_pes() -> Vec<u8> {
        vec![
            0x00, 0x00, 0x01, 0xbd, 0x00, 0x44, 0x80, 0x81, 0x17, 0x21, 0x0e, 0x25, 0x90, 0x0d,
            0x8e, 0x43, 0x43, 0x49, 0x53, 0x04, 0xbf, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
            0xff, 0xff, 0xff, 0xff, 0x80, 0xff, 0xf0, 0x04, 0x00, 0x00, 0x00, 0x20, 0x3f, 0x00,
            0x00, 0x1c, 0x1f, 0x20, 0x00, 0x00, 0x17, 0x0c, 0x83, 0x8a, 0xa3, 0xb3, 0xa4, 0xc4,
            0xa4, 0xce, 0xa5, 0xd5, 0xa5, 0xed, 0xa5, 0xa2, 0xa4, 0xab, 0xa4, 0xe9, 0xa4, 0xca,
            0xa4, 0xea, 0x04, 0x77,
        ]
    }

    // PMT carrying a Profile C (one-seg) caption as data_component_id 0x0012.
    fn caption_pmt() -> [u8; 188] {
        psi(
            0x1fc8,
            vec![
                0x02, 0, 0, 0x7d, 0x98, 0xc1, 0, 0, 0xe1, 0x50, 0xf0, 0, 0x06, 0xe1, 0x54, 0xf0,
                0x05, 0xfd, 0x03, 0x00, 0x12, 0xad,
            ],
            0,
        )
    }

    #[test]
    fn konomitv_converts_profile_c_caption_pes() {
        let pes = caption_pes();
        assert_eq!(pes.len(), 74);
        // Original group CRC-16 (verified against the wire data).
        assert_eq!(crc16(&pes[35..72]).to_be_bytes(), pes[72..74]);
        let out = konomitv_caption(&pes).expect("conversion");
        assert_eq!(out.len(), 82);
        // PES_packet_length, data_group_size and data_unit_size all grow by 8.
        assert_eq!(u16::from_be_bytes([out[4], out[5]]), 0x4c);
        assert_eq!(u16::from_be_bytes([out[38], out[39]]), 0x28);
        assert_eq!(&out[46..49], &[0x00, 0x00, 0x1f]);
        // ESC 0x24 0x2A 0x42 (designate G2 as Kanji) precedes the statement...
        assert_eq!(&out[49..53], &[0x1b, 0x24, 0x2a, 0x42]);
        // ...and is repeated after the CS (clear screen) that resets the sets.
        assert_eq!(out[53], 0x0c);
        assert_eq!(&out[54..58], &[0x1b, 0x24, 0x2a, 0x42]);
        assert_eq!(&out[58..80], &pes[50..72]);
        // The rewritten group CRC-16 is refreshed.
        assert_eq!(crc16(&out[35..80]).to_be_bytes(), out[80..82]);
    }

    #[test]
    fn konomitv_converts_caption_only_when_enabled() {
        let pes = caption_pes();
        for konomitv in [false, true] {
            let mut cc = 0;
            let packets = packetize(&pes, 0x154, &mut cc);
            let mut t = Transport::new(Selection::All, false, konomitv);
            t.feed(caption_pmt());
            let mut out = vec![];
            for p in packets {
                out.extend(t.feed(p));
            }
            let data = out
                .iter()
                .find(|p| pid(*p) == 0x154)
                .map(|p| payload(p).to_vec())
                .expect("caption output");
            if konomitv {
                assert_eq!(&data[49..53], &[0x1b, 0x24, 0x2a, 0x42]);
            } else {
                assert!(data.starts_with(&[0x00, 0x00, 0x01, 0xbd]));
                assert_eq!(&data[49..53], &pes[49..53]);
            }
        }
    }

    #[test]
    fn konomitv_rewrites_caption_descriptor_to_profile_a() {
        let section = |konomitv| {
            let mut t = Transport::new(Selection::All, false, konomitv);
            let out = t.feed(caption_pmt());
            Sections::default()
                .feed(out.iter().find(|p| pid(*p) == 0x1fc8).unwrap())
                .pop()
                .unwrap()
        };
        let original = section(false);
        assert_eq!(&original[19..21], &[0x00, 0x12]);
        assert_eq!(crc32(&original), 0);
        let converted = section(true);
        assert_eq!(crc32(&converted), 0);
        assert_eq!(&converted[19..21], &[0x00, 0x08]);
    }
}
