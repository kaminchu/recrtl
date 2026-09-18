# recrtl

RTL-SDRで日本の地上デジタル放送のワンセグを受信し、MPEG-TSを記録するRust製コマンドです。
録画CLIはrecdvbの `channel rectime destfile` 形式に合わせています。

受信処理はRustで実装し、Python・GNU Radio・gr-isdbtは不要です。
実機のUSB制御に限り `librtlsdr` を実行時に読み込みます。
保存IQの復号には `librtlsdr` も不要です。現在の実行対象はLinuxです。

## 依存パッケージのインストール

Debian／Ubuntu／Raspberry Pi OSなどのaptを使う環境では、次のように準備します。

```sh
sudo apt update
# ビルド用ツールとRustのインストールに使うツール
sudo apt install build-essential curl ca-certificates
# 実機受信用ライブラリ、udevルール、接続確認用のrtl_test
sudo apt install rtl-sdr
```

`rtl-sdr` の依存関係として、そのOSに対応する `librtlsdr` もインストールされます。
保存IQの復号だけなら `rtl-sdr` は不要です。Rustの依存クレートはビルド時にCargoが取得します。

Rust/Cargoが未導入の場合は、[公式のrustup手順](https://doc.rust-lang.org/book/ch01-01-installation.html)でインストールします。

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
```

再生や実IQの受け入れテストには、追加で `ffmpeg`（`ffplay`・`ffprobe`を含む）をインストールします。
録画だけなら不要です。

```sh
sudo apt install ffmpeg
```

## ビルド

Rust/Cargoでビルドします。検証済みツールチェーンはRust 1.98.1です。

```sh
cargo build --release --locked
cargo install --path . --locked
```

## USBデバイスへのアクセス権

一般ユーザーで実機受信するには、USBデバイスへのアクセス権が必要です。
Debian／Ubuntu系のパッケージに含まれるudevルールは、対応デバイスへのアクセスを
`plugdev` グループに許可します（[パッケージの説明](https://github.com/osmocom/rtl-sdr/blob/master/debian/README.Debian)）。
受信に使うユーザーで次を実行します。

```sh
sudo groupadd -f plugdev
sudo usermod -aG plugdev "$(id -un)"
sudo udevadm control --reload-rules
```

その後、**ログアウトしてログインし直し**（SSHなら再接続）、RTL-SDRをUSBから抜き差しします。
`id -nG` に `plugdev` が含まれることを確認し、`sudo` を付けずに接続を確認します。

```sh
id -nG
rtl_test -s 2048000
# サンプルの読み取りを確認したらCtrl+Cで終了
recrtl --list-devices
```

`rtl_test` を終了してから `recrtl` を起動してください。同じ受信機を同時には使えません。
`recrtl --list-devices` は列挙だけなので、実際に開けるかどうかは `rtl_test` で確認します。

権限エラーが続く場合は、`/usr/lib/udev/rules.d/` または `/lib/udev/rules.d/` の
`60-librtlsdr*.rules` に受信機のUSB IDが含まれているか確認してください。

`Kernel driver is active` などで開けない場合は、他の受信ソフトを終了し、
DVB用カーネルドライバーとの競合を確認します。競合している場合のみ、次の設定を追加して再起動します。
この設定は同じドライバーを使う機器のDVB受信にも影響します。

```sh
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/recrtl-rtl-sdr.conf
sudo reboot
```

## 録画

```sh
recrtl [OPTIONS] CHANNEL RECTIME DESTFILE

# 物理19chを60秒間録画
recrtl --dev 0 --gain 38.6 19 60 recording.ts

# 終了シグナルまで録画し、TSを標準出力へ送る
recrtl 19 - - > recording.ts

# SIDを選択
recrtl --sid 32152 19 1h30m recording.ts

# 標準出力を再生ソフトへ渡す
recrtl 19 - - | ffplay -i pipe:0
```

- `CHANNEL`: UHF物理チャンネル13〜62。BS/CSやフルセグは受信しません。
- `RECTIME`: 秒数、`H:M`、`H:M:S`、`1h30m`、`1h2m3s`、または無期限の `-`。
  recdvbと同じく `1:30` は1時間30分です。実機では受信開始からの経過時間で終了します。
- `DESTFILE`: 新規ファイル、または標準出力の `-`。既存ファイルへの上書きはエラーにします。
- `--dev N` / `-d N`: RTL-SDRのデバイス番号（既定値0）。
- `--sid LIST` / `-i LIST`: SIDのカンマ区切り、`all`（既定値）、`hd` / `sd1`、`sd2`、`sd3`、
  `1seg`、`epg`、`epg1seg`。数値と別名の混在も可能です。
  `1seg` はPMT PID `0x1fc8` の番組を選択します。存在しないSIDではTSを出力せず、
  有期限録画・ファイル終端でエラーにします。
- `--strip` / `-s`: nullパケットを除外。
- `--help` / `-h`、`--version` / `-v`、`--list` / `-l`: ヘルプ、バージョン、物理チャンネル一覧。

TS以外の診断はstderrへ出力します。SIGINT / SIGTERMで停止でき、出力先のパイプが
詰まっていても停止できます。パイプの読み手が終了した場合は正常終了します。
実機受信では、プレーヤーが読み取りを一時停止してもIQの受信・復号を続けるよう、
未送信のTSを最大4 MiB保持します。読み取りが再開すれば順番どおり送信し、
上限に達した場合は `TS output stalled` として終了します。保存IQの再生は読み手の速度に合わせます。
B25、LNB制御、HTTP/UDP配信のオプションは対応範囲外で、指定するとエラーになります。

## 受信確認用オプション

```sh
recrtl --list-devices
recrtl --list-regions
recrtl --list-channels niigata

# 2.048 MS/s unsigned 8-bit I,Q交互の保存データを復号
recrtl --iq-file capture.u8iq 19 - recording.ts

# 有限IQの記録端を整形して、映像・音声の厳密な検証に使う
recrtl --iq-file capture.u8iq --trim 19 - trimmed.ts
ffmpeg -v error -xerror -i trimmed.ts -map 0:v:0 -map 0:a:0 -f null -
```

`--gain DB` は固定ゲイン（省略時は自動）、`--frequency MHz` は中心周波数、
`--ppm N` はチューナーの周波数補正です。
保存IQでは `RECTIME` は入力サンプル数に換算され、実時間での待機はしません。
`-` はファイル終端まで処理します。通常は5〜10秒以上のIQを用意してください。

`--trim` は保存IQ専用で、全TSをメモリに保持してから不完全なPES・AACフレームと
最初のSPS/PPS/IDR以前の映像を除外します。再エンコードはしません。
通常の録画はTSを逐次出力するため、記録端の不完全フレームを含み得ます。

## 受信方式

現在の対応範囲はMode 3、GI 1/8、部分受信Layer A、QPSK、1セグメントです。
TMCCから符号化率1/2・2/3・3/4・5/6・7/8と時間インターリーブ長0・1・2・4を選びます。
他のモード・GI・変調方式は未対応です。

処理経路は以下の通りです。

```text
RTL-SDR / IQ file (2.048 MS/s u8 IQ)
 → 125/252 FIR resampling
 → CP synchronization / frequency and sampling-clock tracking
 → FFT / TMCC parity validation / scattered-pilot equalization
 → frequency and time deinterleaving / QPSK / bit deinterleaving
 → depuncturing / soft-decision Viterbi
 → byte deinterleaving / energy descrambling / RS(204,188)
 → PMT validation / PAT insertion / service filtering
 → 188-byte MPEG-TS
```

同期を失った場合は同期・FEC・番組情報をリセットして再取得します。
無信号や復号失敗からダミーTSは生成しません。
PATは部分受信PMTから生成し、ローカル再生用のtransport_stream_id=1を使用します。
放送局一覧は旧実装のデータを `data/stations.json` に保存したもので、最新の割当を保証するものではありません。

## テスト

```sh
cargo test --locked
cargo fmt --check
cargo clippy --all-targets -- -D warnings

# 実IQを使う受け入れテスト（ffmpegとffprobeが必要）
RECRTL_TEST_IQ=/path/to/capture.u8iq \
  cargo test --release --test recorded -- --ignored --nocapture
```

通常のテストは受信機・Python・GNU Radioなしで実行できます。
実IQテストはTS同期、H.264/AACのフレーム数、ffmpegによる厳密な復号を検証します。
実機と実IQではMode 3・GI 1/8・QPSK・符号化率2/3・時間インターリーブ長4を検証しています。
他の符号化率はViterbiの符号化・復号テストで確認しています。

ライセンスはGPL-3.0-or-laterです。参照資料・帰属は `NOTICE` を参照してください。
