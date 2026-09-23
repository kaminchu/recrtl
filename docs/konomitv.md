# KonomiTVでの使い方

[KonomiTV](https://github.com/tsukumijima/KonomiTV)は、Mirakurunまたはmirakcを
バックエンドとして利用できるTV視聴・録画ソフトです。recrtlのワンセグ出力は
そのままではKonomiTVが番組情報を取り込めないため、`--compatible konomitv` で
互換処理を有効にして使います。

## なぜ互換処理が必要か

KonomiTVは番組情報の音声情報（`audios`）を前提に番組を解析します。ワンセグの
L-EITには音声コンポーネント記述子が含まれないため、Mirakurun/mirakcの番組情報に
`audios` が出ず、KonomiTVが番組を取り込めません。また、ワンセグのサービス種別は
データ放送（`service_type` `0xC0`）として通知されます。

`--compatible konomitv` は次の処理を行います。映像・音声そのものはワンセグの
ままです。

- SDTの `service_type` を `0x01`（デジタルTV）に書き換え、Mirakurun/mirakcに
  フルセグのデジタルTVサービスとして認識させます。
- 各イベントに音声コンポーネント記述子（`0xC4`、AACステレオ・48 kHz・日本語の
  固定値）を追加し、番組情報に `audios` を出します。
- 空のEITスケジュール（`0x50`〜`0x5F`）を合成し、MirakurunがEPG取得を
  `epgRetrievalTime`（既定10分）まで待たずに完了できるようにします。番組情報は
  ワンセグの現在・次のみです。
- ワンセグの字幕（Profile C）をフルセグ（Profile A）に変換し、Profile A前提の
  デコーダで字幕がひらがな化するのを防ぎます。

処理の詳細は [architecture.md](architecture.md#mirakurun互換処理-compatible-konomitv)
を参照してください。

## バックエンドの設定

KonomiTVのバックエンドにはMirakurunまたはmirakcを選べます。それぞれの設定で
チューナーコマンドに `--compatible konomitv` を追加します。

Mirakurun（`tuners.yml`）:

```yaml
- name: RTL-SDR-0
  types:
    - GR
  command: recrtl --dev 0 --compatible konomitv <channel> - -
  isDisabled: false
```

mirakc（`config.yml`）:

```yaml
tuners:
  - name: RTL-SDR-0
    types: [GR]
    command: recrtl --dev 0 --compatible konomitv {{{channel}}} - -
```

詳細は [mirakurun.md](mirakurun.md) と [mirakc.md](mirakc.md) を参照してください。

## サービス・番組情報の作り直し

`--compatible konomitv` を後から追加した場合、既存のサービス・番組情報には
反映されません。バックエンドのキャッシュを削除して取得し直してください。

Mirakurun:

- サービス: Mirakurunを停止して `SERVICES_DB_PATH`（既定 `var/db/services.json`）を
  削除して再起動するか、毎日6:05の `Service.Updater` を待ちます。
- 番組情報: Mirakurunを停止して `PROGRAMS_DB_PATH`（既定 `var/db/programs.json`）を
  削除して再起動し、EPG取得をやり直します。

mirakc:

- mirakcを停止してキャッシュディレクトリ（`epg.cache-dir` など）を削除し、
  再起動してスキャンジョブを実行します。

KonomiTVは、Mirakurun/mirakcの全番組に `audios` が付いた後に番組情報を
取り込めるようになります。

## 制限

- 映像・音声はワンセグのままです。解像度はMirakurun上では `240p` のままです。
- 取得できる番組情報は、ワンセグで放送され、バックエンドが解析できる範囲に限られ
  ます。フルセグ相当の数日分の番組表は保証しません。
- mirakcをバックエンドにする場合、mirakcは局ロゴの収集に対応していないため、
  局ロゴが同梱されていないチャンネルでは既定の局ロゴが使われます。
