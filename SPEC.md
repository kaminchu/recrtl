# ワンセグCLIツール仕様書

## 概要

RTL2832ベースの安価なUSBチューナーを使用して、日本のワンセグ（1seg）デジタルテレビ放送を受信し、標準出力にMPEG-TSストリームを出力するCLIツール。

## 目的

- 安価なRTL-SDRドングルでワンセグ放送を受信
- 標準出力への動画ストリーム出力により、ffmpegや動画プレイヤーとのパイプライン連携を実現
- リアルタイム視聴、録画、配信などの用途に対応

## 技術仕様

### ハードウェア要件

- RTL2832U + R820T/R828D チューナー（一般的な安価SDRドングル）
- USB 2.0/3.0接続
- 周波数範囲: 470-770MHz（日本の地上デジタル放送帯域）

### ソフトウェア仕様

#### ISDB-T（日本の地上デジタル放送）
- 変調方式: OFDM
- Mode 3: 13セグメント構成
- ワンセグ: 中央セグメント（セグメント0）
- 帯域幅: 6MHz
- ガードインターバル: 1/4, 1/8, 1/16, 1/32

#### ワンセグ仕様
- 映像: H.264/AVC（解像度320x240、フレームレート15fps）
- 音声: AAC-LC（48kHz、モノラル/ステレオ）
- 多重化: MPEG-2 Transport Stream

### 実装言語・ライブラリ

- **言語**: Python 3.8+
- **主要ライブラリ**:
  - `pyrtlsdr`: RTL-SDR制御
  - `numpy`: 数値計算
  - `scipy`: 信号処理
  - `argparse`: CLI引数解析

## CLI仕様

### 基本コマンド

```bash
python oneseg.py [OPTIONS]
```

### コマンドライン引数

| 引数 | 説明 | デフォルト |
|------|------|-----------|
| `-c, --channel` | チャンネル番号（13-62ch） | 13 |
| `-f, --frequency` | 周波数直接指定（MHz） | - |
| `-g, --gain` | RF gain（0-50dB） | 自動 |
| `-s, --sample-rate` | サンプリングレート（Hz） | 2048000 |
| `-d, --device` | RTL-SDRデバイスID | 0 |
| `-v, --verbose` | 詳細ログ出力 | False |
| `--list-devices` | 利用可能デバイス一覧 | - |

### 出力形式

- **標準出力**: MPEG-2 Transport Stream（バイナリ）
- **標準エラー出力**: ログ、信号強度、エラー情報

## 使用例

### 基本的な受信・再生

```bash
# チャンネル13を受信してffplayで再生
python oneseg.py -c 13 | ffplay -

# NHK総合（東京）を受信してVLCで再生
python oneseg.py -c 27 | vlc -

# 周波数を直接指定
python oneseg.py -f 473.142857 | ffplay -
```

### 録画・保存

```bash
# MP4ファイルに保存
python oneseg.py -c 13 | ffmpeg -i - -c copy output.mp4

# 10分間録画
python oneseg.py -c 13 | timeout 600 ffmpeg -i - -c copy recording.ts

# HLS形式でセグメント化
python oneseg.py -c 13 | ffmpeg -i - -hls_time 4 -hls_playlist_type event playlist.m3u8
```

### 配信・ストリーミング

```bash
# RTMP配信
python oneseg.py -c 13 | ffmpeg -i - -c copy -f flv rtmp://server/live/stream

# HTTP Live Streaming
python oneseg.py -c 13 | ffmpeg -i - -hls_time 4 -hls_list_size 5 stream.m3u8
```

## プロジェクト構造

```
oneseg/
├── SPEC.md              # 本仕様書
├── README.md            # プロジェクト概要
├── requirements.txt     # Python依存関係
├── setup.py            # パッケージ設定
├── oneseg.py           # メインCLIスクリプト
├── src/
│   ├── __init__.py
│   ├── rtl_interface.py # RTL-SDR制御
│   ├── isdb_decoder.py  # ISDB-T復調
│   ├── oneseg_parser.py # ワンセグ解析
│   └── ts_output.py     # MPEG-TS出力
└── tests/
    ├── __init__.py
    └── test_*.py        # ユニットテスト
```

## 実装フェーズ

### Phase 1: 基盤実装
- プロジェクト構造作成
- RTL-SDR基本制御
- 信号取得・前処理

### Phase 2: 信号処理
- OFDM復調実装
- ISDB-T Mode3対応
- エラー訂正処理

### Phase 3: ワンセグ処理
- トランスポートストリーム解析
- PID抽出・フィルタリング
- 標準出力への出力

### Phase 4: 最適化・安定化
- 性能最適化
- エラーハンドリング強化
- ドキュメント整備

## 制限事項

- リアルタイム処理のため、CPU性能に依存
- RTL-SDRドングルの個体差による受信感度の違い
- アンテナ・受信環境による信号品質の影響
- 著作権保護されたコンテンツの取り扱い制限

## ライセンス

GPL v3（RTL-SDRドライバとの互換性のため）