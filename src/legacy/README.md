# legacy（2026-05〜09 の古いパイプライン）

今の解析（10.3 以降、約 334Hz のデータ）では使っていないが、過去のメモ（`docs/knowledge/2026-05-13`〜`2026-09-09`）の結果を再現するために残しているコード。

| 対象 | 中身 |
| --- | --- |
| `scripts/generate_mock_data.py`・`extract_features.py`・`train_dummy.py` | モックデータでのパイプライン（2026-05） |
| `wheelchair_pipeline.py`・`scripts/build_wheelchair_dataset.py`・`scripts/train_wheelchair_model.py` | 6.22・7.12 の実測（約 4Hz）の `world_z_linear` パイプライン（2026-06〜07） |
| `analysis/`・`scripts/analyze_*.py` | 6.22・7.12 のデータの分析（2026-07〜09） |
| `scripts/plot_world_z_crops.py`・`scripts/plot_flat_event_boxplots_622.py` | 6.22 の発表用の図 |
| `config.py`・`models.py` | 上のパイプラインの設定の読み込みとモデル |

- 設定ファイルは `configs/legacy/` にある。
- コマンド（`uv run generate-mock-data` など）は `pyproject.toml` の `project.scripts` に残している。
- `src/experiments/e20261004_boxplots.py`・`e20261004_boxplots_extra.py` は、ここの描画関数（`analysis/flat_event.py`・`analysis/jerk_event.py`）を使っている。

## 以前の README の手順（2026-10-18 に移動）

パスは、移動後のもの（`src/legacy/`・`src/tools/`・`configs/legacy/`）に書き換えてある。

### Wheelchair World-Frame Workflow

[`docs/knowledge/2026-06-30/plan.md`](../../docs/knowledge/2026-06-30/plan.md) に沿った実測データ用の新パイプラインでは，
`wheelchair_data/6.22/analysis/world_csv/*/acc_world.csv` を入力に使う．
`accWorldZ` から重力成分 `9.80665` を引いた `world_z_linear` を特徴量化対象とする．

```bash
uv run build-wheelchair-dataset --config configs/legacy/wheelchair_world_z_svm.yaml

uv run train-wheelchair-model --config configs/legacy/wheelchair_world_z_svm.yaml \
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

### Visualize And Analyze Wheelchair Data

可視化用の再利用可能な描画関数は `src/roadml/visualization/`、研究ごとの集計・評価処理は
`src/legacy/analysis/`、実行コマンドは `src/tools/`（汎用）と `src/legacy/scripts/` に分けている。

```bash
# 端末座標系の加速度波形を出力する
uv run plot-raw-acc \
  --input-dir wheelchair_data/6.22 \
  --output-dir wheelchair_data/6.22/analysis/plots/raw_acc

# world座標系CSVを生成する（可視化は行わない）
uv run transform-world-frame \
  --input-dir wheelchair_data/6.22 \
  --output-dir wheelchair_data/6.22/analysis/world_csv

# world座標系の3軸波形、および分析対象の鉛直加速度を出力する
uv run plot-world-frame \
  --input-dir wheelchair_data/6.22 \
  --output-dir wheelchair_data/6.22/analysis/plots/world_frame

uv run plot-world-z \
  --world-csv-dir wheelchair_data/6.22/analysis/world_csv \
  --raw-dir wheelchair_data/6.22 \
  --output-dir wheelchair_data/6.22/analysis/plots/world_z

# 発表用のstep / rough切り出し画像を出力する
uv run plot-world-z-crops \
  --world-csv wheelchair_data/6.22/analysis/world_csv/20260622180835/acc_world.csv \
  --raw-run-dir wheelchair_data/6.22/20260622180835 \
  --output-dir wheelchair_data/6.22/analysis/plots/world_z/crop \
  --step-range 0 28 \
  --rough-range 68 98

# flat / step / rough の研究分析。図は figures/、表は tables/ に出力する
uv run analyze-flat-event --output-dir data/analysis/20260721_flat_event
```

`analyze-flat-event` の出力構成は次のとおり。

```text
data/analysis/<analysis-id>/
├── figures/
└── tables/
```


### Generate Mock Sensor Logs

```bash
uv run generate-mock-data --config configs/legacy/mock_data_acc_only.yaml --seed 43
uv run generate-mock-data --config configs/legacy/mock_data_acc_only.yaml --seed 42
uv run generate-mock-data --config configs/legacy/mock_data_acc_only.yaml --seed 45
uv run generate-mock-data --config configs/legacy/mock_data_with_gyro.yaml
```

生成される CSV は 1 行 1 サンプルの時系列ログで，`include_gyro` に応じて `gyro_*` 列の有無が切り替わる．
出力先は毎回 `data/raw/YYYYMMDDHHMMSS_seedN/` を新規作成し，その配下に `mock_acc_only.csv` か `mock_with_gyro.csv` を保存する．
ラベル定義は `0=平坦`, `1=段差`, `2=粗さ` とする．
ラベル列は固定順ではなく，ある程度の継続時間を持ったランダム遷移で生成する．
`--seed` を指定すると `mock_data.random_state` を CLI から上書きできるため，train 用と eval 用で別runを作り分けられる．

### Extract Sliding-Window Features

```bash
uv run extract-features --config configs/legacy/mock_data_acc_only.yaml --input data/raw/20260513152209_seed43/mock_acc_only.csv
uv run extract-features --config configs/legacy/mock_data_acc_only.yaml --input data/raw/20260513152216_seed42/mock_acc_only.csv
uv run extract-features --config configs/legacy/mock_data_acc_only.yaml --input data/raw/20260513152641_seed45/mock_acc_only.csv
```

2.0秒窓，1.0秒ストライドで加速度3軸を分割し，各windowについて `mean`, `rms`, `var`, `max`, `min` を算出する．
windowラベルは `1 > 2 > 0` の優先ルールで決め，窓内に `1` が1つでもあれば `1`，`1` がなく `2` があれば `2`，それ以外は `0` とする．
出力先は毎回 `data/features/YYYYMMDDHHMMSS_seedN/` を新規作成し，その配下に `mock_acc_only_features_seedN.csv` を保存する．

### Train And Evaluate

```bash
uv run train-dummy --config configs/legacy/svm.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv

uv run train-dummy --config configs/legacy/random_forest.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv
```

特徴量CSVの `label` を目的変数にし，`window_id`, `window_start_ms`, `window_end_ms`, `n_samples` を除いた特徴量列を学習に使う．
`--train-input` を学習元，`--eval-input` を精度評価用データとして扱い，複数の評価用CSVを順に評価できる．
評価結果は毎回 `data/processed/YYYYMMDDHHMMSS/` を新規作成し，その配下に eval元ごとの classification report と confusion matrix を保存する．

