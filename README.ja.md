# recrtl

**recrtl** は、RTL-SDRで日本の地上デジタル放送（ISDB-T）のワンセグを受信し、
MPEG-TSを記録するRust製コマンドラインツールです。UHF物理チャンネルを選局して
ワンセグ（Layer A）を復調し、188バイトのMPEG-TSをファイルまたは標準出力へ
書き出します。

受信処理はすべてRustで実装しています。Python・GNU Radio・gr-isdbtは不要です。
`librtlsdr` は実機のUSB制御に限り実行時に読み込みます。保存IQの復号には
`librtlsdr` も不要です。現在の実行対象はLinuxです。

**English README is [README.md](README.md).**

## 開発の背景

PCで日本の地上デジタル放送（ISDB-T）を受信するには、従来は専用のPCIe/USB
チューナーカードやドングルに依存してきました。しかし、これらの製品は次々と
生産終了しており、PC向けのフルセグチューナーを入手することは年々難しく、
高価になっています。

一方、RTL-SDRを用いた受信機は比較的入手しやすく、安価であり続けています。
これは「SDR」として販売される機器に限りません。RTL2832Uチップは、一般の
通販でおおむね1,000〜2,000円程度で購入できるワンセグ向けUSBチューナー
（例: DS-DT310BK、DS-DT308SV）にも使われており、これらの機器でもISDB-T
ワンセグを受信できます。recrtlは、まさにこのクラスのハードウェアを対象に
しています。

ワンセグには、自作の録画・配信に適した次のような性質があります。

- **再エンコード不要で小容量。** ワンセグの映像・音声はすでに低ビットレートの
  H.264/AACで符号化されています。録画はMPEG-TSのまま保存でき、トランスコードが
  不要なため、非力なCPUや小さなディスクでも長時間の記録を保持できます。
- **安価な「全録」。** ワンセグはフルセグの約1/6の帯域しか使わず、復号も軽い
  ため、1台のマシンで複数の安価なRTL2832U受信機を同時に動かし、多数チャンネルを
  一括録画する、いわゆる「全録」構成を比較的容易に組めます。
- **低帯域回線でも配信しやすい。** ビットレートが低いため、帯域の限られた回線
  でもワンセグを視聴しやすく、安価または旧式のシングルボードコンピュータから
  でも配信しやすいです。

recrtlは、こうしたハードウェアと用途を、単一の自己完結したRustバイナリで
扱えるようにすることを目指しています。RTL-SDR互換受信機を直接制御し、
ワンセグをソフトウェアで復調し、既存のツール（プレーヤー、Mirakurun、
mirakc、KonomiTV）が扱える標準的なMPEG-TSを出力します。

## 特徴

- ISDB-Tワンセグの映像・音声を標準的な188バイトMPEG-TSとして記録します。
- recdvb互換のCLI: `recrtl [OPTIONS] CHANNEL RECTIME DESTFILE`。
- 実機のRTL-SDR、または保存した2.048 MS/sのIQキャプチャで動作します。
- SID、順序、recdvb別名（`hd`、`sd1`、`1seg`、`epg` など）でサービスを選択できます。
- nullパケットの除外、記録端の不完全なH.264/AACフレームの整形ができます。
- ワンセグをMirakurun/EPGへ連携するための互換処理（`--compatible konomitv`）を
  備えています。
- `--list`、`--list-devices`、`--list-regions`、`--list-channels` はハードウェア
  なしで実行できます。

## 動作要件

- **OS:** Linux（Debian、Ubuntu、Raspberry Pi OSで確認）。
- **ツールチェーン:** Rust 1.98.1以降。
- **ハードウェア:** 実機受信にはRTL-SDR互換の受信機。オフライン復号には保存IQ
  ファイルを代わりに使用できます。
- **任意:** 再生と実IQ受け入れテストには `ffmpeg`（`ffplay`・`ffprobe`を含む）。

対応するのはISDB-Tの **Mode 3、GI 1/8、QPSK、1セグメント** のみです。
BS/CSやフルセグの受信は対応範囲外です。対応パラメータの詳細は
[docs/architecture.md](docs/architecture.md) を参照してください。

## インストール

### 1. 依存パッケージのインストール

aptを使う環境（Debian、Ubuntu、Raspberry Pi OS）では次のように準備します。

```sh
sudo apt update
# ビルド用ツールとRustのインストールに使うツール
sudo apt install build-essential curl ca-certificates
# 実機受信用ライブラリ、udevルール、接続確認用のrtl_test
sudo apt install rtl-sdr
```

`rtl-sdr` の依存関係として、そのOSに対応する `librtlsdr` もインストールされます。
保存IQの復号だけなら `rtl-sdr` は不要です。Rustの依存クレートはビルド時にCargoが
取得します。

Rust/Cargoが未導入の場合は、[公式のrustup手順](https://doc.rust-lang.org/book/ch01-01-installation.html)
でインストールします。

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
```

再生や実IQの受け入れテストには、追加で `ffmpeg` をインストールします。録画だけなら
不要です。

```sh
sudo apt install ffmpeg
```

### 2. ビルドとインストール

```sh
cargo build --release --locked
cargo install --path . --locked
```

### 3. USBデバイスへのアクセス権

一般ユーザーで実機受信するには、USBデバイスへのアクセス権が必要です。
Debian／Ubuntu系のパッケージに含まれるudevルールは、対応デバイスへのアクセスを
`plugdev` グループに許可します（[パッケージの説明](https://github.com/osmocom/rtl-sdr/blob/master/debian/README.Debian)）。
受信に使うユーザーで次を実行します。

```sh
sudo groupadd -f plugdev
sudo usermod -aG plugdev "$(id -un)"
sudo udevadm control --reload-rules
```

その後、**ログアウトしてログインし直し**（SSHなら再接続）、RTL-SDRをUSBから
抜き差しします。`id -nG` に `plugdev` が含まれることを確認し、`sudo` を付けずに
接続を確認します。

```sh
id -nG
rtl_test -s 2048000
# サンプルの読み取りを確認したらCtrl+Cで終了
recrtl --list-devices
```

`rtl_test` を終了してから `recrtl` を起動してください。同じ受信機を同時には
使えません。`recrtl --list-devices` は列挙だけなので、実際に開けるかどうかは
`rtl_test` で確認します。

権限エラーが続く場合は、`/usr/lib/udev/rules.d/` または `/lib/udev/rules.d/` の
`60-librtlsdr*.rules` に受信機のUSB IDが含まれているか確認してください。

`Kernel driver is active` などで開けない場合は、他の受信ソフトを終了し、DVB用
カーネルドライバーとの競合を確認します。競合している場合のみ、次の設定を追加して
再起動します。この設定は同じドライバーを使う機器のDVB受信にも影響します。

```sh
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/recrtl-rtl-sdr.conf
sudo reboot
```

## クイックスタート

```sh
# 物理19chを60秒間録画
recrtl --dev 0 --gain 38.6 19 60 recording.ts

# 終了シグナルまで録画し、TSを標準出力へ送る
recrtl 19 - - > recording.ts

# 標準出力を再生ソフトへ渡す
recrtl 19 - - | ffplay -i pipe:0
```

## 使い方

```text
recrtl [OPTIONS] CHANNEL RECTIME DESTFILE
```

### 引数

- `CHANNEL`: UHF物理チャンネル13〜62。BS/CSやフルセグは受信しません。
- `RECTIME`: 秒数、`H:M`、`H:M:S`、`1h30m`、`1h2m3s`、または無期限の `-`。
  recdvbと同じく `1:30` は1時間30分です。実機では受信開始からの経過時間で終了します。
- `DESTFILE`: 新規ファイル、または標準出力の `-`。既存ファイルへの上書きは
  エラーにします。

### オプション

- `--dev N` / `-d N`: RTL-SDRのデバイス番号（既定値0）。
- `--sid LIST` / `-i LIST`: SIDのカンマ区切り、`all`（既定値）、`hd` / `sd1`、
  `sd2`、`sd3`、`1seg`、`epg`、`epg1seg`。数値と別名の混在も可能です。
  `1seg` はPMT PID `0x1fc8` の番組を選択します。存在しないSIDではTSを出力せず、
  有期限録画・ファイル終端でエラーにします。
- `--strip` / `-s`: nullパケットを除外。
- `--compatible CLIENT`: クライアント固有の互換処理を有効にします。現在は
  `konomitv` のみを指定できます。映像・音声はワンセグのまま、Mirakurunにフルセグの
  デジタルTVサービスとして認識させます。SDTのサービス記述子の `service_type` を
  `0x01`（デジタルTV）に書き換えてCRCを再計算するため、Mirakurunの
  `/api/services` の `type` が `0xC0` ではなく `1` になります。サービスID（SID）は
  変更しません。あわせて、ワンセグのL-EITに無い音声コンポーネント記述子（`0xC4`）を
  各イベントに補い、Mirakurunの番組情報に `audios` を出します（AACステレオ・
  48 kHz・日本語の固定値）。これは音声情報の欠落を前提とするKonomiTVが番組情報を
  取り込めない問題を避けるためです。さらに、ワンセグに存在しないEITスケジュール
  （`0x50`〜`0x5F`）を空のセクションとして補い、MirakurunのEPG取得がフルセグと
  同様に早期完了するようにします（番組情報は現在・次のみ）。最後に、ワンセグの
  ARIB字幕をフルセグ（Profile A）へ変換します。PMTの字幕 `data_component_id` を
  `0x0012`（Profile C）から `0x0008`（Profile A）へ書き換え、各字幕文の先頭と
  画面クリア（`CS`）の直後に「G2を漢字に指定する」エスケープを挿入することで、
  Profile A前提のデコーダでも漢字がひらがな化せずに表示されます。
- `--help` / `-h`、`--version` / `-v`、`--list` / `-l`: ヘルプ、バージョン、
  物理チャンネル一覧。

### 診断・受信オプション

- `--list-devices`: 接続されているRTL-SDR受信機を一覧表示。
- `--list-regions`: 同梱の局データベースにある都道府県コードを一覧表示。
- `--list-channels PREFECTURE`: 指定都道府県で保持している局を一覧表示。
- `--iq-file PATH`: 保存した2.048 MS/s unsigned 8-bit I,Q交互データを復号
  （ハードウェア不要）。
- `--trim`: 保存IQ専用。不完全なH.264/AACフレームと最初のSPS/PPS/IDR以前の映像を
  除外します。EOFまで全TSを保持します。再エンコードはしません。
- `--gain DB`: 固定ゲイン（省略時は自動）。
- `--frequency MHz`: 中心周波数を上書き。
- `--ppm N`: チューナーの周波数補正。
- `--verbose`: 受信統計をstderrへ出力。

### 出力と終了時の挙動

TS以外の診断はstderrへ出力します。SIGINT / SIGTERMで停止でき、出力先のパイプが
詰まっていても停止できます。パイプの読み手が終了した場合は正常終了します。

実機受信では、プレーヤーが読み取りを一時停止してもIQの受信・復号を続けるよう、
未送信のTSを最大4 MiB保持します。読み取りが再開すれば順番どおり送信し、上限に
達した場合は `TS output stalled` として終了します。保存IQの再生は読み手の速度に
合わせます。

B25、LNB制御、HTTP/UDP配信のオプションは対応範囲外で、指定するとエラーになります。

### サービスの選択

```sh
# SIDを選択
recrtl --sid 32152 19 1h30m recording.ts

# SIDとワンセグEPGを混在させる
recrtl --sid 32152,epg1seg 19 - - > recording.ts
```

### 保存IQの再生と検証

```sh
# 2.048 MS/s unsigned 8-bit I,Q交互の保存データを復号
recrtl --iq-file capture.u8iq 19 - recording.ts

# 有限IQの記録端を整形して、映像・音声の厳密な検証に使う
recrtl --iq-file capture.u8iq --trim 19 - trimmed.ts
ffmpeg -v error -xerror -i trimmed.ts -map 0:v:0 -map 0:a:0 -f null -
```

保存IQでは `RECTIME` は入力サンプル数に換算され、実時間での待機はしません。
`-` はファイル終端まで処理します。通常は5〜10秒以上のIQを用意してください。

## 連携

recrtlはMirakurun互換サーバーのチューナーコマンドとして利用でき、ワンセグ出力を
KonomiTV向けに調整できます。連携ガイドを参照してください。

- [Mirakurun](docs/mirakurun.md)
- [mirakc](docs/mirakc.md)
- [KonomiTV](docs/konomitv.md)

## 開発

標準のチェックを実行します。

```sh
cargo test --locked
cargo fmt --check
cargo clippy --all-targets -- -D warnings
```

通常のテストは受信機・Python・GNU Radioなしで実行できます。任意実行の受け入れ
テストは実IQを使い、`ffmpeg` と `ffprobe` が必要です。

```sh
RECRTL_TEST_IQ=/path/to/capture.u8iq \
  cargo test --release --test recorded -- --ignored --nocapture
```

各テスト層が何を検証するか、受信処理の内部は
[docs/architecture.md](docs/architecture.md) を参照してください。

## ドキュメント

- [docs/architecture.md](docs/architecture.md): 対応モード、DSP/FECの処理経路、
  TS処理、Mirakurun互換処理、局データベース。
- [docs/mirakurun.md](docs/mirakurun.md): Mirakurunでの使い方。
- [docs/mirakc.md](docs/mirakc.md): mirakcでの使い方。
- [docs/konomitv.md](docs/konomitv.md): KonomiTVでの使い方。
- [README.md](README.md): 英語版README（原本）。

## ライセンス

GPL-3.0-or-later。参照資料・帰属は [LICENSE](LICENSE) と [NOTICE](NOTICE) を
参照してください。
