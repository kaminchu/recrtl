//! Optional finite-recording edge trimming. Payloads and timestamps are preserved.
use crate::ts::{Sections, payload, pid};
use anyhow::{Result, ensure};
use std::collections::{BTreeMap, BTreeSet};
type Packet = [u8; 188];
fn streams(packets: &[Packet]) -> BTreeMap<u16, u8> {
    let mut sections = Sections::default();
    let mut streams = BTreeMap::new();
    for p in packets {
        if !(0x1fc8..=0x1fcf).contains(&pid(p)) {
            continue;
        }
        for s in sections.feed(p) {
            if s[0] != 2 || s.len() < 16 {
                continue;
            }
            let mut offset = 12 + ((s[10] as usize & 15) << 8) + s[11] as usize;
            while offset + 5 <= s.len() - 4 {
                let kind = s[offset];
                let id = ((s[offset + 1] as u16 & 31) << 8) | s[offset + 2] as u16;
                if matches!(kind, 0x1b | 0x0f | 0x11) {
                    streams.insert(id, kind);
                }
                offset += 5 + ((s[offset + 3] as usize & 15) << 8) + s[offset + 4] as usize;
            }
        }
    }
    streams
}
fn pes(packets: &[Packet], indices: &[usize]) -> Vec<u8> {
    indices
        .iter()
        .flat_map(|&i| payload(&packets[i]).iter().copied())
        .collect()
}
fn complete(data: &[u8], followed: bool) -> bool {
    if data.len() < 9 || data[..3] != [0, 0, 1] || 9 + data[8] as usize > data.len() {
        return false;
    }
    let size = u16::from_be_bytes([data[4], data[5]]) as usize;
    if size == 0 {
        followed
    } else {
        data.len() >= size + 6
    }
}
fn keyframe(data: &[u8]) -> bool {
    let kinds: BTreeSet<_> = data
        .windows(4)
        .filter(|p| p[..3] == [0, 0, 1])
        .map(|p| p[3] & 31)
        .collect();
    [5, 7, 8].iter().all(|k| kinds.contains(k))
}
pub fn packetize(data: &[u8], id: u16, counter: &mut u8) -> Vec<Packet> {
    data.chunks(184)
        .enumerate()
        .map(|(i, data)| {
            let mut p = [0xff; 188];
            p[..4].copy_from_slice(&[
                0x47,
                (id >> 8) as u8 | if i == 0 { 0x40 } else { 0 },
                id as u8,
                0x10 | *counter,
            ]);
            if data.len() < 184 {
                p[3] |= 0x20;
                p[4] = (183 - data.len()) as u8;
                if p[4] > 0 {
                    p[5] = 0;
                }
            }
            p[188 - data.len()..].copy_from_slice(data);
            *counter = (*counter + 1) % 16;
            p
        })
        .collect()
}
pub fn adts_length(data: &[u8], i: usize) -> Option<usize> {
    if i + 7 > data.len()
        || data[i] != 0xff
        || data[i + 1] & 0xf6 != 0xf0
        || ((data[i + 2] >> 2) & 15) >= 13
    {
        return None;
    }
    let size = ((data[i + 3] as usize & 3) << 11)
        | ((data[i + 4] as usize) << 3)
        | (data[i + 5] as usize >> 5);
    (size >= if data[i + 1] & 1 != 0 { 7 } else { 9 }).then_some(size)
}
pub fn trim(data: &[u8]) -> Result<Vec<u8>> {
    ensure!(
        !data.is_empty() && data.len().is_multiple_of(188),
        "invalid TS length"
    );
    let packets: Vec<Packet> = data.as_chunks::<188>().0.to_vec();
    ensure!(
        packets.iter().all(|p| p[0] == 0x47 && p[1] & 0x80 == 0),
        "invalid TS packet"
    );
    let types = streams(&packets);
    let mut keep = vec![true; packets.len()];
    for (&id, &kind) in &types {
        let mut groups: Vec<Vec<usize>> = vec![];
        for (i, p) in packets.iter().enumerate() {
            if pid(p) != id {
                continue;
            }
            keep[i] = false;
            if p[1] & 0x40 != 0 {
                groups.push(vec![]);
            }
            if let Some(g) = groups.last_mut() {
                g.push(i);
            }
        }
        let mut started = kind != 0x1b;
        for (n, g) in groups.iter().enumerate() {
            let data = pes(&packets, g);
            if !complete(&data, n + 1 < groups.len()) {
                continue;
            }
            if !started {
                started = keyframe(&data[9 + data[8] as usize..]);
            }
            if started {
                for &i in g {
                    keep[i] = true;
                }
            }
        }
        ensure!(
            started,
            "no complete SPS/PPS/IDR in recording; capture longer"
        );
    }
    let packets: Vec<_> = packets
        .into_iter()
        .zip(keep)
        .filter_map(|(p, keep)| keep.then_some(p))
        .collect();
    let mut removed: BTreeSet<usize> = BTreeSet::new();
    let mut replacements = BTreeMap::new();
    for (&id, &kind) in &types {
        if kind != 0x0f {
            continue;
        }
        let mut groups: Vec<Vec<usize>> = vec![];
        let mut last_cc = None;
        for (i, p) in packets.iter().enumerate() {
            if pid(p) != id {
                continue;
            }
            ensure!(
                p[3] & 0x20 == 0 || p[4] == 0 || p[5] & 0x10 == 0,
                "AAC PID containing PCR cannot be trimmed"
            );
            if p[3] & 0x10 != 0 {
                let cc = p[3] & 15;
                if let Some(old) = last_cc {
                    ensure!(
                        cc == (old + 1) % 16,
                        "missing or duplicate AAC packet within recording"
                    );
                }
                last_cc = Some(cc);
            }
            if p[1] & 0x40 != 0 {
                groups.push(vec![]);
            }
            if let Some(g) = groups.last_mut() {
                g.push(i);
            }
        }
        if groups.is_empty() {
            continue;
        }
        let payloads: Vec<_> = groups.iter().map(|g| pes(&packets, g)).collect();
        let elementary: Vec<_> = payloads
            .iter()
            .flat_map(|p| p[9 + p[8] as usize..].iter().copied())
            .collect();
        let start = (0..elementary.len())
            .find(|&i| {
                adts_length(&elementary, i)
                    .and_then(|a| {
                        adts_length(&elementary, i + a)
                            .and_then(|b| adts_length(&elementary, i + a + b))
                    })
                    .is_some()
            })
            .ok_or_else(|| anyhow::anyhow!("no consecutive AAC ADTS frames"))?;
        let mut end = start;
        while end + 7 <= elementary.len() {
            let n = adts_length(&elementary, end)
                .ok_or_else(|| anyhow::anyhow!("AAC synchronization lost within recording"))?;
            if end + n > elementary.len() {
                break;
            }
            end += n;
        }
        let mut offset = 0;
        let mut cc = packets[groups[0][0]][3] & 15;
        for (g, p) in groups.iter().zip(payloads) {
            let header = 9 + p[8] as usize;
            let size = p.len() - header;
            let first = start.max(offset);
            let last = end.min(offset + size);
            removed.extend(g);
            if first < last {
                let mut new = p[..header].to_vec();
                new.extend_from_slice(&elementary[first..last]);
                ensure!(new.len() - 6 <= 65535, "AAC PES too large");
                let size = (new.len() - 6) as u16;
                new[4..6].copy_from_slice(&size.to_be_bytes());
                replacements.insert(g[0], packetize(&new, id, &mut cc));
            }
            offset += size;
        }
    }
    let mut out = vec![];
    for (i, p) in packets.iter().enumerate() {
        if let Some(new) = replacements.get(&i) {
            for p in new {
                out.extend(p);
            }
        } else if !removed.contains(&i) {
            out.extend(p);
        }
    }
    Ok(out)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn pmt() -> Packet {
        let mut s = vec![
            2, 0xb0, 23, 0x7d, 0x98, 0xc1, 0, 0, 0xe1, 0x50, 0xf0, 0, 0x1b, 0xe1, 0x51, 0xf0, 0,
            0x0f, 0xe1, 0x52, 0xf0, 0,
        ];
        s.extend(crate::ts::crc32(&s).to_be_bytes());
        let mut p = [0xff; 188];
        p[..5].copy_from_slice(&[0x47, 0x5f, 0xc8, 0x10, 0]);
        p[5..5 + s.len()].copy_from_slice(&s);
        p
    }
    fn make_pes(body: &[u8], video: bool) -> Vec<u8> {
        let mut p = vec![
            0,
            0,
            1,
            if video { 0xe0 } else { 0xc0 },
            0,
            0,
            0x80,
            0x80,
            5,
            0x21,
            0,
            1,
            0,
            1,
        ];
        p.extend(body);
        if !video {
            let n = (p.len() - 6) as u16;
            p[4..6].copy_from_slice(&n.to_be_bytes());
        }
        p
    }
    #[test]
    fn incomplete_video_edges_removed() {
        let mut cc = 0;
        let mut source = pmt().to_vec();
        let good = [
            0, 0, 1, 0x67, 0xaa, 0, 0, 1, 0x68, 0xbb, 0, 0, 1, 0x65, 0xcc,
        ];
        let mut expected = pmt().to_vec();
        for body in [&[0, 0, 1, 0x41, 9][..], &good, &[0, 0, 1, 0x41, 8][..]] {
            let packets = packetize(&make_pes(body, true), 0x151, &mut cc);
            for p in packets {
                source.extend(p);
                if body == good {
                    expected.extend(p);
                }
            }
        }
        assert_eq!(trim(&source).unwrap(), expected);
    }
    #[test]
    fn adts_across_pes_boundaries() {
        // Audio-only PMT for this test.
        let mut p = pmt();
        p[5 + 12] = 0x06;
        let section_len = 26;
        let c = crate::ts::crc32(&p[5..5 + section_len - 4]);
        p[5 + section_len - 4..5 + section_len].copy_from_slice(&c.to_be_bytes());
        let mut source = p.to_vec();
        let mut frame = vec![0xff, 0xf1, 0x58, 0x80, 0x04, 0x1f, 0xfc];
        frame.extend([b'a'; 25]);
        let mut body = b"partial-start".to_vec();
        body.extend(frame.repeat(4));
        body.extend(&frame[..19]);
        let mut cc = 0;
        for b in body.chunks(43) {
            for p in packetize(&make_pes(b, false), 0x152, &mut cc) {
                source.extend(p);
            }
        }
        let output = trim(&source).unwrap();
        let mut rebuilt = vec![];
        for p in output.as_chunks::<188>().0 {
            if pid(p) == 0x152 {
                let data = payload(p);
                assert_eq!(&data[9..14], &[0x21, 0, 1, 0, 1]);
                rebuilt.extend_from_slice(&data[14..]);
            }
        }
        assert_eq!(rebuilt, frame.repeat(4));
    }
}
