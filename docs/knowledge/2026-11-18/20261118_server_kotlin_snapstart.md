# サーバーを Kotlin に移す（Lambda SnapStart 前提）

TypeScript で作ったサーバー（[`20261118_local_server_plan.md`](20261118_local_server_plan.md)）を、アプリと同じ Kotlin に移しました。本人から「Lambda の SnapStart を使えば Kotlin でも無料でできるらしい。言語をそろえたい」という提案があり、調べてから `/grill-me` で決めました。

**状態**：合意済み（2026-11-18）、実施済みです。

**結果**
- テスト 26 件が通りました。
- TypeScript 版と、54 通りの入力で振る舞いが一致しました。
- エミュレーターでの通し確認 A・B・C で、端末・DB・S3 が一致しました。
- SnapStart そのものは、AWS のアカウントができてから確かめます。

## 調べたこと

- **SnapStart の仕組み**：SnapStart は、初期化が終わった時点のメモリをスナップショットにしておき、そこから起動する機能です。JVM の起動の遅さを補います。
- **対応するランタイム**：Java 11 以降、Python 3.12 以降、.NET 8 以降です。Kotlin は JVM の上で動くので、java21 で使えます。
  - Node.js は対象外です。
  - 2026-09 から、コンテナイメージにも対応しています。
- **料金**：Java のランタイムでは、SnapStart に追加料金がかかりません。Python と .NET では、スナップショットのキャッシュと、そこから戻す処理に料金がかかります。
- **費用は、言語を選ぶ理由にならない**：「無料」とは、SnapStart を足しても料金が増えないという意味です。Node.js より安くなるわけではありません。
  - Lambda の無料枠は、毎月 100 万リクエストと 400,000 GB 秒です。
  - 判定結果は 5 秒ごとに送ります。月に 10 時間走っても約 7,200 リクエストです。TypeScript でも Kotlin でも、無料枠に十分収まります。
  - 費用が大きくなるのは、DB（RDS）の側だと思います（推測。新しい無料枠の条件は確かめていません）。
- **使うときの注意**（AWS のドキュメント）
  - 初期化中に張ったネットワークの接続は、スナップショットから戻したあとに使えるとは限りません。AWS SDK の接続は、自動で張り直されます。
  - SnapStart は、公開したバージョンと、それを指すエイリアスにしか効きません（`$LATEST` には効きません）。
  - 初期化中に作った一意の値や乱数は、戻したすべての実行環境で同じ値になります。
  - プロビジョンド同時実行、EFS、512 MB を超えるエフェメラルストレージとは併用できません。

出典
- [Improving startup performance with Lambda SnapStart（AWS ドキュメント）](https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html)
- [AWS Lambda の料金](https://aws.amazon.com/lambda/pricing/)
- [コンテナイメージ対応の告知（2026-09-02）](https://aws.amazon.com/about-aws/whats-new/2026/07/aws-lambda-snapstart-container/)

料金のページのうち、SnapStart の節は、取得した本文の要約で確かめました。原文をそのまま読んだわけではありません。

## 決めたこと（`/grill-me`）

| 問い | 決定 | 理由 |
| --- | --- | --- |
| 地図を出す場所 | Android アプリの中 | 最初の依頼が「エッジ側でマップを作成」だったため。これで、TypeScript を選んだ理由（地図の Web と言語がそろう）がなくなった |
| 移すか・いつ | いま移す（地図の作業より前） | 地図で、サーバーから読む API が増える。移すなら、その前のほうが安く済む |
| フレームワーク | http4k（Apache-2.0） | 同じコードを、PC では普通のサーバー（Jetty）、Lambda では公式の入口（API Gateway v2）で動かせる。余分な拡張を挟まない。Ktor には Lambda 向けの公式の入口がなく、Lambda Web Adapter（拡張）が要る |
| TypeScript 版 | `apps/server-ts` に凍結して残す。新しい API は足さない | 研究室のサーバーに置くことになるかもしれないため（本人）。Kotlin 版も普通のサーバーとして動くので、TypeScript 版が要るのは JVM を置けない場合だけ |
| 置き場所 | Kotlin 版を `apps/server` に、TypeScript 版を `apps/server-ts` に | 主になる方を `apps/server` にする |
| Lambda の入口 | 今回作り、PC でイベントを入れて試す | http4k なら数行で書ける。SnapStart そのものは AWS で確かめる |
| アプリとの型の共有 | 今回はしない | 動いているアプリの送信部分に触らない。地図で読み出しの型が増えるときに、まとめて考える |

実装の細かいところは、作るときに決めました。
- **JSON**：kotlinx.serialization の JSON の木を、手書きで検証します。
- **DB**：JDBC と HikariCP を使います。
- **S3**：AWS SDK v2 を使います。HTTP クライアントは、JDK の軽いもの（`url-connection-client`）にしました。

## やったこと

- **`apps/server`（Kotlin）**：Gradle 9.9.1、Kotlin 2.4.21、http4k 6.61.0.0、JDK 21 です。
  - JDK 21 は、Gradle の toolchain で取ってきます。http4k 6 は Java 21 向けにビルドされていて、JDK 17 では動きません。
  - **`App.kt`**：API の本体です。PC と Lambda の両方から使います。
  - **`Schemas.kt`**：入力の検証です。規則は Zod と同じにしました（知らないキーは無視、任意の項目の `null` は間違い、整数は ±2^53 − 1 まで、間違いの場所は `detections.0.lat` の形）。
  - **`Db.kt`**：初めて使うときに DB につなぎます。マイグレーションの記録は、TypeScript 版と同じ `schema_migrations` の表を使います。
  - **`Storage.kt`**：S3 です。チェックサムは `WHEN_REQUIRED` にしました。
  - **`Main.kt`**：PC 用の入口です。
  - **`LambdaHandler.kt`**：Lambda 用の入口です。
  - **`build.gradle.kts`**：`run`・`migrate` タスクは `.env` を読みます。`lambdaZip` タスクで、Lambda に上げる zip を作ります。
- **そのまま引き継いだもの**：`migrations`、`compose.yaml`、`dev/s3.json`、`.env.example`、構成図です。
- **`compose.yaml`**：両方の版で、プロジェクト名を `server` に固定しました。同じコンテナとデータを使うためです。
- **構成図**：API のロゴを Kotlin・OpenJDK・Eclipse Jetty にし、Lambda を java21・SnapStart にしました。使わなくなった TypeScript・Hono・Node.js・Zod のロゴは消しました。
- **アプリ**：動きは変えていません。README の起動コマンドと、サーバーのスキーマの場所を指すコメント 2 か所だけを直しました。

## 結果

| 確認 | 結果 |
| --- | --- |
| テスト（`./gradlew test`、本物の PostgreSQL と SeaweedFS） | ○ 26 件。TypeScript 版の 15 件と同じ項目、Lambda の入口 3 件、入力の検証 8 件 |
| TypeScript 版と同じ振る舞いか | ○ 両方を立てて、同じ 54 通りの入力（境目の値、`null`、`1000.0`、2^60、片方だけの位置、複数の間違いなど）を送った。ステータスと返事（エラーの種類、間違いの場所）がすべて一致 |
| 送信スクリプト（`npm run send` を Kotlin 版に向ける） | ○ 235 窓、6.2 MB。件数とクラスの一致、再送で二重にならない、ハッシュの一致の 3 つとも OK |
| Lambda の入口 | ○ API Gateway（形式 2.0）と同じ形のイベントで、登録・保存・401 を確認。つながらない DB を指定しても入口は作れ、リクエストで初めて 500 になる（初期化で DB につながない） |
| Lambda の zip | ○ 18 MB（上限は直接アップロードで 50 MB、展開後 250 MB） |
| エミュレーター A：60 秒の走行の途中でサーバーを止めて戻す | ○ 116 窓。欠け 0・余り 0、生データの sha256 も端末・DB・S3 で一致 |
| エミュレーター C：走行が終わったあとも止めておく | ○ 76 窓（走行の終わりで送れていたのは 18 窓）。WorkManager が 30 秒・60 秒あけてやり直し、3 回目で完了 |
| エミュレーター B：止まったまま強制終了し、戻してから起動 | ○ 39 窓。登録できていなかった走行を起動時に登録し直し、全部送れた |
| （偶然）走行中に、エミュレーターの OS ごと再起動 | ○ サーバーの側の欠けは 0、二重も 0。下の「分かったこと」を参照 |

## 分かったこと

- **http4k は、Lambda の応答の本文を常に base64 で返す**（`isBase64Encoded: true`）。API Gateway が元に戻すので、クライアントには影響がありません。
- **OS ごと突然止まると、端末の `detections.jsonl` の末尾が NUL バイトになる**（シナリオ A の 1 回目で、エミュレーターが走行中に再起動しました）。
  - **何が消えたか**：書いた内容がディスクに届く前に OS が止まり、最後の 2 窓が端末から消えました。
  - **サーバーの側**：この 2 窓は、消える前にサーバーへ送れていたので、サーバーには残っています。
  - **アプリの動き**：NUL の行は、アプリが送ったところサーバーが 400 で退けました。アプリは、これを不正な 1 件として `rejected.jsonl` に分けました。
  - **残るリスク**：送る前に OS が止まった窓は、どこにも残りません。アプリの強制終了では起きず、OS が止まったときだけ起きます。直すなら、1 件ごとに `fsync` することになります（未対応）。
- **JDK**：手元の JDK は 17 です。`./gradlew run` は、toolchain の JDK 21 で動きます。ビルドした実行ファイル（`installDist`）を直接動かすときは、`JAVA_HOME` を JDK 21 にする必要があります。

## 残る未確定

- **AWS で確かめること**：SnapStart での実際の起動時間、戻した直後の DB 接続の速さ、Lambda から PostgreSQL への同時接続の数（RDS Proxy が要るか）。
- **zip の中身**：Lambda の zip に、PC 用の Jetty も入っています。重さが問題になったら分けます。
- **ADR にするか**：「Lambda + PostgreSQL + 署名付き URL」と、「サーバーは Kotlin」をまとめて ADR にするかは、まだ決めていません。
