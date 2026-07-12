# 2026-06-30 車椅子実測 `world_z_linear` パイプライン実験まとめ

## 概要

2026-06-30 時点で、`wheelchair_data/6.22/analysis/world_csv` を使った実測データ向け ML パイプラインを実装し、以下の条件で評価した。

- 入力: `acc_world.csv`
- 主特徴量軸: `world_z_linear = accWorldZ - 9.80665`
- window: `1.0` 秒
- stride: `0.25` 秒
- 特徴量: `z_range`, `z_diff_max`, `z_rms`, `z_std`
- ラベル: `flat`, `dansa`, `dekobo`
- ラベル優先度: `dansa > dekobo > flat`
- モデル候補: `SVM`, `Random Forest`

評価の主目的は、`dansa` をどこまで拾えるかを確認することだった。

## 実装した前提

### 前処理

- `accWorldZ` から重力成分 `9.80665` を引いて `world_z_linear` を作成
- `dansa.csv` / `dekobo.csv` から `start-stop` 区間を復元
- 各 window とイベント区間の重なり率を計算し、`0.5` 以上ならそのラベルを付与
- `_during` イベントは区間復元には使わない

### 追加した CLI

- `uv run build-wheelchair-dataset --config ...`
- `uv run train-wheelchair-model --config ... --input ... --train-run-id ... --eval-run-id ...`

### 追加した設定

- [configs/wheelchair_world_z_svm.yaml](/Users/kameiryouhei/code/research/road-irregularity-ml/configs/wheelchair_world_z_svm.yaml:1)
- [configs/wheelchair_world_z_random_forest.yaml](/Users/kameiryouhei/code/research/road-irregularity-ml/configs/wheelchair_world_z_random_forest.yaml:1)

## 実験対象 run

### 6/22 success run 一覧

- `20260622175452`
- `20260622180411`
- `20260622180835`
- `20260622181304`
- `20260622182112`
- `20260622182312`
- `20260622182555`
- `20260622182658`
- `20260622182908`
- `20260622183215`
- `20260622183356`

### run ごとの自動ラベル数

`pre_event_extension_seconds = 0.0` の dataset での内訳:

| run_id | dansa | dekobo | flat |
|---|---:|---:|---:|
| 20260622175452 | 0 | 44 | 161 |
| 20260622180411 | 0 | 35 | 326 |
| 20260622180835 | 23 | 23 | 340 |
| 20260622181304 | 7 | 34 | 404 |
| 20260622182112 | 9 | 64 | 168 |
| 20260622182312 | 0 | 66 | 307 |
| 20260622182555 | 0 | 13 | 222 |
| 20260622182658 | 4 | 10 | 305 |
| 20260622182908 | 0 | 29 | 461 |
| 20260622183215 | 0 | 12 | 365 |
| 20260622183356 | 0 | 8 | 448 |

## 実験一覧

### 実験 A: SVM, 前倒し 0.0 秒, 5-run 評価

- dataset: [data/features/20260630090926/wheelchair_world_z_dataset.csv](/Users/kameiryouhei/code/research/road-irregularity-ml/data/features/20260630090926/wheelchair_world_z_dataset.csv:1)
- result dir: [data/processed/20260630091038](/Users/kameiryouhei/code/research/road-irregularity-ml/data/processed/20260630091038:1)
- train runs:
  - `20260622175452`
  - `20260622180411`
  - `20260622180835`
  - `20260622181304`
  - `20260622182112`
  - `20260622182312`
- eval runs:
  - `20260622182555`
  - `20260622182658`
  - `20260622182908`
  - `20260622183215`
  - `20260622183356`

#### 結果

| 指標 | 値 |
|---|---:|
| accuracy | 0.6265 |
| flat precision / recall / f1 | 0.9835 / 0.6308 / 0.7686 |
| dansa precision / recall / f1 | 0.0000 / 0.0000 / 0.0000 |
| dekobo precision / recall / f1 | 0.1818 / 0.5556 / 0.2740 |
| macro avg f1 | 0.3475 |
| weighted avg f1 | 0.7480 |

#### 補足

- eval 側の `dansa` support は `4` window しかなかった
- `dansa` を含んでいた eval run は `20260622182658` のみ
- 段差を 1 件も拾えなかった

### 実験 B: SVM, 前倒し 0.0 秒, 2-run 評価

- result dir: [data/processed/20260630091539](/Users/kameiryouhei/code/research/road-irregularity-ml/data/processed/20260630091539:1)
- train runs:
  - `20260622175452`
  - `20260622180411`
  - `20260622181304`
  - `20260622182312`
  - `20260622182555`
  - `20260622182658`
  - `20260622182908`
  - `20260622183215`
  - `20260622183356`
- eval runs:
  - `20260622180835`
  - `20260622182112`

#### eval ラベル数

| run_id | dansa | dekobo | flat |
|---|---:|---:|---:|
| 20260622180835 | 23 | 23 | 340 |
| 20260622182112 | 9 | 64 | 168 |

#### 結果

| 指標 | 値 |
|---|---:|
| accuracy | 0.5247 |
| flat precision / recall / f1 | 0.8615 / 0.5512 / 0.6723 |
| dansa precision / recall / f1 | 0.0209 / 0.1250 / 0.0359 |
| dekobo precision / recall / f1 | 0.4054 / 0.5172 / 0.4545 |
| macro avg f1 | 0.3876 |
| weighted avg f1 | 0.6096 |

#### run 別結果

| run_id | accuracy | dansa recall |
|---|---:|---:|
| 20260622180835 | 0.5104 | 0.1739 |
| 20260622182112 | 0.5477 | 0.0000 |

### 実験 C: SVM, 前倒し 1.0 秒, 2-run 評価

- dataset: [data/features/20260630092049/wheelchair_world_z_dataset.csv](/Users/kameiryouhei/code/research/road-irregularity-ml/data/features/20260630092049/wheelchair_world_z_dataset.csv:1)
- result dir: [data/processed/20260630092106](/Users/kameiryouhei/code/research/road-irregularity-ml/data/processed/20260630092106:1)

#### dataset 全体ラベル数

| label | count |
|---|---:|
| dansa | 63 |
| dekobo | 398 |
| flat | 3427 |

#### eval ラベル数

| run_id | dansa | dekobo | flat |
|---|---:|---:|---:|
| 20260622180835 | 31 | 31 | 324 |
| 20260622182112 | 13 | 72 | 156 |

#### 結果

| 指標 | 値 |
|---|---:|
| accuracy | 0.3573 |
| flat precision / recall / f1 | 0.7972 / 0.3521 / 0.4884 |
| dansa precision / recall / f1 | 0.0333 / 0.2273 / 0.0581 |
| dekobo precision / recall / f1 | 0.3913 / 0.4369 / 0.4128 |
| macro avg f1 | 0.3198 |
| weighted avg f1 | 0.4458 |

#### run 別結果

| run_id | accuracy | dansa recall |
|---|---:|---:|
| 20260622180835 | 0.3575 | 0.3226 |
| 20260622182112 | 0.3568 | 0.0000 |

#### 所見

- `dansa recall` は今回の中で最も高い
- ただし `flat` を多く `dansa` / `dekobo` 側へ巻き込み、accuracy が大きく低下した

### 実験 D: SVM, 前倒し 0.5 秒, 2-run 評価

- dataset: [data/features/20260630092253/wheelchair_world_z_dataset.csv](/Users/kameiryouhei/code/research/road-irregularity-ml/data/features/20260630092253/wheelchair_world_z_dataset.csv:1)
- result dir: [data/processed/20260630092306](/Users/kameiryouhei/code/research/road-irregularity-ml/data/processed/20260630092306:1)

#### dataset 全体ラベル数

| label | count |
|---|---:|
| dansa | 53 |
| dekobo | 368 |
| flat | 3467 |

#### eval ラベル数

| run_id | dansa | dekobo | flat |
|---|---:|---:|---:|
| 20260622180835 | 27 | 27 | 332 |
| 20260622182112 | 11 | 68 | 162 |

#### 結果

| 指標 | 値 |
|---|---:|
| accuracy | 0.4067 |
| flat precision / recall / f1 | 0.8279 / 0.4089 / 0.5474 |
| dansa precision / recall / f1 | 0.0292 / 0.2105 / 0.0513 |
| dekobo precision / recall / f1 | 0.4128 / 0.4737 / 0.4412 |
| macro avg f1 | 0.3466 |
| weighted avg f1 | 0.5013 |

#### run 別結果

| run_id | accuracy | dansa recall |
|---|---:|---:|
| 20260622180835 | 0.3705 | 0.2963 |
| 20260622182112 | 0.4647 | 0.0000 |

#### 所見

- `1.0` 秒前倒しより `dansa recall` はやや下がる
- その代わり `flat` の巻き込みが減り、accuracy は改善した
- `dansa` を重視しつつ、accuracy の崩れを多少抑えられている

### 実験 E: Random Forest, 前倒し 0.5 秒, 2-run 評価

- result dir: [data/processed/20260630092655](/Users/kameiryouhei/code/research/road-irregularity-ml/data/processed/20260630092655:1)
- split は実験 D と同じ

#### 結果

| 指標 | 値 |
|---|---:|
| accuracy | 0.7974 |
| flat precision / recall / f1 | 0.8036 / 0.9858 / 0.8855 |
| dansa precision / recall / f1 | 0.0000 / 0.0000 / 0.0000 |
| dekobo precision / recall / f1 | 0.6190 / 0.1368 / 0.2241 |
| macro avg f1 | 0.3699 |
| weighted avg f1 | 0.7316 |

#### 所見

- accuracy は最も高い
- ただし予測が `flat` に強く偏っている
- `dansa` は `38` 件中 `0` 件で、段差検知目的には不適

## 実験比較まとめ

### 全体比較

| 実験 | モデル | 前倒し秒数 | eval runs | accuracy | dansa recall | dekobo recall |
|---|---|---:|---|---:|---:|---:|
| A | SVM | 0.0 | 5 run | 0.6265 | 0.0000 | 0.5556 |
| B | SVM | 0.0 | 2 run | 0.5247 | 0.1250 | 0.5172 |
| C | SVM | 1.0 | 2 run | 0.3573 | 0.2273 | 0.4369 |
| D | SVM | 0.5 | 2 run | 0.4067 | 0.2105 | 0.4737 |
| E | Random Forest | 0.5 | 2 run | 0.7974 | 0.0000 | 0.1368 |

### 現時点の解釈

- `dansa recall` を最優先すると、最も高かったのは **SVM + 前倒し 1.0 秒**
- ただし `flat` の誤判定が多く、accuracy が大きく落ちた
- バランスを見ると、**SVM + 前倒し 0.5 秒**が中間的な妥協点
- `Random Forest` は accuracy は高いが、`flat` に寄りすぎて `dansa` を拾えない
- `20260622182112` はどの設定でも `dansa` が特に難しく、追加確認対象

## 現時点の結論

現段階のベースラインとしては、**`world_z_linear` + SVM + ラベル開始前倒し 0.5 秒**を一旦の比較基準にするのが妥当。理由は以下。

- `dansa recall` が完全ゼロではない
- `1.0` 秒前倒しほど `flat` を壊さない
- `Random Forest` より段差検知目的に合っている

ただし、この条件でも `dansa recall = 0.2105` であり、性能は十分ではない。

## 次にやるべきこと

1. `20260622180835` と `20260622182112` の `dansa` window を時刻付きで洗い出す
2. それぞれの予測ラベルを確認し、`flat` / `dekobo` への流れ方を可視化する
3. `world_z_linear` 単独ではなく、`accWorldY` または `accWorldMag` の追加を比較する
4. `pre_event_extension_seconds` を `0.25`, `0.5`, `0.75`, `1.0` で系統比較する
5. `dansa` 向け特徴量を追加する
   - 例: 負方向の急変、ピーク位置、絶対差分最大値、window 内 skewness など
