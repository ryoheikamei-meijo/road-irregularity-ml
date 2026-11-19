# サーバー・TypeScript 版（apps/server-ts、凍結中）

> **凍結中（2026-11-18）**：サーバーは Kotlin 版（[`apps/server`](../server/README.md)）に移した。
> - **残す理由**：研究室のサーバーに JVM を置けない場合の予備として残している。
> - **API**：2026-11-18 の時点の API のまま。新しい API（地図の読み出しなど）は足さない。
> - **使うとき**：Kotlin 版に追いつかせてから使う。
> - **経緯**：[`docs/knowledge/2026-11-18/20261118_server_kotlin_snapstart.md`](../../docs/knowledge/2026-11-18/20261118_server_kotlin_snapstart.md)

アプリが判定した結果と、走行後の生データを受けて保存する API。API の形・DB の表・マイグレーションは、Kotlin 版と同じ。経緯と決定は [`docs/knowledge/2026-11-18/20261118_local_server_plan.md`](../../docs/knowledge/2026-11-18/20261118_local_server_plan.md)。

- API：TypeScript（strict）+ [Hono](https://hono.dev) + Zod
- DB：PostgreSQL（`migrations/*.sql`。Kotlin 版と同じ内容）
- 生データ：S3 互換のストレージに、**署名付き URL で直接 PUT**する（API は通さない）。ローカルは SeaweedFS
- 構成図は Kotlin 版の README の「[構成](../server/README.md#構成)」（API の部分を TypeScript + Hono に読み替える）

## 動かし方

JDK は要らない。Node.js 22 以上と Docker が要る。

```sh
cd apps/server-ts
npm install
cp .env.example .env     # 開発用の値。.env は git に入れない
npm run up               # PostgreSQL と S3 互換のストレージを立てる（127.0.0.1 だけに公開）
npm run migrate          # 表を作る
npm run dev              # http://127.0.0.1:8787
npm test                 # 結合テスト（上の 2 つに実際につなぐ。専用のスキーマとバケットを使う）
npm run typecheck
npm run down             # 止める（データは残る。消すなら docker compose down -v）
```

PC から記録済みの走行を送って、保存を確かめる（`API_URL` を付けると、Kotlin 版など別のサーバーにも送れる）：

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
- **DB とストレージは Kotlin 版と共有**：`compose.yaml` のプロジェクト名を同じ（`server`）にしているので、同じコンテナとデータを使う。同時に動かすときは、ポートを分ける（`PORT=8788 npm start`）。
- **チェックサム**：AWS SDK は、署名付き URL に「空のボディのチェックサム」を付けることがある。SeaweedFS では 400（`BadDigest`）になるので、`requestChecksumCalculation: "WHEN_REQUIRED"` にしている（`src/s3.ts`）。
- **MinIO は使わない**：コミュニティ版は、公式イメージの配布をやめ、リポジトリもアーカイブされた（2026-02）。
- ローカルで確かめていないこと：Lambda の起動の遅さ、PostgreSQL への同時接続の数、Lambda の 6 MB の上限（生データは署名付き URL で避けている）。本番に載せるときに確かめる。
