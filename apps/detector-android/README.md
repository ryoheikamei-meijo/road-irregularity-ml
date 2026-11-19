# 路面判定アプリ（detector-android）

スマホの上（エッジ）で、路面を flat / step / rough に判定するアプリ。計測用のアプリ（`../../MyApplication3`）とは別のもの。

- モデル：`models/<版>/core_svm.onnx`（core の 5 個の特徴量 + SVM）。版ごとに管理し、使う版は `gradle.properties` の `roaddetector.modelVersion` で選ぶ（[`models/README.md`](models/README.md)）。研究リポジトリの `src/experiments/e20261116_export_onnx.py` で書き出す
- 特徴量：`core/CoreFeatureExtractor.kt`。Python の基準の実装 `src/roadml/core_model.py` と同じ手順
- 判定：`core/OnnxClassifier.kt`（ONNX Runtime Android 1.32.0）
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

- 「判定を始める」：加速度と姿勢を約 333 Hz で受け取り、2.0 秒の窓を 0.5 秒ごとに判定する。記録は `/sdcard/Android/data/com.example.roaddetector/files/sessions/<日時>/` の `input.csv`（判定に使ったサンプル）と `judge.csv`（窓ごとの特徴量・判定・計算時間）
- 「記録済みのデータで PC と比べる（再生）」：デバッグ版に入れた 3 セッション（`app/src/debug/assets/replay/`）を同じ処理に流し、その版での PC の判定（`models/<版>/replay/`）と比べる
- adb から：`adb shell am start -n com.example.roaddetector/.MainActivity --ez replay true`（再生）、`--ei live_s 60`（60 秒だけ判定）。結果は `adb logcat -s RoadDetector:I`

## サーバーへの送信

判定結果と生データを、サーバー（[`apps/server`](../server/README.md)）に送る。経緯と決定は [`docs/knowledge/2026-11-18/20261118_local_server_plan.md`](../../docs/knowledge/2026-11-18/20261118_local_server_plan.md)。

- **判定結果**：走行中、5 秒ごとに、GPS の位置を付けて送る（どの回線でも）。つながらなければ端末に残し、次に送る。サーバーは「走行 ID + 窓の始まり」で重複を弾くので、再送しても二重にならない。
- **生データ（`input.csv`）**：走行を止めたあと、Wi-Fi など従量課金でない回線につながったとき、署名付き URL でストレージへ直接 PUT する（WorkManager。失敗したら間隔をあけてやり直す。アプリを起動したとき、送り終えていない走行も入れ直す）。
- `input.csv` の列：`timestamp,accX,accY,accZ,rotX,rotY,rotZ,rotW,gyroX,gyroY,gyroZ,wallMs`。ジャイロは判定に使わず、直近の値を残すだけ（読む側は列名で読むので、列を足しても壊れない）。`timestamp` は端末の起動からの ms で、`wallMs` が壁時計。
- 端末に残るもの（`sessions/<日時>/`）：`session.json`（走行の ID・登録済みか・生データを送り終えたか）、`detections.jsonl`（送る判定結果）、`detections.sent`（送れた件数）、`rejected.jsonl`（サーバーが不正と判断して退けたもの）。
- 設定：`gradle.properties` の `roaddetector.apiUrl`（既定は `http://10.0.2.2:8787`。エミュレーターから見た PC）と `roaddetector.apiKey`（開発用の共有キー）。実際に使うときは `-Proaddetector.apiKey=...` で上書きする。平文の HTTP は、`10.0.2.2`・`localhost` だけに許してある（`res/xml/network_security_config.xml`）。
- エミュレーターで試す：サーバーを `S3_PUBLIC_ENDPOINT=http://10.0.2.2:8333 ./gradlew run`（`apps/server` で）で起動し（署名にホストが入るため）、`adb shell pm grant com.example.roaddetector android.permission.ACCESS_FINE_LOCATION`、`adb emu geo fix <経度> <緯度>`、`adb shell am start -n com.example.roaddetector/.MainActivity --ei live_s 60`。
- 強制終了したとき、`input.csv` の末尾（書き込みのバッファの分。約 8 KB、約 0.25 秒）は残らない。判定結果（`detections.jsonl`）は 1 件ずつ書くので欠けない。
- 壊れたセンサーのサンプル（走り始めに届く、姿勢が全部 0 など）は、`CoreFeatureExtractor.push` が状態に触れずに捨てる（NaN が傾きの基準に入ると、その走行の傾きが以後ずっと NaN になるため）。
