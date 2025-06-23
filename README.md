# ワンセグCLIツール

RTL2832ベースの安価なUSBチューナーを使用して、日本のワンセグ（1seg）デジタルテレビ放送を受信し、標準出力にMPEG-TSストリームを出力するCLIツール。

## 特徴

- 安価なRTL-SDRドングルでワンセグ放送を受信
- 標準出力への動画ストリーム出力により、ffmpegや動画プレイヤーとのパイプライン連携を実現
- リアルタイム視聴、録画、配信などの用途に対応
- Python実装による柔軟性とカスタマイズ性

## 要件

### ハードウェア
- RTL2832U + R820T/R828D チューナー（一般的な安価SDRドングル）
- USB 2.0/3.0接続
- 適切なアンテナ（UHF対応）

### ソフトウェア
- Python 3.8以上
- RTL-SDRドライバ
- Linux環境（推奨）

## インストール

### 必要な依存関係
```bash
# Ubuntu/Debian
sudo apt-get install python3 python3-pip librtlsdr-dev

# CentOS/RHEL
sudo yum install python3 python3-pip rtl-sdr-devel

# macOS (Homebrew)
brew install python3 rtl-sdr
```

### プロジェクトセットアップ
```bash
# リポジトリをクローン
git clone https://github.com/example/oneseg-cli.git
cd oneseg-cli

# Pythonパッケージのインストール
pip install -r requirements.txt

# 開発モードでインストール（オプション）
pip install -e .
```

### 開発環境のセットアップ

#### 方法1: 環境設定スクリプト使用（推奨）
```bash
# プロジェクトディレクトリで実行
source env.sh

# 以降、通常通り実行可能
python oneseg.py --list-devices
```

#### 方法2: 実行ラッパースクリプト使用
```bash
# 環境設定済みのラッパースクリプトを使用
python run_oneseg.py --list-devices
python run_oneseg.py -c 13 | ffplay -
```

#### 方法3: 手動でPYTHONPATH設定
```bash
export PYTHONPATH="$(pwd)/src:$PYTHONPATH"
python oneseg.py --list-devices
```

## 使用方法

### デバイス動作確認

```bash
# RTL-SDRデバイスと信号処理パイプラインの動作確認
python oneseg.py --test-device

# 特定のチャンネルでテスト
python oneseg.py --test-device -c 27

# 特定のデバイスでテスト
python oneseg.py --test-device -d 1
```

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

## 技術仕様

### ISDB-T（日本の地上デジタル放送）
- 変調方式: OFDM
- Mode 3: 13セグメント構成
- ワンセグ: 中央セグメント（セグメント0）
- 帯域幅: 6MHz

### ワンセグ仕様
- 映像: H.264/AVC（解像度320x240、フレームレート15fps）
- 音声: AAC-LC（48kHz、モノラル/ステレオ）
- 多重化: MPEG-2 Transport Stream

## 開発

### テスト実行

```bash
# 全テスト実行
python -m pytest tests/

# カバレッジ付きテスト
python -m pytest tests/ --cov=src
```

### プロジェクト構造

```
oneseg/
├── README.md            # 本ファイル
├── requirements.txt     # Python依存関係
├── setup.py            # パッケージ設定
├── oneseg.py           # メインCLIスクリプト
├── src/                # コアライブラリ
│   ├── rtl_interface.py # RTL-SDR制御
│   ├── isdb_decoder.py  # ISDB-T復調
│   ├── oneseg_parser.py # ワンセグ解析
│   └── ts_output.py     # MPEG-TS出力
└── tests/              # テストスイート
```

## 制限事項

- リアルタイム処理のため、CPU性能に依存
- RTL-SDRドングルの個体差による受信感度の違い
- アンテナ・受信環境による信号品質の影響
- 著作権保護されたコンテンツの取り扱い制限

## ライセンス

GPL v3 - RTL-SDRドライバとの互換性のため

## 貢献

プルリクエストやイシューの報告を歓迎します。

## 免責事項

本ソフトウェアは教育・研究目的で開発されています。放送法その他の法規制を遵守してご利用ください。