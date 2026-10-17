# Road Irregularity ML

手動式車椅子の走行時の加速度データから、路面の状態（flat：平坦、step：段差、rough：凸凹）を分類する機械学習の実験用リポジトリ。

データは、車椅子の後方に固定したスマホのアプリ（`MyApplication3`）で収集している。

## セットアップ

Python 3.13 と [uv](https://docs.astral.sh/uv/) を使う。

```bash
uv sync
```

依存関係を追加・更新した後も `uv sync` を実行する（`uv add ...` は依存関係のメンテナンスのときだけ使う）。

## ディレクトリ構成

```
.
├── README.md
├── docs/
│   ├── README.md          ドキュメントの目次
│   ├── adr/               設計判断の記録（ADR）
│   └── knowledge/         分析・実験のメモ（YYYY-MM-DD/ ごと）
├── src/
│   ├── roadml/            共通の処理（読み込み・ラベル付け・窓・特徴量・評価・描画）
│   ├── experiments/       実験のスクリプト（メモ 1 本に対応。e<日付>_<内容>.py）
│   ├── tools/             汎用のコマンド（世界座標系への変換、波形の描画など）
│   └── legacy/            2026-05〜09 の古いパイプライン（src/legacy/README.md）
├── configs/
│   ├── datasets/          解析に使うセッションの一覧
│   └── legacy/            古いパイプラインの設定
├── tests/
├── wheelchair_data/       実測データ（Git 管理外）
└── data/analysis/         実験の出力（<日付>_<内容>/）
```

## 今の解析の流れ

```
アプリ（MyApplication3）
  └→ wheelchair_data/<日付>/<セッションID>/   acc.csv・dansa.csv・dekobo.csv など
       └→ configs/datasets/<名前>.yaml      使うセッションの一覧
            └→ src/roadml/                  世界座標系への変換 → 窓の切り出し・ラベル付け → 特徴量 → LOGO の評価
                 └→ src/experiments/        実験ごとのスクリプト
                      └→ data/analysis/<日付>_<内容>/   図・表
                           └→ docs/knowledge/<日付>/   メモ
```

- **データ**: 10.3・10.4 の実測（約 334Hz）。基本は後ろ固定の 12 セッション（`configs/datasets/rear_only_103_104.yaml`）。CSV の列は、アプリの README を参照。
- **ラベル（方針A）**: step・rough は、継続ボタンの区間に半分以上重なる窓だけを使う。flat は、平坦だけのセッションを 5 ブロックに分けて使う（`src/roadml/windows.py`）。
- **評価**: セッション単位の Leave-One-Group-Out（16 グループ）、balanced accuracy。step と rough だけの 2 クラス精度も見る（`src/roadml/evaluation.py`）。
- **軸**: 鉛直は世界座標系の z − g、水平は x・y の大きさ √(x² + y²)（[ADR 2026-10-17](docs/adr/20261017_axis_representation.md)）。
- **特徴量**: 基本4（std・range・rms・diff_max）+ 尖度・クレスト（`src/roadml/features.py`）。

## 実験の実行

```bash
uv run python -m src.experiments.<スクリプト名> [--dataset <名前> | --data-dir <ディレクトリ>]
```

- `--dataset` を省略すると、後ろ固定のみ（`rear_only_103_104`）を使う。10.4 の実験は、10.3 + 10.4 の全セッション（`all_103_104`）が既定。
- 各実験の詳しい再現方法は、対応するメモの「再現方法」の章を参照。

### 実験のスクリプト（`src/experiments/`）

| スクリプト | 内容 | メモ |
| --- | --- | --- |
| `e20261004_baseline` | z 軸の基本4での最初の評価 | [10-04](docs/knowledge/2026-10-04/20261004_analysis_log_103_104.md) |
| `e20261004_window_sweep` | 窓幅を変えた評価 | 同上 |
| `e20261004_plan_a` | 方針A のラベルでの評価 | 同上 |
| `e20261004_trim` | 区間の開始側を削ったときの評価 | 同上 |
| `e20261004_shape_features` | 尖度・クレストを足した評価 | 同上 |
| `e20261004_confusion_shape` | 尖度・クレストを足したときの混同行列 | 同上 |
| `e20261004_boxplots`・`_boxplots_extra` | flat・step・rough の箱ひげ図 | 同上 |
| `e20261004_peak_flat_vs_event` | 窓の中の最大・最小の比較 | 同上 |
| `e20261004_session_comparison` | 代表セッションの波形の比較 | 同上 |
| `e20261004_misclassified_windows` | 誤分類の窓を波形に重ねる | 同上 |
| `e20261005_rear_vs_front_waveforms`・`_rear_vs_front_stats` | スマホの固定位置（後ろ／前）の比較 | [10-05](docs/knowledge/2026-10-05/20261005_rear_only_analysis.md) |
| `e20261005_burst_segment` | バースト特徴量・区間単位の評価 | 同上 |
| `e20261005_magnitude` | 合成加速度の評価 | 同上 |
| `e20261006_feature_importance` | 特徴量の寄与度（permutation・ablation・上位 k 個） | [10-06](docs/knowledge/2026-10-06/20261006_feature_importance_rear_only.md)、[10-12](docs/knowledge/2026-10-12/20261012_feature_importance_no_burst.md)（`--no-burst`） |
| `e20261006_related_features` | 関連研究の特徴量の評価 | [10-06](docs/knowledge/2026-10-06/20261006_related_work_features_eval.md) |
| `e20261012_topk_selection`・`_confusion_topk` | 上位 k 個の選ばれ方と混同行列 | [10-12](docs/knowledge/2026-10-12/20261012_feature_importance_no_burst.md) |
| `e20261012_window_widening`・`_window_widening_diagnosis` | 窓幅を広げたときの精度と、その診断 | 同上 |
| `e20261012_confusion_presented` | 発表の構成での混同行列・誤分類の内訳 | 同上 |
| `e20261013_perm_by_class` | クラスごとの permutation importance | （ゼミの指摘への対応） |
| `e20261017_added_features` | 性質の違う特徴量を 1 種類ずつ足す | [10-17](docs/knowledge/2026-10-17/20261017_added_features_eval.md) |
| `e20261017_step_rough_errors` | step と rough の取り違えの原因 | [10-17](docs/knowledge/2026-10-17/20261017_step_rough_error_causes.md) |
| `e20261017_heading_dependence` | x・y の走る向きへの依存 | [10-17](docs/knowledge/2026-10-17/20261017_heading_dependence.md) |

`e20261004_confusion_shape`・`e20261012_confusion_topk`・`e20261012_window_widening_diagnosis` は、`main` 関数を持たず、実行するとすぐに計算する作り（import するだけでも動く）。

### 汎用のコマンド（`src/tools/`）

| スクリプト | 内容 |
| --- | --- |
| `plot_session_waveform` | 1 セッションの世界座標系の加速度と速度を、横長の 1 枚に描く |
| `transform_world_frame`（`uv run transform-world-frame`） | 生の加速度を世界座標系に変換した CSV を作る |
| `plot_raw_acc`（`uv run plot-raw-acc`） | 端末の座標系の加速度の波形を描く |
| `plot_world_frame`（`uv run plot-world-frame`） | 世界座標系の 3 軸の波形を描く |
| `plot_world_z`（`uv run plot-world-z`） | 世界座標系の鉛直の加速度の波形を描く |

### 新しい実験を足すとき

1. スクリプトは `src/experiments/e<YYYYMMDD>_<内容>.py`、出力は `data/analysis/<YYYYMMDD>_<内容>/`、メモは `docs/knowledge/<YYYY-MM-DD>/` に置く。
2. 共通の処理（窓の切り出し・特徴量・評価）は `src/roadml/` のものを使う。データは `src.roadml.datasets` の `add_run_dir_args`・`resolve_run_dirs` で受け取る。
3. メモの最後に「再現方法」（実行したコマンドと出力）を書き、`docs/README.md` の目次と、上のスクリプトの表に 1 行足す。
4. 複数の実験で使う処理ができたら、`src/roadml/` に移す。

## テスト

```bash
uv run pytest
```

`tests/test_regression_rear_only.py` は、主な評価値（xyz18・SVM・2.0 秒窓で 0.861 など）が変わっていないことを確かめる。実測データ（`wheelchair_data/`）が無い環境ではスキップする。`src/roadml/` を変更したときは必ず実行する。

## Notes

- `wheelchair_data/`、`data/raw/`、`data/processed/`、`data/features/`、`data/analysis/` は Git 管理しない（`.gitignore`）。CSV も管理しない。メモに貼っている図（`data/analysis/` の PNG）は、手元でだけ見られる。
- 実験データには位置情報が含まれる可能性があるため、GitHub には原則アップロードしない。
- 古いパイプライン（モックデータ、6.22・7.12 の約 4Hz のデータ）の使い方は [`src/legacy/README.md`](src/legacy/README.md)。

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
