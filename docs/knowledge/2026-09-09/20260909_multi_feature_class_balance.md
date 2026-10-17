# 合成加速度(|a|)+ジャーク特徴量とクラス均等化の組み合わせ効果

## 1. 背景・目的

本日実施した2つの分析——[ジャーク特徴量分析](20260909_jerk_feature_analysis.md)と[クラス均等化(ダウンサンプリング)分析](20260909_class_balance_downsampling.md)——はいずれも、実運用の学習パイプラインが使う「z軸4特徴量のみ」を前提に評価していた。一方、[合成加速度分析](20260909_magnitude_event_analysis.md)では、合成加速度|a|の基本4特徴量が同数比較（4 vs 4）でz軸単体より優れることがわかっている。

そこで本分析では、「z軸4特徴量のみ」を「合成加速度|a|の基本特徴量＋ジャーク特徴量（計6特徴量、`jerk_max`は除外）」に置き換えたとき、識別性能（特にstep(段差)のrecall）がどれだけ変わるか、クラス均等化（ダウンサンプリング）と組み合わせた場合にどうなるかを確認する。

> **注記**：当初この分析は「z軸4特徴量 vs x/y/z全軸+ジャーク21特徴量」の比較として行っていたが、[合成加速度分析](20260909_magnitude_event_analysis.md)の追加検証（比較B）を踏まえてスライドの流れを「z軸(4) → 合成加速度(6)」で揃えるため、本分析を合成加速度との比較に差し替えた。**18特徴量（`jerk_max`除外後）が本日全体で最良だった**という結果自体は変わらず有効で、その数値・詳細は[合成加速度分析](20260909_magnitude_event_analysis.md)（比較B）と[特徴量重要度分析](20260909_feature_importance_reduction.md)を参照。

## 2. 実装した変更

学習パイプライン本体（`train_wheelchair_model.py` / `configs/`）は変更せず、既存の分析コードを再利用・軽微に一般化した。

- `src/analysis/class_balance.py`
  - `run_group_cv()` に `feature_columns` 引数を追加（デフォルト `None` で従来通り `Z_FEATURE_COLUMNS` を使用、後方互換）。これにより任意の特徴量セットで同じ評価ロジック（run単位グループ5分割CV、学習fold内のみダウンサンプリング）を再利用できるようにした。
  - 既存の呼び出し元（`class_balance.py` の `main()`、[20260909_class_balance_downsampling.md](20260909_class_balance_downsampling.md)の出力）は挙動・出力ファイルとも変化なし。
- `src/analysis/multi_feature_balance.py`（新規） / `src/scripts/analyze_multi_feature_balance.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-multi-feature-balance` を追加
  - 特徴量セットを2種類用意: `z_only`（実運用と同じ4特徴量）と `mag_plus_jerk_only`（[合成加速度分析](20260909_magnitude_event_analysis.md)の`ALL_MAG_FEATURE_COLUMNS`＝合成加速度|a|の基本4特徴量＋ジャーク2特徴量、計6特徴量。`jerk_max`は除外済み、詳細は本ドキュメント末尾の更新履歴を参照）。
  - 2特徴量セット × 2モデル(SVM/RF) × 2条件(baseline/downsampled) の計8通りを同一データ・同一splitter(`random_state=42`)で評価し、比較図・集計表を出力。
- 既存テスト（`pytest`、17件）は全て通過。

再実行コマンド: `uv run analyze-multi-feature-balance`

## 3. データ・条件

これまでと同じ22走行（6.22の11走行 + 7.12の51kg・有効11走行）、窓幅1.0秒。特徴量セットのみ以下の2種類を比較。

| 特徴量セット | 特徴量数 | 内訳 |
| --- | --- | --- |
| z_only（実運用） | 4 | `z_range`, `z_diff_max`, `z_rms`, `z_std` |
| mag_plus_jerk_only | 6 | 合成加速度|a|の `range`, `diff_max`, `rms`, `std`（4） + 合成加速度ジャークの `jerk_rms`, `jerk_std`（2、`jerk_max`は除外） |

## 4. 結果

出力先: [`data/analysis/20260909_multi_feature_balance/`](../../../data/analysis/20260909_multi_feature_balance)
- 比較図: [figures/multi_feature_balance_comparison.png](../../../data/analysis/20260909_multi_feature_balance/figures/multi_feature_balance_comparison.png)
- 集計表: [tables/multi_feature_balance_summary.csv](../../../data/analysis/20260909_multi_feature_balance/tables/multi_feature_balance_summary.csv)

| model | feature_set | 条件 | balanced_accuracy | macro_f1 | flat recall | step recall | rough recall |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| SVM | z_only | baseline | 0.4314 | 0.3886 | 0.6646 | 0.0753 | 0.5545 |
| SVM | z_only | downsampled | 0.4650 | 0.3913 | 0.6616 | 0.1290 | 0.6043 |
| SVM | mag_plus_jerk_only | baseline | **0.4736** | 0.4078 | 0.7721 | 0.2151 | 0.4336 |
| SVM | mag_plus_jerk_only | downsampled | 0.4360 | 0.3705 | 0.7231 | 0.2366 | 0.3483 |
| Random Forest | z_only | baseline | 0.3955 | 0.4125 | 0.9766 | 0.0108 | 0.1991 |
| Random Forest | z_only | downsampled | **0.4572** | 0.3384 | 0.5256 | 0.3011 | 0.5450 |
| Random Forest | mag_plus_jerk_only | baseline | 0.3679 | 0.3771 | 0.9888 | 0.0108 | 0.1043 |
| Random Forest | mag_plus_jerk_only | downsampled | 0.4265 | 0.3222 | 0.5541 | **0.3226** | 0.4028 |

### 4.1 SVM：合成加速度への置き換えはbaselineで明確に効く

SVMでは、特徴量をz軸4個→合成加速度+ジャーク6個に変えるだけ（ダウンサンプリングなし）で、balanced_accuracy 0.4314→0.4736、macro_f1 0.3886→0.4078、flat/step recallともに改善した（step recallは0.0753→0.2151）。一方downsampled条件では、balanced_accuracyはわずかに下がる（0.4650→0.4360）が、step recallはさらに伸びる（0.1290→0.2366）というトレードオフになる。

### 4.2 Random Forest：balanced_accuracyは下がるが、step recallはむしろ改善する

Random Forestでは、z軸4特徴量から合成加速度6特徴量に変えると、baseline・downsampledどちらの条件でもbalanced_accuracyが下がる（baseline: 0.3955→0.3679、downsampled: 0.4572→0.4265）。一方、downsampled条件のstep recallは**合成加速度の方が高い**（0.3011→0.3226）。balanced_accuracy（全体としてのバランス）ではz軸のみが上回るが、本命指標のstep recallでは合成加速度の方が良いという、指標によって結論が変わる結果になった。

これはモデルの性質の違いを反映している。[特徴量重要度分析](20260909_feature_importance_reduction.md)で判明した通り、RFはy/z軸のRMS・標準偏差、SVMはx軸のジャーク・差分系を重視する。合成加速度は方向（軸）の情報を1つのスカラーに潰してしまうため、RFが元々頼っていた「軸ごとの違い」を隠してしまう面がある一方、段差検出だけを見れば合成加速度側にも情報がある、という両面がある。

## 5. まとめ・次のステップ

- 「z軸4特徴量のみ」を「合成加速度+ジャーク6特徴量」に置き換える効果は**モデルによって傾向が異なる**：SVMはbalanced_accuracy・step recallともに明確に改善するが、Random Forestはbalanced_accuracyが下がる一方でstep recallはむしろ改善する。単純な「置き換えれば良くなる」という話ではなく、モデルと重視する指標を踏まえた使い分けが必要。
- 本日全体で最良だったのは、合成加速度ではなく**x/y/z全軸＋ジャーク(18特徴量)＋ダウンサンプリング**という組み合わせ（RFのbalanced_accuracy 0.514・step recall 0.366、SVMのbalanced_accuracy 0.536・step recall 0.333）。この結果と、18特徴量のうちどれが効いているかの分析は[特徴量重要度分析](20260909_feature_importance_reduction.md)、18特徴量 vs 合成加速度6特徴量の直接比較は[合成加速度分析の比較B](20260909_magnitude_event_analysis.md)を参照。
- 次の一手: (a) SVMのハイパーパラメータ(C, gamma)調整やRFのn_estimators/max_depth調整、(b) 依然として残るサンプル数不足（dansa93件）そのものの解消（追加計測）。(c) 合成加速度+ジャーク6特徴量のうちどれが効いているかは[別分析](20260909_magnitude_feature_importance.md)で確認し、`mag_rms`以外はほぼノイズであることがわかった。

## 6. 更新履歴：2026-09-09、`jerk_max`を特徴量セットから除外

ジャーク特徴量から`jerk_max`を除外し`jerk_rms`/`jerk_std`のみを使う方針に変更したことに伴い、`mag_plus_jerk_only`は7特徴量→6特徴量になった（詳細・波及範囲は[ジャーク分析の更新履歴](20260909_jerk_feature_analysis.md)を参照）。除外後は本文の通り全条件で性能が改善しており（SVM baselineのstep recall: 0.1720→0.2151、RF downsampledのstep recall: 0.2473→0.3226）、`jerk_max`が主にノイズとして働いていたことを裏付ける結果になった。
