# recrtl

**recrtl** is a Rust command-line recorder for Japanese terrestrial digital TV
(ISDB-T) one-segment broadcasts using an RTL-SDR. It tunes a physical UHF
channel, demodulates the one-segment (Layer A) signal, and writes an MPEG-TS
stream to a file or stdout.

The receive chain is written entirely in Rust. Python, GNU Radio, and gr-isdbt
are not required. `librtlsdr` is loaded at runtime only to drive the USB
receiver; replaying a saved IQ capture does not need `librtlsdr` at all.
recrtl currently targets Linux.

**日本語のREADMEは [README.ja.md](README.ja.md) です。**

## Features

- Records ISDB-T one-segment video and audio as a standard 188-byte MPEG-TS.
- Uses a recdvb-compatible CLI: `recrtl [OPTIONS] CHANNEL RECTIME DESTFILE`.
- Works with a live RTL-SDR device or with a saved 2.048 MS/s IQ capture.
- Selects services by SID, by ordinal, or by the recdvb aliases (`hd`, `sd1`,
  `1seg`, `epg`, ...).
- Can drop null packets and can trim incomplete H.264/AAC edges of a recording.
- Provides Mirakurun/EPG integration workarounds for one-seg streams
  (`--compatible konomitv`).
- Requires no hardware for `--list`, `--list-devices`, `--list-regions`, and
  `--list-channels`.

## Requirements

- **OS:** Linux (verified on Debian, Ubuntu, and Raspberry Pi OS).
- **Toolchain:** Rust 1.98.1 or later.
- **Hardware:** an RTL-SDR-compatible receiver for live reception. A saved IQ
  file can be used instead for offline decoding.
- **Optional:** `ffmpeg` (including `ffplay` and `ffprobe`) for playback and the
  real-IQ acceptance test.

Only ISDB-T **Mode 3, GI 1/8, QPSK, one segment** is supported. BS/CS and
full-segment reception are out of scope. See
[docs/architecture.md](docs/architecture.md) for the supported parameter ranges.

## Installation

### 1. Install dependencies

On apt-based distributions (Debian, Ubuntu, Raspberry Pi OS):

```sh
sudo apt update
# Build tools and the tools used to install Rust
sudo apt install build-essential curl ca-certificates
# Live-reception library, udev rules, and the rtl_test utility
sudo apt install rtl-sdr
```

Installing `rtl-sdr` pulls in the matching `librtlsdr`. If you only replay saved
IQ files, `rtl-sdr` is not required. Rust crates are fetched by Cargo at build
time.

If Rust/Cargo is not installed, use the
[official rustup instructions](https://doc.rust-lang.org/book/ch01-01-installation.html):

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
```

For playback and the real-IQ acceptance test, install `ffmpeg` as well. It is
not needed for recording.

```sh
sudo apt install ffmpeg
```

### 2. Build and install

```sh
cargo build --release --locked
cargo install --path . --locked
```

### 3. Grant access to the USB device

To receive with an unprivileged user, that user needs access to the USB device.
The udev rules shipped with the Debian/Ubuntu `rtl-sdr` package grant access to
supported devices to the `plugdev` group (see the
[package notes](https://github.com/osmocom/rtl-sdr/blob/master/debian/README.Debian)).
Run the following as the user that will receive:

```sh
sudo groupadd -f plugdev
sudo usermod -aG plugdev "$(id -un)"
sudo udevadm control --reload-rules
```

Then **log out and back in** (reconnect if you are on SSH) and unplug/replug the
RTL-SDR. Confirm that `id -nG` lists `plugdev`, and check the connection without
`sudo`:

```sh
id -nG
rtl_test -s 2048000
# After confirming samples are read, stop with Ctrl+C
recrtl --list-devices
```

Stop `rtl_test` before starting `recrtl`; a receiver cannot be shared.
`recrtl --list-devices` only enumerates devices, so use `rtl_test` to confirm
that a device can actually be opened.

If permission errors persist, check that
`60-librtlsdr*.rules` under `/usr/lib/udev/rules.d/` or `/lib/udev/rules.d/`
contains the USB ID of your receiver.

If the device cannot be opened with `Kernel driver is active`, close any other
receiver software and check for a conflict with the DVB kernel driver. Only if
there is a conflict, add the following and reboot. This setting also affects DVB
reception by other devices that use the same driver.

```sh
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/recrtl-rtl-sdr.conf
sudo reboot
```

## Quickstart

```sh
# Record physical channel 19 for 60 seconds
recrtl --dev 0 --gain 38.6 19 60 recording.ts

# Record until stopped and stream the TS to stdout
recrtl 19 - - > recording.ts

# Pipe the live stream into a player
recrtl 19 - - | ffplay -i pipe:0
```

## Usage

```text
recrtl [OPTIONS] CHANNEL RECTIME DESTFILE
```

### Arguments

- `CHANNEL`: UHF physical channel, 13..62. BS/CS and full-segment are not
  received.
- `RECTIME`: seconds, `H:M`, `H:M:S`, `1h30m`, `1h2m3s`, or `-` for unlimited.
  As in recdvb, `1:30` means 1 hour 30 minutes. With a live device the timer
  starts when reception begins.
- `DESTFILE`: a new file, or `-` for stdout. Overwriting an existing file is an
  error.

### Options

- `--dev N` / `-d N`: RTL-SDR device index (default `0`).
- `--sid LIST` / `-i LIST`: comma-separated service IDs, `all` (default), `hd` /
  `sd1`, `sd2`, `sd3`, `1seg`, `epg`, `epg1seg`. Numeric IDs and aliases can be
  mixed. `1seg` selects the program whose PMT PID is `0x1fc8`. If none of the
  requested SIDs exist, no TS is emitted and a timed or file-ended recording
  fails.
- `--strip` / `-s`: remove null packets.
- `--compatible CLIENT`: enable client-specific compatibility workarounds.
  Currently only `konomitv` is accepted. The video and audio stay one-segment,
  but the service is presented to Mirakurun as a full-segment digital TV
  service. The `service_type` in the SDT service descriptor is rewritten to
  `0x01` (digital TV) and the CRC is recomputed, so Mirakurun's
  `/api/services` reports `type` as `1` instead of `0xC0`. The service ID (SID)
  is not changed. In addition, the audio component descriptor (`0xC4`) that the
  one-seg L-EIT lacks is added to every event, so Mirakurun exposes `audios` in
  its program information (fixed AAC stereo, 48 kHz, Japanese). This avoids the
  problem where KonomiTV cannot ingest program information that lacks audio
  metadata. Empty EIT schedule sections (`0x50`..`0x5F`), which one-seg never
  broadcasts, are also synthesized so Mirakurun finishes EPG gathering early
  like it does for full-segment, instead of waiting for the retrieval timeout
  (program information is still limited to current/next).
- `--help` / `-h`, `--version` / `-v`, `--list` / `-l`: help, version, and the
  physical channel list.

### Diagnostics and receiver options

- `--list-devices`: list attached RTL-SDR receivers.
- `--list-regions`: list the prefecture codes in the bundled station database.
- `--list-channels PREFECTURE`: list the stations preserved for a prefecture.
- `--iq-file PATH`: decode a saved unsigned 8-bit interleaved IQ file at
  2.048 MS/s (no hardware needed).
- `--trim`: for IQ files only, drop incomplete H.264/AAC frames and the video
  before the first SPS/PPS/IDR. Buffers the whole TS until EOF; no re-encoding.
- `--gain DB`: fixed tuner gain (automatic when omitted).
- `--frequency MHz`: override the center frequency.
- `--ppm N`: tuner frequency correction.
- `--verbose`: print receiver statistics on stderr.

### Output and exit behavior

Diagnostics other than TS are written to stderr. The recorder can be stopped
with SIGINT or SIGTERM, even if the output pipe is blocked. If the reader of the
pipe exits, recrtl exits successfully.

During live reception, up to 4 MiB of unsent TS is buffered so that IQ reception
and decoding continue even if the player pauses reading. When reading resumes,
the buffered TS is sent in order. If the limit is reached, recrtl exits with
`TS output stalled`. Saved-IQ playback follows the reader's pace.

B25, LNB control, and HTTP/UDP streaming options are out of scope; specifying
them results in an error.

### Service selection

```sh
# Select a SID
recrtl --sid 32152 19 1h30m recording.ts

# Mix a SID and the one-seg EPG
recrtl --sid 32152,epg1seg 19 - - > recording.ts
```

### IQ replay and verification

```sh
# Decode a saved 2.048 MS/s unsigned 8-bit interleaved I,Q capture
recrtl --iq-file capture.u8iq 19 - recording.ts

# Trim a finite IQ recording for strict video/audio verification
recrtl --iq-file capture.u8iq --trim 19 - trimmed.ts
ffmpeg -v error -xerror -i trimmed.ts -map 0:v:0 -map 0:a:0 -f null -
```

With a saved IQ file, `RECTIME` is converted into a number of input samples and
no real-time waiting occurs. `-` processes until the end of the file. In
practice, prepare at least 5 to 10 seconds of IQ data.

## Integration

recrtl can be used as a tuner command behind a Mirakurun-compatible server, and
its one-seg output can be adapted for KonomiTV. See the integration guides:

- [Mirakurun](docs/mirakurun.md)
- [mirakc](docs/mirakc.md)
- [KonomiTV](docs/konomitv.md)

## Development

Run the standard checks:

```sh
cargo test --locked
cargo fmt --check
cargo clippy --all-targets -- -D warnings
```

The regular tests run without a receiver, Python, or GNU Radio. The opt-in
acceptance test uses a real IQ capture and requires `ffmpeg` and `ffprobe`:

```sh
RECRTL_TEST_IQ=/path/to/capture.u8iq \
  cargo test --release --test recorded -- --ignored --nocapture
```

See [docs/architecture.md](docs/architecture.md) for what each test layer
verifies and for the receiver internals.

## Documentation

The files under `docs/` are written in Japanese.

- [docs/architecture.md](docs/architecture.md): supported modes, the DSP/FEC
  pipeline, TS handling, Mirakurun compatibility, and the station database.
- [docs/mirakurun.md](docs/mirakurun.md): using recrtl with Mirakurun.
- [docs/mirakc.md](docs/mirakc.md): using recrtl with mirakc.
- [docs/konomitv.md](docs/konomitv.md): using recrtl with KonomiTV.
- [README.ja.md](README.ja.md): Japanese README.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for reference
material and attribution.
