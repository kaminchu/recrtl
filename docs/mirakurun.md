# Mirakurunでの使い方

recrtlを[Mirakurun](https://github.com/Chinachu/Mirakurun)のチューナーコマンドと
して使い、地上波ワンセグのチャンネルスキャンとEPG取得、録画を行う手順です。

## 前提

- Mirakurunの実行ユーザーから `recrtl` を起動できること。PATHに含まれない場合は
  `command` の `recrtl` を実行ファイルの絶対パスに置き換えてください。
- 同じ実行ユーザーにUSBデバイスへのアクセス権があること。手順は
  [READMEの「USBデバイスへのアクセス権」](../README.ja.md#3-usbデバイスへのアクセス権)
  を参照してください。
- Mirakurunの `disableEITParsing` は `false`（既定値）にします。

## tuners.yml

RTL-SDRを1台使う場合の記述例です。設定ファイルの場所は
[Mirakurunの設定ドキュメント](https://github.com/Chinachu/Mirakurun/blob/master/doc/Configuration.ja.md)
を参照してください。

```yaml
- name: RTL-SDR-0
  types:
    - GR
  command: recrtl --dev 0 <channel> - -
  isDisabled: false
```

`<channel>` はMirakurunが `channels.yml` の物理チャンネル番号に置き換えます。
末尾の `- -` は無期限の受信とTSの標準出力を指定します。受信対象は地上波の
ワンセグのみです。ゲインを固定する場合は、`--dev 0` の後ろに `--gain 38.6` などを
追加します。

## チャンネルスキャンとEPG取得

この設定でMirakurunの地上波チャンネルスキャンとワンセグのEPG取得を行えます。

- `--sid` は省略（既定の `all`）し、Mirakurun側でサービスを選択してください。
- `--sid epg` はワンセグ用EITを選択しないため、チューナーの起動コマンドには
  指定しません。
- スキャンではワンセグのサービスID・局名が登録されます。既存のフルセグ用
  サービスIDを `channels.yml` に指定している場合は、ワンセグ用に設定し直して
  ください。

スキャンに必要なPATは、SDTから取得した放送のTS IDとNIT PIDへの参照を含めて
生成します。詳細は [architecture.md](architecture.md#patの生成) を参照してください。

## ワンセグをフルセグのデジタルTVサービスとして登録する

ワンセグのサービスをフルセグのデジタルTVサービスとしてMirakurunに登録したい
場合は、`command` に `--compatible konomitv` を追加します。

```yaml
  command: recrtl --dev 0 --compatible konomitv <channel> - -
```

`--compatible konomitv` はSDTの `service_type`、EITの音声記述子、空のEIT
スケジュール（EPG取得の早期完了用）だけを補うため、映像・音声はワンセグのままです
（解像度はMirakurun上では `240p` のままです）。MirakurunはPATに含まれるサービス
だけをSDTから登録するため、SIDは変わりません。EPG取得はフルセグと同様に
早期完了し、取得できる番組情報はワンセグの現在・次のみです。
処理の詳細は [architecture.md](architecture.md#mirakurun互換処理-compatible-konomitv)
を参照してください。

## サービスDB・番組情報の作り直し

Mirakurunはサービス情報を `SERVICES_DB_PATH`（既定では `var/db/services.json`）に
保存し、既存サービスの `type` は毎日6:05の `Service.Updater` まで更新しません。
`--compatible konomitv` を付けずに登録済みのサービスがあると `type` は `192` の
まま残るため、次のいずれかでサービスを登録し直してください。

- Mirakurunを停止して `SERVICES_DB_PATH` を削除してから再起動する
  （再スキャンされます）。
- 毎日6:05の `Service.Updater` を待つ。

`--compatible konomitv` を追加した状態でサービスDBを作り直すと、`/api/services`
の `type` は `1` になります。チャンネルスキャンの `refresh=true` は `channels.yml`
を更新するだけで、サービスDBの `type` は更新しないため注意してください。

EITの音声記述子も、既存の番組情報には反映されません。`--compatible konomitv` を
付けた状態でMirakurunの番組情報を取り直すには、Mirakurunを停止して
`PROGRAMS_DB_PATH`（既定では `var/db/programs.json`）を削除してから再起動し、
EPG取得をやり直してください。KonomiTVなどのクライアントは、Mirakurunの全番組に
`audios` が付いた後に番組情報を取り込めるようになります。

## Dockerで動かす場合

コンテナ内に `recrtl` と `librtlsdr` を用意し、USBデバイスをコンテナへ渡して
ください。`recrtl` はLinux向けの実行ファイルなので、ホストと同じ
アーキテクチャのイメージに配置します。

## 制限

取得できる番組情報は、ワンセグで放送され、Mirakurunが解析できる範囲に限られます。
確認済みの6局では現在・次の番組を取得できますが、フルセグ相当の数日分の番組表は
保証しません。
