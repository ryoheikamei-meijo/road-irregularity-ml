# Title
<type(scope): PR title>

## Summary

<この PR が何をするか。責務範囲と後続フェーズとの境界があればここで明記する。>

## Background / Why

- <この変更が必要になった背景>
- <今回の責務として切り出した理由>
- <既存バグや制約があればその説明>

## Changes

### feat

- `<path/to/file>`: <追加した機能や責務>
- `<path/to/file>`: <追加した機能や責務>

### refactor

- `<path/to/file>`: <切り出しや責務整理の内容>

### fix

- `<path/to/file>`: <修正した不具合や制約>

## Implementation Notes

- <非自明な仕様、優先順位、データフロー、識別子ルールなど>
- <後続フェーズが参照する戻り値や状態遷移があれば記載>

## Testing

- `<path/to/test-file>`: <何を検証したか>
- `<command>`: <実行した確認内容>
- 未実施の確認があれば明記: <理由>

## Impact / Risk

- <設定値や環境変数に依存する挙動>
- <互換性やデータ影響>
- <未実装の後続対応があれば記載>

## Local Verification

<再現手順が不要なら、この節ごと削除する。>

<details>
<summary>動作確認手順</summary>

### 前提データ

| テーブル | 必要なレコード |
|---|---|
| `<table_name>` | `<必要な前提データ>` |
| `<table_name>` | `<必要な前提データ>` |

### 補助 SQL

```sql
-- 必要な場合だけ残す
<insert or update statements>
```

### 実行コマンド

```bash
<curl or test command>
```

### 期待結果

```json
<expected response>
```

<DB 更新やログ確認など、追加で見るべきポイントがあれば 1-2 行で書く。>

</details>
