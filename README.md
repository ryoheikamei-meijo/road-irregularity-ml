# Road Irregularity ML

手動式車椅子走行時の加速度データを用いて，路面凹凸を検知するための機械学習実験用リポジトリ．

## Environment

Python 3.13 を使用する．

## Setup

```bash
uv sync
```

`pyproject.toml` の `project.scripts` で定義したコマンドを使う前提のため，依存関係を追加・更新した後は `uv sync` を実行する．

## Workflow

```bash
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 43
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 42
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 45

uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152209_seed43/mock_acc_only.csv
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152216_seed42/mock_acc_only.csv
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152641_seed45/mock_acc_only.csv

uv run train-dummy --config configs/svm.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv
```

1回の実験は `raw -> features -> train/eval` の順で進める．  
train 用 run と eval 用 run は seed を分けて生成する．

## Wheelchair World-Frame Workflow

`knowledge/6.30/plan.md` に沿った実測データ用の新パイプラインでは，
`wheelchair_data/6.22/analysis/world_csv/*/acc_world.csv` を入力に使う．
`accWorldZ` から重力成分 `9.80665` を引いた `world_z_linear` を特徴量化対象とする．

```bash
uv run build-wheelchair-dataset --config configs/wheelchair_world_z_svm.yaml

uv run train-wheelchair-model --config configs/wheelchair_world_z_svm.yaml \
  --input data/features/20260630120000/wheelchair_world_z_dataset.csv \
  --train-run-id 20260622175452 \
  --train-run-id 20260622180411 \
  --train-run-id 20260622180835 \
  --train-run-id 20260622181304 \
  --train-run-id 20260622182112 \
  --train-run-id 20260622182312 \
  --eval-run-id 20260622182555 \
  --eval-run-id 20260622182658 \
  --eval-run-id 20260622182908 \
  --eval-run-id 20260622183215 \
  --eval-run-id 20260622183356
```

このパイプラインでは 1.0 秒窓・0.25 秒ストライドで window を切り，
`dansa.csv` / `dekobo.csv` との重なり率 0.5 以上を用いて
`dansa > dekobo > flat` の優先順でラベル付けする．
特徴量は `z_range`, `z_diff_max`, `z_rms`, `z_std` の 4 つを使う．

## Generate Mock Sensor Logs

```bash
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 43
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 42
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 45
uv run generate-mock-data --config configs/mock_data_with_gyro.yaml
```

生成される CSV は 1 行 1 サンプルの時系列ログで，`include_gyro` に応じて `gyro_*` 列の有無が切り替わる．
出力先は毎回 `data/raw/YYYYMMDDHHMMSS_seedN/` を新規作成し，その配下に `mock_acc_only.csv` か `mock_with_gyro.csv` を保存する．
ラベル定義は `0=平坦`, `1=段差`, `2=粗さ` とする．
ラベル列は固定順ではなく，ある程度の継続時間を持ったランダム遷移で生成する．
`--seed` を指定すると `mock_data.random_state` を CLI から上書きできるため，train 用と eval 用で別runを作り分けられる．

## Extract Sliding-Window Features

```bash
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152209_seed43/mock_acc_only.csv
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152216_seed42/mock_acc_only.csv
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152641_seed45/mock_acc_only.csv
```

2.0秒窓，1.0秒ストライドで加速度3軸を分割し，各windowについて `mean`, `rms`, `var`, `max`, `min` を算出する．
windowラベルは `1 > 2 > 0` の優先ルールで決め，窓内に `1` が1つでもあれば `1`，`1` がなく `2` があれば `2`，それ以外は `0` とする．
出力先は毎回 `data/features/YYYYMMDDHHMMSS_seedN/` を新規作成し，その配下に `mock_acc_only_features_seedN.csv` を保存する．

## Train And Evaluate

```bash
uv run train-dummy --config configs/svm.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv

uv run train-dummy --config configs/random_forest.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv
```

特徴量CSVの `label` を目的変数にし，`window_id`, `window_start_ms`, `window_end_ms`, `n_samples` を除いた特徴量列を学習に使う．
`--train-input` を学習元，`--eval-input` を精度評価用データとして扱い，複数の評価用CSVを順に評価できる．
評価結果は毎回 `data/processed/YYYYMMDDHHMMSS/` を新規作成し，その配下に eval元ごとの classification report と confusion matrix を保存する．

## Dependency Management

依存関係のインストールは通常 `uv sync` を使う．  
`uv add ...` は利用者向けの通常手順ではなく，依存関係を追加・更新するメンテナンス時にだけ使う．

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
