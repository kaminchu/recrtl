# mirakcでの使い方

[mirakc](https://github.com/mirakc/mirakc)はMirakurun互換APIを持つRust製のPVR
バックエンドです。recrtlをチューナーコマンドとして使い、地上波ワンセグを扱う
手順です。

## 前提

- mirakcの実行ユーザーから `recrtl` を起動できること。PATHに含まれない場合は
  `command` の `recrtl` を実行ファイルの絶対パスに置き換えてください。
- 同じ実行ユーザーにUSBデバイスへのアクセス権があること。手順は
  [READMEの「USBデバイスへのアクセス権」](../README.ja.md#3-usbデバイスへのアクセス権)
  を参照してください。

## config.ymlのtuners

mirakcはMirakurunと異なり、`channels` と `tuners` を1つの `config.yml` に記述
します。チューナーコマンドのチャンネルは `<channel>` ではなくMustacheの
`{{{channel}}}` に置き換わります。

```yaml
tuners:
  - name: RTL-SDR-0
    types: [GR]
    command: recrtl --dev 0 {{{channel}}} - -
```

`{{{channel}}}` は `channels` に定義した物理チャンネル番号に置き換わります。
末尾の `- -` は無期限の受信とTSの標準出力を指定します。受信対象は地上波の
ワンセグのみです。ゲインを固定する場合は、`--dev 0` の後ろに `--gain 38.6` などを
追加します。

mirakcの設定項目の詳細は
[mirakcの設定ドキュメント](https://github.com/mirakc/mirakc/blob/main/docs/config.md)
を参照してください。

## channels

mirakcにはMirakurunのようなチャンネルスキャン機能がありません。`channels` を
手動で記述するか、Mirakurunの `channels.yml` を流用してください。

```yaml
channels:
  - name: NHK総合
    type: GR
    channel: '27'
```

物理チャンネル番号はrecrtlの `--list` で確認できます。

```sh
recrtl --list
```

## ワンセグをフルセグのデジタルTVサービスとして登録する

KonomiTVなどがワンセグの番組情報を取り込めるよう、`--compatible konomitv` を
追加できます。

```yaml
    command: recrtl --dev 0 --compatible konomitv {{{channel}}} - -
```

処理内容は [architecture.md](architecture.md#mirakurun互換処理-compatible-konomitv)
を参照してください。mirakcはMirakurun互換APIを提供するため、SDTの
`service_type` やEITの音声記述子の扱いはMirakurunと同様です。

## サービス・番組情報の更新

mirakcはサービスや番組情報をキャッシュします。`--compatible konomitv` を後から
追加した場合など、キャッシュを作り直したいときは、mirakcを停止してキャッシュ
ディレクトリ（`epg.cache-dir` など）を削除し、再起動してスキャンジョブを
実行してください。

## Dockerで動かす場合

mirakc公式のDockerイメージを使う場合は、コンテナ内に `recrtl` と `librtlsdr` を
用意し、USBデバイスをコンテナへ渡してください。カスタムイメージの作り方は
[mirakcのDockerドキュメント](https://github.com/mirakc/mirakc/blob/main/docs/docker.md)
を参照してください。
