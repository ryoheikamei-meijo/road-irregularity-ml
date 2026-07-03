# Process

## 2026-06-22

- Android appに `MISS` ボタンを追加した。
- `START` でセッション開始、`STOP` で `success`、`MISS` で `failed/button_miss` を記録するようにした。
- 計測中に `CLEAR` した場合も `failed/cleared` としてセッション終了するようにした。
- セッションごとの結果を `csv/<session_id>/session_result.csv` に保存する仕組みを追加した。
- 全セッションを一覧できる `csv/sessions_index.csv` への追記処理を追加した。
- `./gradlew assembleDebug` でビルド確認を行った。
