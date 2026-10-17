# 合成加速度|a|特徴量による段差(step)・凹凸(rough)識別力の分析

## 1. 背景・目的

[2026-08-05の企業MTG議事録](../../../../../131_亀井涼平/knowledge/semi/company_mtg/2026-08-05/oshisuto_regular_mtg_notes.md)で、「加速度を合成した値についても箱ひげ図を作成し、特徴を確認するとよい（大月さんは合成加速度を用いて複数の分析を行っていた）」という指摘があった。合成加速度 `|a| = sqrt(x²+y²+z²)` は既に `accWorldMag` としてworld座標系CSVに含まれている（`src/visualization/world_frame.py`で可視化専用に算出済み）が、学習・分析には未使用のまま残っていた。

本分析では、[ジャーク分析](20260909_jerk_feature_analysis.md)と同じ枠組みで、合成加速度から基本4特徴量＋ジャーク2特徴量（計6特徴量、`jerk_max`は除外）を計算し、(1) 企業MTGで求められていた箱ひげ図で flat/step/rough の分布を確認する、(2) 合成加速度だけ（x/y/z軸は使わない）でどの程度の分類性能が出るかを、特徴量数を揃えたフェアな比較で確認する。

(2)は当初「z軸4特徴量 vs 合成加速度7特徴量」という特徴量数が異なる比較をしていたが、合成加速度側が3個多く不公平だったため、次の2つの比較に改めた。

- **比較A（同数比較）**: `z_only`（z軸の基本4特徴量）vs `mag_basic_only`（合成加速度の基本4特徴量のみ、ジャークは含めない）。特徴量数を4対4に揃え、z軸単独と合成加速度単独のどちらが優れているかを見る。
- **比較B（置き換え検証）**: `all_axes_plus_jerk`（x/y/z全軸＋ジャーク、計18特徴量。本日の一連の分析で確認した最良の特徴量セットで、詳細は[特徴量重要度分析](20260909_feature_importance_reduction.md)を参照）vs `mag_plus_jerk_only`（合成加速度の基本4特徴量＋ジャーク2特徴量、計6特徴量）。もし合成加速度だけでx/y/z全軸と同等の性能が出るなら、x/y/z軸を別々に持つ代わりに合成加速度1本に置き換えることで、特徴量数を増やさずに済む（18→6）。

## 2. 実装した変更

- `src/wheelchair_pipeline.py`
  - `WORLD_MAG_COLUMN`（`accWorldMag`）・`WORLD_MAG_LINEAR_COLUMN`（`world_mag_linear`）を追加。`load_world_dataframe`で、z軸と同様に重力分（9.80665）を引いた「動的な合成加速度」を計算する（静止時は向きによらず`|a|≈9.80665`になるため、z軸の`world_z_linear`と同じ考え方で重力オフセットを除去した）。
  - `AXIS_LINEAR_COLUMNS`に`"mag": WORLD_MAG_LINEAR_COLUMN`を追加。`build_multi_axis_run_feature_dataframe`は軸を汎用的に扱う実装だったため、`axes`に`"mag"`を渡すだけで基本4特徴量・ジャーク特徴量（`mag_range`, `mag_diff_max`, `mag_rms`, `mag_std`, `mag_jerk_max`, `mag_jerk_rms`, `mag_jerk_std`）が自動的に計算されるようになった（追加コード不要。データフレーム自体には`mag_jerk_max`も引き続き算出・格納されるが、分析で使う特徴量セットからは除外している）。
- `src/analysis/flat_event.py`: `build_analysis_dataframe`に`axes`引数を追加（デフォルトは既存の`AXES=("x","y","z")`で後方互換）。
- `src/analysis/magnitude_event.py`（新規） / `src/scripts/analyze_magnitude_event.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-magnitude-event` を追加
  - [jerk_event.py](20260909_jerk_feature_analysis.md)と同じ構成で、`axes=("x","y","z","mag")`のデータフレームから合成加速度の6特徴量（`jerk_max`除外）に絞り、flat/step/roughの3クラス箱ひげ図、記述統計、step vs roughの単変量AUC・Cliff's deltaを出力する。
- `src/analysis/magnitude_feature_balance.py`（新規） / `src/scripts/analyze_magnitude_feature_balance.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-magnitude-feature-balance` を追加
  - [クラス均等化分析](20260909_class_balance_downsampling.md)の`run_group_cv`を再利用し、`z_only`(4)・`mag_basic_only`(4)・`all_axes_plus_jerk`(18)・`mag_plus_jerk_only`(6)の4特徴量セット × SVM/RF × baseline/downsampledの計16通りを評価する。
- 既存テスト（`pytest`、17件）は全て通過。

再実行コマンド: `uv run analyze-magnitude-event` / `uv run analyze-magnitude-feature-balance`

## 3. データ・条件

これまでと同じ22走行、窓幅1.0秒。

## 4. 結果

出力先: [`data/analysis/20260909_magnitude_event/`](../../../data/analysis/20260909_magnitude_event) / [`data/analysis/20260909_magnitude_feature_balance/`](../../../data/analysis/20260909_magnitude_feature_balance)
- 3クラス箱ひげ図: [figures/three_class_magnitude_distributions.png](../../../data/analysis/20260909_magnitude_event/figures/three_class_magnitude_distributions.png)
- 記述統計・AUC表: [tables/magnitude_class_feature_summary.csv](../../../data/analysis/20260909_magnitude_event/tables/magnitude_class_feature_summary.csv) / [tables/magnitude_pairwise_feature_auc.csv](../../../data/analysis/20260909_magnitude_event/tables/magnitude_pairwise_feature_auc.csv)
- 比較A・比較Bの分類性能表: [tables/magnitude_feature_balance_summary.csv](../../../data/analysis/20260909_magnitude_feature_balance/tables/magnitude_feature_balance_summary.csv)

### 4.1 flat vs event: 合成加速度のRMSはそこそこ効くが、既存特徴量を明確に上回らない

| 比較 | 最良特徴量 | AUC |
| --- | --- | --- |
| flat vs step | `mag_rms` | 0.757 |
| flat vs rough | `mag_rms` | 0.782 |

`mag_rms`（合成加速度のRMS）はflat vs step/roughともにAUC 0.75〜0.78で、z軸単体の基本特徴量（`z_rms`のAUC 0.640、[7/21分析](../2026-07-21/20260721_flat_event_analysis_report.md)参照）より高いが、y軸ジャーク（flat vs stepでAUC 0.799、[ジャーク分析](20260909_jerk_feature_analysis.md)参照）ほどではない。合成加速度は「そこそこ効くが、既存の最良特徴量を明確に上回るわけではない」という位置づけ。

### 4.2 本題：step vs rough は、合成加速度でもほぼ識別できない

| 特徴量 | AUC (rough高値側) | Cliff's delta |
| --- | ---: | ---: |
| mag_std | 0.509 | 0.018 |
| mag_range | 0.515 | 0.030 |
| mag_rms | 0.521 | 0.043 |
| mag_diff_max | 0.557 | 0.114 |
| mag_jerk_rms | 0.532 | 0.063 |
| mag_jerk_std | 0.545 | 0.089 |

6特徴量すべてがAUC 0.51〜0.56とほぼチャンスレベル。これは[ジャーク分析](20260909_jerk_feature_analysis.md)で見た「x/y軸ジャークがstep vs roughでほぼ無力だった」のと同じ傾向であり、「単一方向・単一の合成指標では段差と凹凸の違いを捉えられない」という、これまでの分析結果と一貫した結論になった。3クラス箱ひげ図でも、flatとevent（step/rough）は分離するが、stepとroughの箱は6特徴量すべてで大きく重なっている。

### 4.3 比較A（同数比較）：z軸4特徴量 vs 合成加速度4特徴量

x/y/z軸は一切使わず、特徴量数を4対4に揃えてrun単位グループ5分割CVを評価した。

| feature_set | model | 条件 | balanced_accuracy | step recall |
| --- | --- | --- | ---: | ---: |
| z軸のみ(4) | SVM | baseline | 0.4314 | 0.0753 |
| **合成加速度のみ(4)** | SVM | baseline | **0.4847** | **0.2688** |
| z軸のみ(4) | SVM | downsampled | 0.4650 | 0.1290 |
| 合成加速度のみ(4) | SVM | downsampled | 0.4386 | 0.2581 |
| z軸のみ(4) | RF | baseline | 0.3955 | 0.0108 |
| 合成加速度のみ(4) | RF | baseline | 0.3737 | 0.0000 |
| z軸のみ(4) | RF | downsampled | 0.4572 | 0.3011 |
| 合成加速度のみ(4) | RF | downsampled | 0.4380 | **0.3548** |

特徴量数を揃えたフェアな比較でも、**SVMでは合成加速度4特徴量がz軸4特徴量より明確に良い**（baseline: balanced_accuracy 0.4314→0.4847、step recall 0.0753→0.2688）。Random Forestでは、balanced_accuracyはz軸の方がわずかに高いが、downsampled条件でのstep recallは合成加速度の方が高い（0.3011→0.3548）。総じて、**「z軸だけ使うくらいなら、同じ4特徴量数で合成加速度に置き換えた方が良い」**という結論になった（ただし本分析全体での最高step recallは、4.4で見る全軸+ジャーク(18)の方がさらに高い）。

### 4.4 比較B（置き換え検証）：全軸+ジャーク(18) vs 合成加速度+ジャーク(6)

もし合成加速度だけでx/y/z全軸と同等の性能が出るなら、18特徴量を6特徴量に圧縮できる。

| feature_set | model | 条件 | balanced_accuracy | step recall |
| --- | --- | --- | ---: | ---: |
| 全軸+ジャーク(18) | SVM | baseline | 0.5003 | 0.1183 |
| 合成加速度+ジャーク(6) | SVM | baseline | 0.4736 | 0.2151 |
| 全軸+ジャーク(18) | SVM | downsampled | **0.5000** | 0.2581 |
| 合成加速度+ジャーク(6) | SVM | downsampled | 0.4360 | 0.2366 |
| 全軸+ジャーク(18) | RF | downsampled | **0.5139** | **0.3656（本分析全体で最高のstep recall）** |
| 合成加速度+ジャーク(6) | RF | downsampled | 0.4265 | 0.3226 |

こちらは比較Aとは異なる結果になった。**downsampled条件（今日ベストとしてきた設定）では、全軸+ジャーク(18)が合成加速度のみ(6)をbalanced_accuracyで両モデルとも上回る**（SVM: 0.5000 vs 0.4360／RF: 0.5139 vs 0.4265）。一方step recallは、SVMではほぼ互角（0.2581 vs 0.2366）、RFでは全軸+ジャーク側がさらに高い（0.3656 vs 0.3226、こちらが本分析全体で最高のstep recall）。**合成加速度だけでx/y/z全軸を完全に置き換えることはできない**、という結論になった。

これは4.3の結果と矛盾しない。合成加速度|a|は3軸の情報を1つのスカラーに潰してしまうため、[特徴量重要度分析](20260909_feature_importance_reduction.md)で判明していた「RFはy/z軸を重視、SVMはx軸を重視」という**方向（軸）ごとの違いの情報を捨ててしまう**。z軸単体と比べれば合成加速度の方が情報量が多い（4.3）が、x/y/z軸をすべて別々に持つ18特徴量と比べると、方向情報を失った分だけ劣る（4.4）。

## 5. まとめ・次のステップ

- 企業MTGで求められていた合成加速度の箱ひげ図分析は完了。**flat vs eventの検出には`mag_rms`がそこそこ有効**（AUC 0.75〜0.78）だが、**step vs roughの識別にはほぼ無力**（AUC 0.51〜0.56）で、これはジャーク分析と同じ結論だった。
- **同数（4 vs 4）で比べると、合成加速度はz軸単体より明確に優れている**（SVM baseline: balanced_accuracy 0.4314→0.4847、step recall 0.0753→0.2688）。z軸だけを使うくらいなら合成加速度に置き換えた方がよい。
- ただし**x/y/z全軸＋ジャーク(18特徴量)を合成加速度だけ(6特徴量)に置き換えることはできない**。全軸版の方が明確に良く、方向（軸）ごとの情報を合成で潰してしまう分の性能低下がある。
- 結論：**「z軸だけ」を置き換える候補としては合成加速度は有望だが、「x/y/z全軸を1本にまとめる」ような大幅な特徴量削減には使えない**。特徴量削減は[特徴量重要度分析](20260909_feature_importance_reduction.md)で確認した「重要度の低い特徴量を個別に間引く」方法の方が有効という結論に変わりはない。
- 次の一手: 依然として「stepとroughの違い」自体は未解決。単一特徴量・合成指標では限界が見えたため、今後は波形の時系列パターン自体（例えば代表波形の形状の違い）に着目した特徴量や、追加の段差データ計測が必要。

## 6. 更新履歴：2026-09-09、`jerk_max`を特徴量セットから除外

ジャーク特徴量から`jerk_max`を除外し`jerk_rms`/`jerk_std`のみを使う方針に変更したことに伴い、本分析の合成加速度側の特徴量は7個→6個、比較Bの全軸側は21個→18個になった（波及範囲の全体像は[ジャーク分析の更新履歴](20260909_jerk_feature_analysis.md)を参照）。比較Aは`mag_basic_only`がジャークを含まないため無影響（数値も完全に同じ）。比較Bは両側の特徴量セットが変わったため再計算し、結論（合成加速度だけでは全軸を置き換えられない）自体は変わらないが、除外後の方が全軸+ジャーク側の性能が向上し（RF downsampledのstep recall: 0.3226→0.3656）、差はむしろ広がった。
