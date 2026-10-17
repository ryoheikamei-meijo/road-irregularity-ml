# ジャーク（加加速度）特徴量による段差(step)・凹凸(rough)識別力の分析

## 1. 背景・目的

企業MTG（[2026-08-05の議事録](../../../../131_亀井涼平/knowledge/semi/company_mtg/2026-08-05/oshisuto_regular_mtg_notes.md)）で、鈴木先生から「加速度を微分した加加速度（ジャーク）に着目すると、凸凹と段差の違いが現れる可能性がある」という指摘があった。この指摘は当時は今後のTODOとして残されており、着手していなかった。

本分析では、既存の `src/analysis/flat_event.py` の分析基盤（22走行、flat/step(dansa)/rough(dekobo)の3クラスラベル付き窓データ）を流用し、ジャーク特徴量を追加して次の問いに答える。

1. ジャーク特徴量は、既存の基本特徴量（range/diff_max/rms/std）と比べて `flat vs event` の識別に使えるか。
2. 本題である `step(段差) vs rough(凹凸)` の識別に、ジャークは既存特徴量より効くか。

## 2. 実装した変更

学習パイプライン本体（`build_dataset_dataframe` / `compute_window_features` / z軸4特徴量固定）には一切手を入れず、可視化・分析専用のコードにのみジャーク特徴量を追加した。

- `src/wheelchair_pipeline.py`
  - `compute_axis_window_features(values, *, prefix, timestamps_ms=None)` に `timestamps_ms` 引数を追加（デフォルト `None` で後方互換）。指定時のみ、隣接サンプルの実測タイムスタンプ差分 `dt` で加速度差分を割った真のジャーク `diff(values) / dt` を計算し、`{prefix}_jerk_max`（絶対値の最大）・`{prefix}_jerk_rms`・`{prefix}_jerk_std` を追加で返す（データフレーム自体には引き続き3種とも算出・格納される）。
  - `compute_window_features`（学習パイプラインが使う z軸専用ラッパー）は `timestamps_ms` を渡さないため、出力列・学習結果への影響はない。
  - `build_multi_axis_run_feature_dataframe`（分析専用の x/y/z 全軸特徴量関数）にのみ、窓内の `elapsed`（ミリ秒）をタイムスタンプとして渡すよう変更。これにより `build_multi_axis_dataset_dataframe` の出力に x/y/z 各軸のジャーク3特徴量（計9列）が自動的に追加される。
- `src/analysis/jerk_event.py`（新規） / `src/scripts/analyze_jerk_event.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-jerk-event` を追加
  - `flat_event.py` の `build_analysis_dataframe`（22走行分の x/y/z 多軸特徴量データフレーム）をそのまま再利用し、ジャーク特徴量（`{x,y,z}_jerk_{max,rms,std}`、計9列のうち分析で使うのは`{rms,std}`の6列。**`jerk_max`は2026-09-09時点で特徴量セットから除外**、詳細は本ドキュメント末尾の更新履歴を参照）に絞って以下を出力：
    - `flat・step・rough` の3クラス箱ひげ図（3軸 × 2特徴量の3x2グリッド）
    - 3クラスの記述統計（中央値・IQR）と `step vs rough` の単変量AUC・Cliff's delta
    - `flat vs step` / `flat vs rough` / `step vs rough` 3ペアの単変量AUC一覧
- 既存テスト（`pytest`、17件）は全て通過。`compute_window_features`（学習パイプライン向け）の出力・学習結果に変化がないことを確認した。

再実行コマンド: `uv run analyze-jerk-event`

## 3. データ・条件

[20260721_flat_event_analysis_report.md](../7.21/20260721_flat_event_analysis_report.md)と同じ22走行（6.22の11走行 + 7.12の51kg・有効11走行）、窓幅1.0秒・ストライド0.25秒。

| ラベル | 窓数 | 割合 |
| --- | ---: | ---: |
| flat | 4,102 | 88.8% |
| rough (dekobo) | 422 | 9.1% |
| step (dansa) | 93 | 2.0% |

## 4. 結果

出力先: `data/analysis/20260909_jerk_event/`
- [figures/three_class_jerk_distributions.png](../../data/analysis/20260909_jerk_event/figures/three_class_jerk_distributions.png)
- [tables/jerk_class_feature_summary.csv](../../data/analysis/20260909_jerk_event/tables/jerk_class_feature_summary.csv)
- [tables/jerk_pairwise_feature_auc.csv](../../data/analysis/20260909_jerk_event/tables/jerk_pairwise_feature_auc.csv)
- [tables/window_features_with_jerk.csv](../../data/analysis/20260909_jerk_event/tables/window_features_with_jerk.csv)

### 4.1 flat vs event（段差・凹凸を問わず平坦との違い）: ジャークは既存特徴量と同程度に効く

| 比較 | 最良特徴量 | AUC |
| --- | --- | --- |
| flat vs step | `y_jerk_rms` | 0.788 |
| flat vs rough | `y_jerk_rms` | 0.778 |

x/y軸ジャークは flat vs step / flat vs rough のいずれもAUC 0.74〜0.79で、[8/2のx/y/z軸比較分析](../8.2/20260802_xyz_axis_window_width_comparison.md)で判明していた「段差検出は水平方向(x/y)が効く」という傾向と整合する。ジャークは基本特徴量と同程度の情報を持つが、明確にそれを上回るわけではない。

### 4.2 本題：step vs rough は、ジャークでもほぼ識別できない

| 特徴量 | AUC (rough高値側) | Cliff's delta |
| --- | ---: | ---: |
| x_jerk_rms | 0.473 | -0.053 |
| x_jerk_std | 0.472 | -0.055 |
| y_jerk_rms | 0.465 | -0.069 |
| y_jerk_std | 0.473 | -0.053 |
| z_jerk_rms | 0.584 | 0.168 |
| z_jerk_std | 0.570 | 0.139 |

x/y軸のジャークは `step vs rough` でほぼチャンスレベル（AUC 0.47付近）。z軸ジャークのみ弱い差（AUC 0.57〜0.58）が見られ、roughの方がジャークが大きい傾向（Cliff's delta 正）だが、これは**既存の基本特徴量 `z_rms`（AUC 0.640）と同程度かそれ以下**であり、ジャークが既存特徴量を明確に上回る新しい手がかりにはならなかった（[20260721の既存結果](../7.21/20260721_flat_event_analysis_report.md)の `class_feature_summary.csv` と比較: `z_std`=0.595, `z_range`=0.597, `z_rms`=0.640, `z_diff_max`=0.566）。

3クラス箱ひげ図（[three_class_jerk_distributions.png](../../data/analysis/20260909_jerk_event/figures/three_class_jerk_distributions.png)）でも、flatとevent（step/rough）は明確に分離するが、stepとroughの箱は6特徴量すべてで大きく重なっている。

## 5. まとめ・次のステップ

- ジャーク特徴量は「平坦か否か」の検出には既存特徴量と同水準で使えるが、「段差(step)か凹凸(rough)か」を単一特徴量で分離する決定打にはならなかった。z軸ジャークにわずかな差はあるが、既存の`z_rms`を上回らない。
- 企業MTGでのTODOには一区切りがついたが、「stepとroughの違い」自体は依然として未解決。窓幅を広げた場合のジャーク特徴量の変化は今回未検証（次回以降の課題）。→ 多変量（x/y/z全軸の基本特徴量＋ジャークを組み合わせたSVM/RF）での識別性能や、合成加速度|a|に置き換えた場合の効果は[別分析](./20260909_magnitude_event_analysis.md)・[特徴量重要度分析](./20260909_feature_importance_reduction.md)で検証済み（合成加速度でもstep vs roughはほぼ識別できず、同じ結論）。
- 今回の分析はサンプル数の少なさ（step=93件）の影響を強く受けている可能性があり、[クラス不均衡対応の実験](./20260909_class_balance_downsampling.md)と合わせて解釈する必要がある。

## 6. 更新履歴：2026-09-09、`jerk_max`を特徴量セットから除外

当初はジャーク特徴量として`jerk_max`（窓内の絶対値最大）・`jerk_rms`・`jerk_std`の3種を使っていたが、`jerk_max`を除外し`jerk_rms`/`jerk_std`の2種のみを使う方針に変更した。この変更は本分析（3クラス箱ひげ図・AUC表）だけでなく、[全軸+ジャーク統合分析](./20260909_multi_feature_class_balance.md)・[特徴量重要度分析](./20260909_feature_importance_reduction.md)・[合成加速度分析](./20260909_magnitude_event_analysis.md)・[合成加速度の重要度分析](./20260909_magnitude_feature_importance.md)全てに波及するため、影響した図・数値は全て再生成・更新済み。

- 除外前は`flat vs step`の最良特徴量が`y_jerk_max`（AUC 0.799）だったが、除外後は`y_jerk_rms`（AUC 0.788）に代わった。結論（ジャークは基本特徴量と同程度、明確に上回らない）自体は変わらない。
- `step vs rough`の最良特徴量も`z_jerk_max`（AUC 0.587）から`z_jerk_rms`（AUC 0.584）に代わったが、ほぼ同水準で結論は変わらない。
- 多変量（SVM/RF）での分類性能への影響は、[特徴量重要度分析](./20260909_feature_importance_reduction.md)・[合成加速度分析](./20260909_magnitude_event_analysis.md)側でより顕著に現れている（`jerk_max`除外後、複数の設定で性能が改善した）。
