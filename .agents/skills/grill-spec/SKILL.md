---
name: grill-spec
description: Use when a written spec or design document should be adversarially interrogated, and PROACTIVELY propose it before implementing from a spec that has not been interrogated yet - surfacing ambiguity, contradictions, undefined behavior, and implicit assumptions as prioritized questions, interviewing the user, and reflecting resolutions back into the document.
---

# Grill Spec

書かれた仕様・設計文書(docs 配下の設計文書、issue 内の仕様記述、README の
仕様節など)を敵対的に尋問し、曖昧さ・矛盾・未定義動作・暗黙前提を質問として
ユーザーに解消してもらい、結果を文書へ反映するための正本。

## 使うとき / 使わないとき

使うとき:

- 仕様・設計文書の執筆後、実装着手前の自己点検
- 文書を根拠に実装へ入る前の、AI と人間の認識合わせ

使わないとき:

- まだ文書になっていないアイデア・依頼
  - 正本は `.claude/skills/grill-me/SKILL.md`
- 実装後の変更レビュー
  - 通常のコードレビューで扱う

## 尋問パス(観点)

文書を順に読みながら、最低 1 巡は以下を疑う:

- 観測可能性: 各要求・完了条件は、満たされたかどうかを観測できる書き方に
  なっているか
- 境界と端境ケース: 空・上限・同時・時刻境界・繰り返しの端で挙動が
  割れないか
- 失敗系: エラー・縮退・認証・オフラインなどの分岐が固定されているか
- 用語整合: 用語がプロジェクト内の既存定義と一致しているか
- 決定整合: 既存 ADR・既存文書と矛盾しないか
- blindspot pass: 明文化されていない暗黙のドメイン制約・運用制約・
  端境ケース(未知の未知)を最低 1 巡探す
- 非目標: 「やらないこと」が書かれているか。scope が滲む余地はないか

## 進め方

1. findings-first で指摘を列挙し、各指摘に文書の該当セクション・行の根拠を
   添える。**指摘の列挙は一括でよい**。指摘は読む側への情報であり、決定を
   求めていないため。一覧は会話に出す(issue コメントや subagent の中だけで
   済ませない)。
2. 指摘を blocker / non-blocker に分類する。
   - blocker: 実装前に決めないと挙動が割れる。
   - non-blocker: 実装と並行して追跡できる。issue 化して閉じてよい。
3. blocker を決定木に並べ替え、`grill-me` の「尋問の原則」でユーザーに
   解消してもらう。規約はここに複製しない。本 skill 固有の注意は 1 点だけ:
   **列挙が一括でも、決定を求める質問は指摘の数だけ並べない**(指摘 1 件 =
   質問 1 件ではない)。blocker が多い(目安 8 件超)なら、先に根の前提を
   1 問だけ聞いて剪定する。
4. 終了条件も `grill-me` に従う。終了時に解消結果、剪定した指摘とその理由、
   残存 non-blocker を要約し、まとめへの明示の合意を得てから実装に進む
   (文書への反映は反映契約に従い回答ごとに済ませ、合意まで「未確定」とする)。

## 反映契約

- 回答は対象文書本文へ即時反映し、会話ログだけに結論を残さない。まとめへの
  明示の合意までは反映した記述に「未確定」の札を付け、合意で札を外す。
- 未確定は issue 化するか、対象文書の Open Questions 節に明示して追跡する。
- ラウンドをまたぐ・中断する場合の決定木の checkpoint は `grill-me` の
  反映契約に従う(未解決の指摘・依存・調査待ちを issue / Open Questions 節へ
  残せば、後続セッションが frontier を再構成できる)。
- 再開時は [`grill-me` の「中断・引き継ぎ後の再開」](../grill-me/SKILL.md#中断引き継ぎ後の再開)
  に従い、checkpoint の未解決判断をユーザーとの現在の会話へ戻す。
- 長く効く判断に触れる結論が出たら、`manage-adrs` skill の ADR 要否判定へ
  接続する。

## 関連

- `.claude/skills/grill-me/SKILL.md`(尋問の原則の正本)
- `.claude/skills/manage-adrs/SKILL.md`(ADR 要否判定・作成)
