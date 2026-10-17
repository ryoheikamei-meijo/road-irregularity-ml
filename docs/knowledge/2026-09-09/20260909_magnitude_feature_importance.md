# 合成加速度+ジャーク特徴量(6)の重要度分析

## 1. 背景・目的

[z軸 vs 合成加速度の比較](20260909_multi_feature_class_balance.md)で「z軸4特徴量」を「合成加速度|a|の基本4特徴量＋ジャーク2特徴量（計6特徴量、`jerk_max`は除外）」に置き換える効果を確認したが、6個のうちどれが実際に効いているのかは未確認だった。[全軸+ジャーク特徴量(18)の重要度分析](20260909_feature_importance_reduction.md)と同じ方法で、この6特徴量についても寄与度を確認する。

6特徴量とすでに少ないため、上位N個に絞る削減検討（[全軸+ジャーク分析](20260909_feature_importance_reduction.md)で行ったもの）は今回行わない。寄与度の確認のみを目的とする。

## 2. 実装した変更

- `src/legacy/analysis/feature_importance.py`
  - `plot_feature_importance()` / `plot_feature_importance_agreement()` に `feature_set_label` 引数を追加（デフォルトは従来通り「全軸+ジャーク特徴量」）。これにより図タイトルの特徴量セット名を呼び出し側で差し替えられるようにした（ロジック自体は変更なし、既存の呼び出し・出力は従来通り）。
- `src/legacy/analysis/magnitude_feature_importance.py`（新規） / `src/legacy/scripts/analyze_magnitude_feature_importance.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-magnitude-feature-importance` を追加
  - `feature_importance.py` の `compute_permutation_importance_cv` / `plot_feature_importance` / `plot_feature_importance_agreement` をそのまま再利用し、対象の特徴量セットを [z軸 vs 合成加速度の比較](20260909_multi_feature_class_balance.md) の `mag_plus_jerk_only`（`ALL_MAG_FEATURE_COLUMNS`、6特徴）に差し替えた。ダウンサンプリングありの設定で、RF・SVM双方のpermutation importanceを計算する。
  - 上位N個の削減比較（`reduced_vs_full_feature_comparison.csv`相当）は作成しない。
- 既存テスト（`pytest`、17件）は全て通過。

再実行コマンド: `uv run analyze-magnitude-feature-importance`

## 3. データ・条件

これまでと同じ22走行、窓幅1.0秒。合成加速度+ジャーク特徴量6個（`mag_range`, `mag_diff_max`, `mag_rms`, `mag_std`, `mag_jerk_rms`, `mag_jerk_std`。`mag_jerk_max`は除外）。重要度算出はSVM・Random Forestそれぞれ、ダウンサンプリングありの設定で実施。図の見方（●＝5fold平均、線＝5foldでの最小〜最大の範囲、agreement図は棒グラフのみ）は[全軸+ジャーク特徴量の重要度分析](20260909_feature_importance_reduction.md)の4.0節と同じ。

## 4. 結果

出力先: [`data/analysis/20260909_magnitude_feature_importance/`](../../../data/analysis/20260909_magnitude_feature_importance)
- モデル間比較図: [figures/feature_importance_agreement.png](../../../data/analysis/20260909_magnitude_feature_importance/figures/feature_importance_agreement.png)
- Random Forest単体: [figures/feature_importance_random_forest.png](../../../data/analysis/20260909_magnitude_feature_importance/figures/feature_importance_random_forest.png) / [tables/feature_importance_random_forest.csv](../../../data/analysis/20260909_magnitude_feature_importance/tables/feature_importance_random_forest.csv)
- SVM単体: [figures/feature_importance_svm.png](../../../data/analysis/20260909_magnitude_feature_importance/figures/feature_importance_svm.png) / [tables/feature_importance_svm.csv](../../../data/analysis/20260909_magnitude_feature_importance/tables/feature_importance_svm.csv)
- RF/SVM並記表: [tables/feature_importance_rf_vs_svm.csv](../../../data/analysis/20260909_magnitude_feature_importance/tables/feature_importance_rf_vs_svm.csv)

| 順位 | Random Forest | importance | SVM | importance |
| ---: | --- | ---: | --- | ---: |
| 1 | `mag_rms` | **0.0533** | `mag_rms` | **0.0580** |
| 2 | `mag_range` | **0.0103** | `mag_jerk_rms` | -0.0108 |
| 3 | `mag_jerk_std` | -0.0080 | `mag_range` | -0.0118 |
| 4 | `mag_std` | -0.0091 | `mag_std` | -0.0120 |
| 5 | `mag_jerk_rms` | -0.0201 | `mag_jerk_std` | -0.0226 |
| 6 | `mag_diff_max` | -0.0259 | `mag_diff_max` | -0.0344 |

### RF/SVMともに`mag_rms`が突出、残りはほぼノイズ

[全軸+ジャーク特徴量(18)の分析](20260909_feature_importance_reduction.md)ではRFとSVMで重要な特徴量が大きく食い違っていたが、合成加速度の6特徴量では**両モデルとも`mag_rms`が飛び抜けてプラスの重要度**（RF: 0.0533, SVM: 0.0580）で一致している。RFでは`mag_range`もわずかにプラス（0.0103）だったが、SVMでは`mag_range`はマイナス（-0.0118）で、この点だけはモデル間で評価が分かれた。それ以外の特徴量（`mag_std`, `mag_diff_max`, ジャーク2種）は両モデルともマイナス（シャッフルしてもむしろ性能が上がる＝ノイズに近い）という結果になった。

これは[flat vs eventの分析](20260909_magnitude_event_analysis.md)（4.1節）で`mag_rms`がAUC 0.75〜0.78と単変量でも最良だったことと整合する。合成加速度から作れる6特徴量のうち、実質的に情報を持っているのは`mag_rms`（および、RFにとってはやや`mag_range`）のみで、残りは互いに強く相関しているか、ノイズを増やしているだけと考えられる。

## 5. まとめ・次のステップ

- 合成加速度から作った6特徴量のうち、**実際に効いているのは主に`mag_rms`**。RF・SVMでほぼ一致しており、[全軸+ジャーク特徴量(18)](20260909_feature_importance_reduction.md)でRF/SVMの重要度が大きく割れていたのとは対照的に、**モデルに依存しない、信頼度の高い結果**と言える。
- [z軸 vs 合成加速度の比較](20260909_multi_feature_class_balance.md)で使った6特徴量（`mag_plus_jerk_only`）は、実質的に`mag_rms`（＋RFなら`mag_range`）だけで説明できる可能性が高い。6特徴量に増やす意味はほとんどなく、**`mag_rms`単体、もしくは元々の比較A（`mag_basic_only`4特徴量）で十分**という結論を補強する結果になった。
- 次の一手: `mag_rms`単体での分類性能を確認する、もしくは[全軸+ジャーク特徴量(18)の重要度分析](20260909_feature_importance_reduction.md)の上位10特徴量に`mag_rms`を加えた場合に性能が変わるかを確認する。

## 6. 更新履歴：2026-09-09、`jerk_max`を特徴量セットから除外

ジャーク特徴量から`jerk_max`を除外し`jerk_rms`/`jerk_std`のみを使う方針に変更したことに伴い、対象の特徴量は7個→6個になり全面的に再計算した（波及範囲の全体像は[ジャーク分析の更新履歴](20260909_jerk_feature_analysis.md)を参照）。除外前・後とも「`mag_rms`だけが両モデルで有効」という結論の骨格は変わらないが、除外後はRFで`mag_range`もわずかにプラスに転じた点が新たにわかった。
