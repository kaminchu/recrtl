# アーキテクチャ

recrtlの受信処理・TS処理・テスト構成についての技術情報です。使い方そのものは
[README](../README.ja.md) を参照してください。

## 対応範囲

現在の対応範囲はISDB-Tの **Mode 3、GI 1/8、部分受信Layer A、QPSK、1セグメント**
です。TMCCから符号化率1/2・2/3・3/4・5/6・7/8と時間インターリーブ長0・1・2・4を
選びます。他のモード・GI・変調方式は未対応です。BS/CSやフルセグも対象外です。

## 処理経路

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

同期を失った場合は同期・FEC・番組情報をリセットして再取得します。無信号や復号
失敗からダミーTSは生成しません。

### 実装モジュール

| ファイル | 役割 |
| --- | --- |
| `src/rtl.rs` | `librtlsdr` の実行時ロードとUSB受信、デバイス列挙 |
| `src/dsp.rs` | リサンプリング、同期、FFT、TMCC、等化、デインターリーブ |
| `src/fec.rs` | デパンクチャ、軟判定Viterbi、バイトデインターリーブ、RS復号 |
| `src/permutation.rs` | ISDB-T Mode 3の周波数パーミュテーション表 |
| `src/ts.rs` | PSI/SI解析、PAT生成、サービスフィルタ、Mirakurun互換処理 |
| `src/recording.rs` | `--trim` の記録端整形 |
| `src/receiver.rs` | 受信ループ、出力バッファリング、シグナル処理 |
| `src/cli.rs` | 引数解析とバリデーション |
| `src/main.rs` | エントリポイント、一覧系サブコマンド |

## リサンプリング

RTL-SDRからは2.048 MS/sでIQを取得します。ISDB-Tの1セグメントはFFT後の
有効帯域が約5.6 MHz相当（モード3のFFTサイズ8192、キャリア間隔約
1/8.126 MHz）であるため、125/252のFIRリサンプラでサンプルレートを変換して
以降のOFDM処理に合わせます。

## TS処理

### PATの生成

recrtlは受信したPMT（PID `0x1fc8`〜`0x1fcf`）からPATを生成します。
`transport_stream_id` は実TSのSDTに合わせます（SDT取得前は暫定値1）。
SDTを再取得してTS IDが変わった場合はPATを再生成します。PATには選択中の
サービスのPMT PIDに加え、プログラム0でNIT PID（`0x10`）への参照を含めます。
これはMirakurunのチャンネルスキャンが必要とする情報です。

### サービスフィルタ

PATに含まれるサービス（PMTから得たSIDとPID集合）だけを通過させます。
`--sid all` ではすべて、それ以外では指定SID・順序・別名に一致するサービスの
PIDのみを出力します。EPG系の指定ではEITのPIDを追加で通過させます。
元のTSにあるPAT・CAT・PMT・SDT・EITなどのPSI/SIは、必要なものを選択的に
通します。

### EITのPID変換

ワンセグのEITはPID `0x27`（L-EIT）で放送されますが、MirakurunはPID `0x12` の
EITを解析します。recrtlはワンセグ用EIT（`0x27`）をそのまま残しつつ、同じ内容を
PID `0x12` にも出力します。元からPID `0x12` のEITがある場合も、セクション単位で
まとめて連続性カウンターを付け直します。これは、ネイティブEITとミラーしたL-EITが
部分セクションで混ざったり、連続性カウンターが衝突したりしないようにするためです。
対応先の処理は
[MirakurunのTSFilter](https://github.com/Chinachu/Mirakurun/blob/master/src/Mirakurun/TSFilter.ts)
を参照してください。

### 取得できる番組情報の限界

取得できる番組情報は、ワンセグで放送され、Mirakurunが解析できる範囲に限られます。
確認済みの6局では現在・次の番組を取得できますが、フルセグ相当の数日分の番組表は
保証しません。ワンセグに含まれない番組情報を補完・生成する機能はありません。

## Mirakurun互換処理（`--compatible konomitv`）

`--compatible konomitv` はSDTとEITに対して次の2つだけを行います。映像・音声は
ワンセグのままです（Mirakurun上の解像度も `240p` のまま）。

### SDTの `service_type` 書き換え

SDT（table_id `0x42`）内の各サービス記述子（`0x48`）の `service_type` を
`0x01`（デジタルTV）に書き換え、CRCを再計算します。これによりMirakurunの
`/api/services` の `type` が `0xC0` ではなく `1` になります。サービスID（SID）は
変更しません。MirakurunはPATに含まれるサービスだけをSDTから登録するため、SIDは
変わりません。

### EITの音声記述子の補完

ワンセグのL-EITは短形式イベント記述子やコンテンツ記述子しか持たず、音声
コンポーネント記述子（`0xC4`）を含みません。そのためMirakurunは `audio`/`audios`
を公開せず、音声情報の欠落を前提とするKonomiTVが番組情報を取り込めません。
recrtlは `0xC4` を持たない各イベントに、AACステレオ・48 kHz・日本語・主音声の
固定値（`0xC4 0x09 0xF2 0x03 0x01 0x0F 0xFF 0x4F 0x6A 0x70 0x6E`）の記述子を
追加し、セクション長とCRCを更新します。

### 既存データベースへの反映

Mirakurunはサービス情報を `SERVICES_DB_PATH`（既定では `var/db/services.json`）に
保存し、既存サービスの `type` は毎日6:05の `Service.Updater` まで更新しません。
`--compatible konomitv` を付けずに登録済みのサービスがあると `type` は `192` の
まま残ります。EITの音声記述子も既存の番組情報には反映されません。登録し直しの
手順は [docs/mirakurun.md](mirakurun.md) を参照してください。

## 局データベース

`data/stations.json` は旧実装の放送局データを保存したもので、最新の割当を保証する
ものではありません。`--list-regions` と `--list-channels` はこのデータを参照します。

## テスト構成

通常のテストは受信機・Python・GNU Radioなしで実行できます。

- **Mirakurun向け:** PATのTS ID・NIT参照、EITのPID変換・分割セクションの結合・
  CRC、`--compatible konomitv` のSDT `service_type` 書き換えとCRC再計算を検証します。
- **オフラインEPG:** 6局分の保存TSを使い、Mirakurun 4.1.3のTSFilter・EPG処理に
  よる局名・サービスID・現在／次の番組名・開始時刻・長さの取得を確認しています。
- **実IQ受け入れテスト:** TS同期、H.264/AACのフレーム数、ffmpegによる厳密な復号を
  検証します（`ffmpeg` と `ffprobe` が必要）。

実機と実IQではMode 3・GI 1/8・QPSK・符号化率2/3・時間インターリーブ長4を検証して
います。他の符号化率はViterbiの符号化・復号テストで確認しています。

実行方法は [README](../README.ja.md#開発) を参照してください。
