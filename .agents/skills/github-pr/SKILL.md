---
name: github-pr
description: "このリポジトリ向けの非公開 PR 本文テンプレートを使って、ドラフト本文を日本語で整えるスキル。Summary / Background / Changes / Testing / Impact / Local Verification を定型で埋めたいときに使う。"
---

# Skill: GitHub PR Private Template

`github-pr` は、このリポジトリで使う PR 本文テンプレートを安定して埋めるためのスキル。

## When To Use

- ユーザーが PR 本文の draft 作成や整形を求めたとき
- 既存のメモや差分から、プロジェクト標準の章立てへ落とし込みたいとき
- Local Verification や Background / Why を含む、日本語の詳細 PR 本文が必要なとき

## Required Read

- [assets/pr-body-template.md](./assets/pr-body-template.md)

## Workflow

1. ユーザーが渡したドラフト、差分、PR タイトル案から事実を集める
2. `assets/pr-body-template.md` を開き、各プレースホルダを今回の PR 用に置き換える
3. セクションは原則維持し、不要な節だけを削る
4. `Changes` は `feat` / `refactor` / `fix` など意味のある単位で整理する
5. `Testing` は実行した確認だけを書く。未実施なら明記する
6. `Local Verification` は再現手順があるときだけ残し、不要なら節ごと落とす

## Writing Rules

- 本文は日本語で書く
- `Summary` は 1 段落で、PR の責務範囲を先に示す
- `Background / Why` は意思決定の理由と責務分離を優先して書く
- `Changes` はファイル列挙だけで終わらせず、レビュー観点が分かる粒度にする
- `Implementation Notes` は読む価値のある非自明な仕様だけを書く
- `Impact / Risk` は設定依存、互換性、未完了の後続フェーズを明記する
- SQL や curl の例は、その PR を読む人がローカル再現に使う場合だけ含める

## Do Not Do

- テンプレートの見出し構成を毎回大きく変える
- 実施していないテストを書く
- `Changes` をコミットログの貼り付けにする
- 下書きメモの生 SQL や断片情報を、そのまま本文に残す
