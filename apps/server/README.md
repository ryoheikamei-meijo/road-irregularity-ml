# サーバー（apps/server）

アプリが判定した結果と、走行後の生データを受けて保存する API。経緯と決定は [`docs/knowledge/2026-11-18/20261118_local_server_plan.md`](../../docs/knowledge/2026-11-18/20261118_local_server_plan.md)。今は**ローカルだけ**（AWS へのデプロイ・地図・ログインは作っていない）。

- API：TypeScript（strict）+ [Hono](https://hono.dev) + Zod。Lambda 用の入口は、デプロイのときに足す（`createApp` は入口に依存しない）
- DB：PostgreSQL（`migrations/*.sql`）
- 生データ：S3 互換のストレージに、**署名付き URL で直接 PUT**する（API は通さない）。ローカルは SeaweedFS

## 構成

![サーバー側の構成。Android アプリが判定結果を 5 秒ごとに API へ送り、生データは署名付き URL でストレージへ直接送る。上段はローカルで動作確認済み、下段は AWS の計画](docs/architecture.svg)

上段が**いまの構成（ローカルで動作確認済み）**、下段が**本番の AWS（未構築）**。左のアプリは同じもので、サーバーの入口・DB・ストレージを、ローカルの部品から AWS のサービスに入れ替える。矢印の番号は送る順番で、①は走行中に何度も、②③④は走行を止めたあと。③だけは API を通らず、アプリが署名付き URL でストレージへ直接送る（Lambda は 6 MB を超えて受けられず、生データは 50〜160 MB のため）。

| 項目 | いま（ローカル） | 本番（AWS・計画） | 理由 |
| --- | --- | --- | --- |
| API | TypeScript + Hono + Zod を Node.js で動かす | API Gateway + Lambda（Lambda 用の入口を足す） | 静的型付けで書きたい。Hono は Lambda でも動く。Zod で、実行時にも入力の型を検証する |
| DB | PostgreSQL（Docker） | RDS など（未選定） | 地図で範囲を検索し、同じ場所を何度も通った集計をするのに、SQL が素直 |
| 生データの置き場 | SeaweedFS（Docker。S3 の API） | Amazon S3 | S3 の API だけを使うので、そのまま入れ替えられる |
| 生データの送り方 | 署名付き URL で、アプリから直接 PUT | 同じ | API は URL の発行と完了の確認だけをする |
| 判定結果の送り方 | 5 秒ごとにまとめて POST。失敗したら端末に残して再送 | 同じ | `(走行 ID, 窓の始まり)` で重複を弾くので、再送しても二重にならない |
| 認証 | 共有キー（`x-api-key`） | 同じ（HTTPS にする） | 研究室の中だけの前提 |
| 見送ったもの | AWS Emulator、MinIO | - | [経緯](../../docs/knowledge/2026-11-18/20261118_local_server_plan.md) |

同じ図を、ロゴつきの HTML（アーティファクト）にしたものは [こちら](https://claude.ai/artifact/XbSptd7i6ffjLttfh6egR2)（所有者だけが開ける）。図は `docs/diagram/build.py` で作る（`python3 apps/server/docs/diagram/build.py`。ロゴの素材は `docs/diagram/logos/`）。ロゴは構成を示すためだけに使い、AWS のアイコンは色と形を変えていない。出典は `build.py` の冒頭にある。

## 動かし方

JDK は要らない。Node.js 22 以上と Docker が要る。

```sh
cd apps/server
npm install
cp .env.example .env     # 開発用の値。.env は git に入れない
npm run up               # PostgreSQL と S3 互換のストレージを立てる（127.0.0.1 だけに公開）
npm run migrate          # 表を作る
npm run dev              # http://127.0.0.1:8787
npm test                 # 結合テスト（上の 2 つに実際につなぐ。専用のスキーマとバケットを使う）
npm run typecheck
npm run down             # 止める（データは残る。消すなら docker compose down -v）
```

PC から記録済みの走行を送って、保存を確かめる：

```sh
npm run send -- ../../wheelchair_data/11.1/20261101142339 ../../data/analysis/20261116_export_onnx/parity/20261101142339.csv
```

## API

認証は、ヘッダー `x-api-key`（共有キー。研究室内だけの前提で、強い認証ではない）。`/health` だけは鍵が要らない。

| メソッド・パス | 内容 |
| --- | --- |
| `POST /sessions` | 走行の登録。id（UUID）はアプリが作る。同じ id の再送は 200（冪等）、別の端末の同じ id は 409 |
| `POST /sessions/:id/detections` | 判定結果のバッチ（最大 2000 件）。`window_start_ms` はセンサーの時刻（アプリでは起動から。生データの `timestamp` と同じ基準）、`window_wall_ms` は壁時計（epoch ms）。`(走行 id, 窓の始まり)` で重複を弾く。`{received, inserted, duplicates}` を返す |
| `POST /sessions/:id/raw-upload-url` | 生データを PUT する署名付き URL を返す（有効 1 時間） |
| `POST /sessions/:id/raw-complete` | アップロードの完了通知。置かれたファイルの大きさが `size_bytes` と合わなければ 409 |
| `GET /health` | DB への疎通 |

判定のクラスは `flat`・`step`・`rough`（モデルの `dansa`・`dekobo` は、送る前に置き換える）。`scores` は SVM の決定関数の値で、確率ではない。位置（`lat`・`lon`・`accuracy_m`）は取れなかった窓では省く。

## 注意

- **署名付き URL のホスト**：署名にはホストが入る。`S3_PUBLIC_ENDPOINT` を、クライアントから見える名前にする（PC は `127.0.0.1`、Android エミュレーターは `10.0.2.2`）。エミュレーターから届かせるときは `HOST=0.0.0.0` でサーバーを起動し、ストレージの公開も合わせて変える必要がある（共有キーしか守りが無いので、普段はしない）。
- **チェックサム**：AWS SDK は、署名付き URL に「空のボディのチェックサム」を付けることがある。SeaweedFS では 400（`BadDigest`）になるので、`requestChecksumCalculation: "WHEN_REQUIRED"` にしている（`src/s3.ts`）。
- **MinIO は使わない**：コミュニティ版は、公式イメージの配布をやめ、リポジトリもアーカイブされた（2026-02）。
- ローカルで確かめていないこと：Lambda の起動の遅さ、PostgreSQL への同時接続の数、Lambda の 6 MB の上限（生データは署名付き URL で避けている）。本番に載せるときに確かめる。
