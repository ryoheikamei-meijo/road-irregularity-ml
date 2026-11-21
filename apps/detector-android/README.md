# 路面判定アプリ（detector-android）

スマホの上（エッジ）で、路面を flat / step / rough に判定するアプリ。計測用のアプリ（`../../MyApplication3`）とは別のもの。

- モデル：`models/<版>/core_svm.onnx`（core の 5 個の特徴量 + SVM）。版ごとに管理し、使う版は `gradle.properties` の `roaddetector.modelVersion` で選ぶ（[`models/README.md`](models/README.md)）。研究リポジトリの `src/experiments/e20261116_export_onnx.py` で書き出す
- 特徴量：`core/CoreFeatureExtractor.kt`。Python の基準の実装 `src/roadml/core_model.py` と同じ手順
- 判定：`core/OnnxClassifier.kt`（ONNX Runtime Android 1.32.0）
- 地図：`map/`（MapLibre Native Android 13.7.1 の OpenGL ES 版。タイルは OpenFreeMap の `positron`＝OSM のデータ、灰色の地図。登録・キー不要）。見た目の指定（style の URL）は `gradle.properties` の `roaddetector.mapStyleUrl`
- 経緯と結果：[`docs/knowledge/2026-11-16/20261116_onnx_edge_inference.md`](../../docs/knowledge/2026-11-16/20261116_onnx_edge_inference.md)

## ビルドとテスト

JDK 17 と Android SDK（`local.properties` の `sdk.dir`）が要る。

```sh
./gradlew :app:assembleDebug       # APK
./gradlew :app:installDebug        # つないだ端末に入れる
./gradlew :app:testDebugUnitTest   # PC の JVM で、Python と同じ判定になるかを確かめる
```

単体テストは、研究リポジトリの `wheelchair_data/` と `data/analysis/20261116_export_onnx/` を読む（無いときは飛ばす）。

## 使い方

アプリを開くと、**地図の画面**（`MainActivity`）が出る。
- 端末に残る判定結果を描く：段差は赤いピン（階段の絵）、凸凹は黄色い帯（濃い縁と点の模様）、通った道を線（今の走行は青、これまでの走行は灰色）
- 現在地：Google マップと同じく、青い丸・精度の円・向きの矢印で出す（MapLibre の現在地の表示 `LocationComponent`）。止まっているときも、画面を開いている間は出す。位置の権限が無いときに「現在地」を押すと、理由を説明してから許可を求める。位置がまだ取れていなければ、地図は動かさず「現在地を取得しています」と出す
  - 同じ判定が 3 窓以上続いたものを 1 つにまとめる（段差 1 か所・凸凹 1 区間。`MapData.events`）。段差のピンは、決定関数の値が最大の窓の位置に立てる。まとめ方の根拠は [`20261119_window_merge_design.md`](../../docs/knowledge/2026-11-19/20261119_window_merge_design.md)
  - 見せ方は、4 つの案をサンプルの画面で比べて選んだ（段差は一瞬なのでピン、凸凹は続く路面なので帯）
  - 地図の土台は灰色の `positron`。`liberty` は道路が黄色・橙で、段差・凸凹の色とぶつかったため
- 走行中は 1 秒ごとに今の走行を読み足し、今の位置を追う。指で地図を動かすと追うのをやめ、「現在地」で戻る
- 上のカードに、今の判定と、今回の走行の段差・凸凹の数。止まっているときは、これまでの走行の数
- カードの下のチップに、段差・凸凹の数（これまでと今回の合計）。押すと、地図に出す・隠すを切り替える（凡例を兼ねる。隠しているときは絵も消える）
- 「開発用」で、開発用の画面（`DevActivity`）を開く：決定関数の値、サンプリングの速さ、計算時間、「サーバーへ送る」のスイッチ、送信の状態、再生
- 画面の文言は日本語にそろえ（段差・凸凹・平坦）、見た目は Material Design 3 の部品で作る。文字は 16sp 以上、文字と背景のコントラストは 4.5:1 以上、地図の印は色に加えて形と絵でも区別する（段差は丸いピンに階段、凸凹は点の模様の帯）。日本語の文字・色・ボタンの決まりは、デジタル庁デザインシステムを参考にした（出典：デジタル庁デザインシステムウェブサイト https://design.digital.go.jp/dads/）。権限の許可の画面は OS が出すので、端末の言語に従う
- 描く内容（GeoJSON）は `map/MapData.kt` が作り、地図の土台に依存しない。Google マップに替えるときは `map/DetectionMap.kt` だけを差し替える

- 「判定を始める」：加速度と姿勢を約 333 Hz で受け取り、2.0 秒の窓を 0.5 秒ごとに判定する。記録は `/sdcard/Android/data/com.example.roaddetector/files/sessions/<日時>/` の `input.csv`（判定に使ったサンプル）と `judge.csv`（窓ごとの特徴量・判定・計算時間）
  - 判定はフォアグラウンドサービス（`DetectionService`。通知を出して動き続ける仕組み）で行う。**画面を消しても、ほかのアプリに切り替えても、判定・GPS・記録・送信が続く**。走行中は通知に窓の数と送信の状態が出て、通知の「止める」でも止められる。画面（`MainActivity`）は、`LiveStatus` で様子を受け取って出すだけ
  - 判定を始めるには、位置の権限が要る（地図に載せるため。Android 14 以降は、権限が無いと位置の種類のフォアグラウンドサービスを始められない）。無ければ、ボタンを押したときに求める。通知の権限（Android 13 以降）は無くても動くが、通知が出ない
  - 画面が消えても CPU が止まらないよう、走行中は wake lock を持つ（上限 6 時間）
- 「サーバーへ送る」のスイッチ（開発用の画面）：送信のオン・オフ（既定はオン）。切っている間も、判定結果と生データは端末に残る。入れ直すと、たまった分を送る（走行中なら 5 秒ごとの送信で、止めた走行は WorkManager で）
- 「記録済みのデータで PC と比べる（再生）」（開発用の画面）：デバッグ版に入れた 3 セッション（`app/src/debug/assets/replay/`）を同じ処理に流し、その版での PC の判定（`models/<版>/replay/`）と比べる
- adb から：`adb shell am start -n com.example.roaddetector/.MainActivity --ez replay true`（再生。開発用の画面を開いて流す）、`--ei live_s 60`（60 秒だけ判定）、`--ez upload false`（送信を切る。`true` で入れる）。開いている画面にも届く。結果は `adb logcat -s RoadDetector:I`
- 経緯：[`docs/knowledge/2026-11-19/20261119_android_map_plan.md`](../../docs/knowledge/2026-11-19/20261119_android_map_plan.md)

## 実機で走る

本番のサーバーはまだ無い。今の送り先（`10.0.2.2`）は実機からは届かないので、**「サーバーへ送る」を切って使う**。判定結果と生データは端末に残る。

1. 端末の「開発者向けオプション」で USB デバッグを入れ、PC につなぐ（`adb devices` に出ればよい）
2. `./gradlew :app:installDebug` で入れる
3. アプリを開き、「開発用」で「サーバーへ送る」を切る。地図の画面に戻り、「判定を始める」で、位置と通知の権限を許可する
4. 走ったあと、記録を PC に取り出す：`adb pull /sdcard/Android/data/com.example.roaddetector/files/sessions/<日時>`

## サーバーへの送信

判定結果と生データを、サーバー（[`apps/server`](../server/README.md)）に送る。経緯と決定は [`docs/knowledge/2026-11-18/20261118_local_server_plan.md`](../../docs/knowledge/2026-11-18/20261118_local_server_plan.md)。

- **判定結果**：走行中、5 秒ごとに、GPS の位置を付けて送る（どの回線でも）。つながらなければ端末に残し、次に送る。サーバーは「走行 ID + 窓の始まり」で重複を弾くので、再送しても二重にならない。
- **生データ（`input.csv`）**：走行を止めたあと、Wi-Fi など従量課金でない回線につながったとき、署名付き URL でストレージへ直接 PUT する（WorkManager。失敗したら間隔をあけてやり直す。アプリを起動したとき、送り終えていない走行も入れ直す）。
- `input.csv` の列：`timestamp,accX,accY,accZ,rotX,rotY,rotZ,rotW,gyroX,gyroY,gyroZ,wallMs`。ジャイロは判定に使わず、直近の値を残すだけ（読む側は列名で読むので、列を足しても壊れない）。`timestamp` は端末の起動からの ms で、`wallMs` が壁時計。
- 端末に残るもの（`sessions/<日時>/`）：`session.json`（走行の ID・登録済みか・生データを送り終えたか）、`detections.jsonl`（送る判定結果）、`detections.sent`（送れた件数）、`rejected.jsonl`（サーバーが不正と判断して退けたもの）。
- 送信を切っているとき：判定結果は `detections.jsonl` に残るが、走行の登録も送信もしない。生データのジョブ（WorkManager）も入れない（すでに入っていたものは、送らずに終える）。
- 設定：`gradle.properties` の `roaddetector.apiUrl`（既定は `http://10.0.2.2:8787`。エミュレーターから見た PC）と `roaddetector.apiKey`（開発用の共有キー）。実際に使うときは `-Proaddetector.apiKey=...` で上書きする。平文の HTTP は、`10.0.2.2`・`localhost` だけに許してある（`res/xml/network_security_config.xml`）。
- エミュレーターで試す：サーバーを `S3_PUBLIC_ENDPOINT=http://10.0.2.2:8333 npm run start` で起動し（署名にホストが入るため）、`adb shell pm grant com.example.roaddetector android.permission.ACCESS_FINE_LOCATION`、`adb emu geo fix <経度> <緯度>`、`adb shell am start -n com.example.roaddetector/.MainActivity --ei live_s 60`（`--ez upload true` で送信を入れておく）。
- 強制終了したとき、`input.csv` の末尾（書き込みのバッファの分。約 8 KB、約 0.25 秒）は残らない。判定結果（`detections.jsonl`）は 1 件ずつ書くので欠けない。
- 壊れたセンサーのサンプル（走り始めに届く、姿勢が全部 0 など）は、`CoreFeatureExtractor.push` が状態に触れずに捨てる（NaN が傾きの基準に入ると、その走行の傾きが以後ずっと NaN になるため）。
