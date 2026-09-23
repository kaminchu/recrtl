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
- `--compatible CLIENT`: クライアント固有の互換処理を有効にします。現在は `konomitv` のみを
  指定できます。映像・音声はワンセグのまま、MirakurunにフルセグのデジタルTVサービスとして
  認識させます。SDTのサービス記述子の `service_type` を `0x01`（デジタルTV）に書き換えて
  CRCを再計算するため、Mirakurunの `/api/services` の `type` が `0xC0` ではなく `1` になります。
  サービスID（SID）は変更しません。あわせて、ワンセグのL-EITに無い音声コンポーネント記述子
  （`0xC4`）を各イベントに補い、Mirakurunの番組情報に `audios` を出します（AACステレオ・
  48 kHz・日本語の固定値）。これは音声情報の欠落を前提とするKonomiTVが番組情報を取り込めない
  問題を避けるためです。
- `--help` / `-h`、`--version` / `-v`、`--list` / `-l`: ヘルプ、バージョン、物理チャンネル一覧。

TS以外の診断はstderrへ出力します。SIGINT / SIGTERMで停止でき、出力先のパイプが
詰まっていても停止できます。パイプの読み手が終了した場合は正常終了します。
実機受信では、プレーヤーが読み取りを一時停止してもIQの受信・復号を続けるよう、
未送信のTSを最大4 MiB保持します。読み取りが再開すれば順番どおり送信し、
上限に達した場合は `TS output stalled` として終了します。保存IQの再生は読み手の速度に合わせます。
B25、LNB制御、HTTP/UDP配信のオプションは対応範囲外で、指定するとエラーになります。

## Mirakurunで使う場合

RTL-SDRを1台使う場合の `tuners.yml` の記述例です。
設定ファイルの場所は[Mirakurunの設定ドキュメント](https://github.com/Chinachu/Mirakurun/blob/master/doc/Configuration.ja.md)を参照してください。

```yaml
- name: RTL-SDR-0
  types:
    - GR
  command: recrtl --dev 0 <channel> - -
  isDisabled: false
```

`<channel>` はMirakurunが `channels.yml` の物理チャンネル番号に置き換えます。
末尾の `- -` は無期限の受信とTSの標準出力を指定します。受信対象は地上波のワンセグのみです。
ゲインを固定する場合は、`--dev 0` の後ろに `--gain 38.6` などを追加します。

ワンセグのサービスをフルセグのデジタルTVサービスとしてMirakurunに登録したい場合は、
`command` に `--compatible konomitv` を追加します。

```yaml
  command: recrtl --dev 0 --compatible konomitv <channel> - -
```

`--compatible konomitv` はSDTの `service_type` とEITの音声記述子だけを補うため、映像・音声は
ワンセグのままです（解像度はMirakurun上では `240p` のままです）。
MirakurunはPATに含まれるサービスだけをSDTから登録するため、`--compatible konomitv` を付けても
SIDは変わりません。

Mirakurunはサービス情報を `SERVICES_DB_PATH`（既定では `var/db/services.json`）に保存し、
既存サービスの `type` は毎日6:05の `Service.Updater` まで更新しません。
`--compatible konomitv` を付けずに登録済みのサービスがあると `type` は `192` のまま残るため、
次のいずれかでサービスを登録し直してください。

- Mirakurunを停止して `SERVICES_DB_PATH` を削除してから再起動する（再スキャンされます）。
- 毎日6:05の `Service.Updater` を待つ。

`--compatible konomitv` を追加した状態でサービスDBを作り直すと、`/api/services` の `type` は
`1` になります。
チャンネルスキャンの `refresh=true` は `channels.yml` を更新するだけで、サービスDBの `type` は
更新しないため注意してください。

EITの音声記述子も、既存の番組情報には反映されません。`--compatible konomitv` を付けた状態で
Mirakurunの番組情報を取り直すには、Mirakurunを停止して `PROGRAMS_DB_PATH`
（既定では `var/db/programs.json`）を削除してから再起動し、EPG取得をやり直してください。
KonomiTVなどのクライアントは、Mirakurunの全番組に `audios` が付いた後に番組情報を
取り込めるようになります。

Mirakurunの実行ユーザーから `recrtl` を起動できるようにしてください。
PATHに含まれない場合は、`command` の `recrtl` を実際の実行ファイルの絶対パスに置き換えます。
同じ実行ユーザーにUSBデバイスへのアクセス権も必要です。
Dockerで動かす場合は、コンテナ内に `recrtl` と `librtlsdr` を用意し、USBデバイスを渡してください。

この設定でMirakurunの地上波チャンネルスキャンとワンセグのEPG取得を行えます。
`--sid` は省略（既定の `all`）し、Mirakurun側でサービスを選択してください。
`--sid epg` はワンセグ用EITを選択しないため、チューナーの起動コマンドには指定しません。
Mirakurunの `disableEITParsing` は `false`（既定値）にします。
スキャンではワンセグのサービスID・局名が登録されます。既存のフルセグ用サービスIDを
`channels.yml` に指定している場合は、ワンセグ用に設定し直してください。

スキャンに必要なPATは、SDTから取得した放送のTS IDとNIT PIDへの参照を含めて生成します。
ワンセグ用EIT（PID `0x27`）はそのまま残し、Mirakurunが解析するPID `0x12` にも出力します。
元からPID `0x12` のEITがある場合も、セクション単位でまとめて連続性カウンターを付け直します。
対応先の処理は[MirakurunのTSFilter](https://github.com/Chinachu/Mirakurun/blob/master/src/Mirakurun/TSFilter.ts)を参照してください。

取得できる番組情報は、ワンセグで放送され、Mirakurunが解析できる範囲に限られます。
確認済みの6局では現在・次の番組を取得できますが、フルセグ相当の数日分の番組表は保証しません。
ワンセグに含まれない番組情報を補完・生成する機能はありません。

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
PATは部分受信PMTから生成し、transport_stream_idは実TSのSDTに合わせます（SDT取得前は暫定値1）。
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
Mirakurun向けには、PATのTS ID・NIT参照、EITのPID変換・分割セクションの結合・CRC、
`--compatible konomitv` のSDT `service_type` 書き換えとCRC再計算を検証します。
また、6局分の保存TSを使い、Mirakurun 4.1.3のTSFilter・EPG処理による局名・サービスID・
現在／次の番組名・開始時刻・長さの取得をオフラインで確認しています。
実IQテストはTS同期、H.264/AACのフレーム数、ffmpegによる厳密な復号を検証します。
実機と実IQではMode 3・GI 1/8・QPSK・符号化率2/3・時間インターリーブ長4を検証しています。
他の符号化率はViterbiの符号化・復号テストで確認しています。

ライセンスはGPL-3.0-or-laterです。参照資料・帰属は `NOTICE` を参照してください。
