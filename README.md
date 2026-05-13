# Road Irregularity ML

手動式車椅子走行時の加速度データを用いて，路面凹凸を検知するための機械学習実験用リポジトリ．

## Environment

Python 3.13 を使用する．

## Setup

```bash
uv sync
```

`pyproject.toml` の `project.scripts` で定義したコマンドを使う前提のため，依存関係を追加・更新した後は `uv sync` を実行する．

## Install dependencies

```bash
uv add numpy pandas scipy scikit-learn matplotlib pyyaml
uv add --dev ruff pytest ipykernel
```

## Run dummy training

```bash
uv run train-dummy --config configs/svm.yaml
uv run train-dummy --config configs/random_forest.yaml
```

## Generate mock sensor logs

```bash
uv run generate-mock-data --config configs/mock_data_acc_only.yaml
uv run generate-mock-data --config configs/mock_data_with_gyro.yaml
```

生成される CSV は 1 行 1 サンプルの時系列ログで，`include_gyro` に応じて `gyro_*` 列の有無が切り替わる．
出力先は毎回 `data/raw/YYYYMMDDHHMMSS/` を新規作成し，その配下に `mock_acc_only.csv` か `mock_with_gyro.csv` を保存する．
ラベル定義は `0=平坦`, `1=段差`, `2=粗さ` とする．
ラベル列は固定順ではなく，ある程度の継続時間を持ったランダム遷移で生成する．

## Notes

- data/raw/，data/processed/，data/features/ はGit管理しない．
- 実験データには位置情報が含まれる可能性があるため，GitHubには原則アップロードしない．

## Branch naming

- 新機能は `feat/xxxxx`
- バグ修正は `fix/xxxxx`
- 挙動を変えない整理は `refactor/xxxxx`
- ドキュメント更新は `docs/xxxxx`
- 設定変更や依存更新などの雑務は `chore/xxxxx`
- テスト追加や整理は `test/xxxxx`
- `xxxxx` は英小文字の kebab-case を使う
- 例: `feat/mock-data-generator`, `fix/mock-output-path`, `docs/mock-data-spec`

## Commit message

- 形式は `type(scope): summary` を基本とする
- `type` は `feat`, `fix`, `refactor`, `docs`, `chore`, `test` を使う
- `scope` は対象領域を短く書く
- `summary` は日本語で簡潔に書く
- 例: `feat(mock-data): ジャイロON/OFF対応のモックデータ生成を追加`
- 例: `fix(output): モックCSVをタイムスタンプ付きディレクトリに保存するよう修正`
- 例: `docs(readme): ブランチ名とコミットメッセージの運用ルールを追記`
