# Process

## 2026-06-22

- Android appに `MISS` ボタンを追加した。
- `START` でセッション開始、`STOP` で `success`、`MISS` で `failed/button_miss` を記録するようにした。
- 計測中に `CLEAR` した場合も `failed/cleared` としてセッション終了するようにした。
- セッションごとの結果を `csv/<session_id>/session_result.csv` に保存する仕組みを追加した。
- 全セッションを一覧できる `csv/sessions_index.csv` への追記処理を追加した。
- `./gradlew assembleDebug` でビルド確認を行った。

## 2026-07-03

- 車椅子利用者の体重が段差・でこぼこ計測に影響するため、体重を記録できるようにした。
- 画面に「体重設定」ボタンと体重表示（`weightTextView`）を追加した。
- ボタン押下で数字（小数可）のみ入力できるダイアログを表示し、0kg以下・300kg超は保存せずエラー表示するようにした。
- 入力した体重は `SharedPreferences` に保存し、アプリ再起動後も前回値を引き継ぐようにした。
- `START` を押した時点の体重をそのセッションの値として確定し、`SessionResultLogger` の `session_result.csv` / `sessions_index.csv` に `weight_kg` カラムとして保存するようにした。
- `./gradlew assembleDebug` でビルド確認を行った。
