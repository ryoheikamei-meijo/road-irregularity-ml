# セッションの情報

測定日ごとに 1 つの CSV（`<日付>.csv`、`wheelchair_data/<日付>/` に対応）。`wheelchair_data/` は git の管理外なので、セッションの情報はここに残す。

| 列 | 値 | 意味 |
| --- | --- | --- |
| `session_id` | `yyyyMMddHHmmss` | セッションのフォルダ名 |
| `kind` | `flat` / `step` / `rough` | そのセッションを何のために測ったか |
| `wheelchair` | `original` / `standard` | 使った車椅子（元々使っていた車椅子 / 新しく買った汎用の車椅子）。基本は `session_result.csv` の `wheelchair` と同じ。記録ミスを直したときは、こちらが正しい（`note` に書く） |
| `weight_kg` | kg | 車椅子に乗った人の体重。基本は `session_result.csv` の `weight_kg` と同じ。入力間違いを直したときは、こちらが正しい（`note` に書く） |
| `use` | `yes` / `no` | 解析に使うか。`no` の理由は `note` に書く |
| `note` | 自由記述 | 測定時の状況や、データの気になる点 |

- `flat` のセッションには、段差・でこぼこのボタンの記録（`dansa.csv`・`dekobo.csv`）が無い。今の解析コードは「ボタンの記録が無い = flat」とみなしているが、ボタンの押し忘れと区別できないので、この表で明示する。
- `weight_kg`・`use` は 2026/11/1 に追加した列。10.31 はすべて 68 kg（同じ人。11.1 のアプリでは 69 kg と記録している）。
- 10.31 の解析スクリプトは `session_id`・`kind`・`wheelchair` だけを読み、`use` は見ていない（除くセッションは `--exclude` などで指定している）。
