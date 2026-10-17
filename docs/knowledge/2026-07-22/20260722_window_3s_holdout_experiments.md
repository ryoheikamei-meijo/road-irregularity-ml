# 2026-07-22 3秒窓・境界window・特徴量削減の比較実験

## 目的

既存データだけで実施できる以下の3項目を、同一のtrain / eval run分割で比較した。

1. 3秒窓を既存の2-run holdoutで学習・評価する。
2. イベント境界に一部重なるflat windowを学習データから除外する。
3. 相関の高い`z_rms`を特徴量から除外する。

効果を切り分けるため、境界window除外と`z_rms`除外を同時に適用した条件も補助的に評価した。

## 共通条件

- 入力: `wheelchair_data/6.22`と`wheelchair_data/7.12`の世界座標系データ
- 対象: 6.22の11 run、7.12の成功かつ51 kgの11 run
- window: 3.0秒（4 Hzの12点）
- stride: 0.25秒
- ラベル: `flat` / `dansa` / `dekobo`
- イベント開始の前倒し: 0.5秒
- ラベル閾値: windowとイベント区間の重なり50%以上
- モデル: StandardScaler + RBF SVM
- `C`: 1.0
- `gamma`: `scale`
- `class_weight`: `balanced`

### train / eval分割

1秒窓の既存実験と同じrunをholdoutした。

- eval: `20260622180835`, `20260622182112`
- train: 残り20 run

3秒窓ではbaselineの学習データが3,830 windows、評価データが611 windowsとなった。評価データの内訳はflat 478、dansa 38、dekobo 95である。窓幅が変わるため、同じeval runでも1秒窓の627 windowsとは総数が異なる。

### 入力データ

- 3秒窓の分析元データ: [window_features.csv](../../../data/analysis/20260722_window_width/window_3s/tables/window_features.csv)
- 比較用データセット: [20260722_window_3s_holdout_variants](../../../data/features/20260722_window_3s_holdout_variants)

## 実験1: 3秒窓の同一holdout評価

4特徴量（`z_range`, `z_diff_max`, `z_rms`, `z_std`）を使い、1秒窓と同じ2 runを評価した。

| window | accuracy | balanced accuracy | macro F1 | dansa F1 | dekobo F1 |
|---|---:|---:|---:|---:|---:|
| 1秒 | 0.7129 | 0.4478 | 0.4425 | 0.0612 | 0.4257 |
| 3秒 | **0.7676** | **0.5470** | **0.5212** | **0.1558** | **0.5281** |

同一holdoutで、3秒窓は1秒窓に対してaccuracy +0.0547、balanced accuracy +0.0992、macro F1 +0.0787となった。dansa F1は0.0612から0.1558、dekobo F1は0.4257から0.5281へ改善した。

窓幅比較のrun単位CVだけでなく、固定holdoutでも改善したため、窓幅を広げる効果は確認できた。ただしdansa F1は依然として低く、3秒窓だけでは安定した3分類には至っていない。

出力:

- [classification_report_svm_all_eval.txt](../../../data/processed/20260722143354/classification_report_svm_all_eval.txt)
- [confusion_matrix_svm_all_eval.csv](../../../data/processed/20260722143354/confusion_matrix_svm_all_eval.csv)
- [run_split.txt](../../../data/processed/20260722143354/run_split.txt)

## 実験2: 学習時の境界window除外

イベント区間との重なりが0%超50%未満で、ラベルがflatになっているwindowを境界windowとした。評価データは変更せず、train側だけから158件のflat windowを除外した。

- baseline train: 3,830 windows（flat 3,470 / dansa 51 / dekobo 309）
- 境界除外後: 3,672 windows（flat 3,312 / dansa 51 / dekobo 309）

| 条件 | accuracy | balanced accuracy | macro F1 | dansa F1 | dekobo F1 |
|---|---:|---:|---:|---:|---:|
| 3秒baseline | **0.7676** | **0.5470** | **0.5212** | **0.1558** | **0.5281** |
| + 境界window除外 | 0.7660 | 0.5435 | 0.5189 | 0.1538 | 0.5240 |

全指標がわずかに低下した。今回の3秒・固定holdout条件では、境界window除外による改善は確認できなかった。境界windowは実運用時にも発生するため、除外によって境界付近の学習機会を失った可能性がある。標準パイプラインには採用しない。

出力:

- [classification_report_svm_all_eval.txt](../../../data/processed/20260722143356/classification_report_svm_all_eval.txt)
- [confusion_matrix_svm_all_eval.csv](../../../data/processed/20260722143356/confusion_matrix_svm_all_eval.csv)
- [run_split.txt](../../../data/processed/20260722143356/run_split.txt)

## 実験3: `z_rms`の除外

`z_rms`と`z_std`の相関が約0.99であることから、`z_rms`を除外し、`z_range`, `z_diff_max`, `z_std`の3特徴量で評価した。train / evalのwindowはbaselineと同一である。

| 条件 | accuracy | balanced accuracy | macro F1 | dansa precision | dansa recall | dansa F1 | dekobo F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4特徴量 | 0.7676 | **0.5470** | 0.5212 | 0.1538 | 0.1579 | 0.1558 | **0.5281** |
| `z_rms`除外 | **0.7692** | 0.5445 | **0.5241** | **0.1795** | **0.1842** | **0.1818** | 0.5089 |

`z_rms`除外によってaccuracy +0.0016、macro F1 +0.0029、dansa F1 +0.0260となった。一方、balanced accuracyは-0.0025、dekobo F1は-0.0192となった。

全体性能はほぼ同等だが、特徴量数を減らしながらmacro F1とdansa F1が改善したため、3特徴量版は次の候補とする。ただし改善幅は小さく、別のrun分割でも再確認が必要である。

出力:

- [classification_report_svm_all_eval.txt](../../../data/processed/20260722143357/classification_report_svm_all_eval.txt)
- [confusion_matrix_svm_all_eval.csv](../../../data/processed/20260722143357/confusion_matrix_svm_all_eval.csv)
- [run_split.txt](../../../data/processed/20260722143357/run_split.txt)

## 補助実験: 境界window除外 + `z_rms`除外

| 条件 | accuracy | balanced accuracy | macro F1 | dansa F1 | dekobo F1 |
|---|---:|---:|---:|---:|---:|
| `z_rms`除外のみ | **0.7692** | **0.5445** | **0.5241** | **0.1818** | **0.5089** |
| 境界除外 + `z_rms`除外 | 0.7660 | 0.5375 | 0.5177 | 0.1750 | 0.4955 |

両方を適用すると`z_rms`除外のみより悪化した。境界window除外は特徴量構成を変えても有効ではなかった。

出力:

- [classification_report_svm_all_eval.txt](../../../data/processed/20260722143359/classification_report_svm_all_eval.txt)
- [confusion_matrix_svm_all_eval.csv](../../../data/processed/20260722143359/confusion_matrix_svm_all_eval.csv)
- [run_split.txt](../../../data/processed/20260722143359/run_split.txt)

## 結論

今回の3項目では、窓幅を3秒へ広げる変更が最も大きな改善を示した。境界window除外は採用せず、`z_rms`除外は簡素化とdansa F1改善の観点から候補として残す。

現時点の推奨条件は以下。

- window: 3.0秒
- stride: 0.25秒
- 特徴量: `z_range`, `z_diff_max`, `z_std`
- 境界window: 除外しない

ただし、4特徴量baselineはbalanced accuracyとdekobo F1でわずかに優れている。3特徴量版を標準設定に確定する前に、leave-one-run-outまたはrepeated group CVで再確認する。

## 使用した実装・設定

- window生成・特徴量計算・ラベル付与: [wheelchair_pipeline.py](../../../src/wheelchair_pipeline.py)
- 3秒窓データ生成: [flat_event.py](../../../src/analysis/flat_event.py)
- 学習・評価CLI: [train_wheelchair_model.py](../../../src/scripts/train_wheelchair_model.py)
- モデル定義: [models.py](../../../src/models.py)
- SVM設定: [wheelchair_world_z_combined_svm.yaml](../../../configs/wheelchair_world_z_combined_svm.yaml)
