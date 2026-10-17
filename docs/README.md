# ドキュメント

| フォルダ | 中身 |
| --- | --- |
| [`adr/`](adr/) | 設計判断の記録（ADR）。新しく書くときは [`adr/template/template.md`](adr/template/template.md) をもとにする |
| [`knowledge/`](knowledge/) | 分析・実験のメモ。日付（`YYYY-MM-DD`）のフォルダごとに置く |

## ADR

| 日付 | 内容 | Status |
| --- | --- | --- |
| 2026-05-13 | [路面不整検知 ML パイプラインの初期方針](adr/20260513_detail.md) | Draft |
| 2026-10-17 | [加速度の軸の扱い：鉛直は世界座標系の z、水平は x・y の大きさを使う](adr/20261017_axis_representation.md) | accepted |

## 分析・実験のメモ

データの時期で、前提が大きく違う。

| 時期 | データ | 注意 |
| --- | --- | --- |
| 2026-05 | モックデータ | パイプラインを作るための仮のデータ |
| 2026-06〜09 | 6.22・7.12 の実測（約 4Hz） | サンプリングが粗く、今の解析とは別物 |
| 2026-10〜 | 10.3・10.4 の実測（約 334Hz、継続ボタンあり） | **今の解析の対象**。基本は後ろ固定の 12 セッション |

### 2026-10〜（10.3・10.4 のデータ、今の解析）

| 日付 | メモ | 要点 |
| --- | --- | --- |
| 2026-10-04 | [10.3 / 10.4 データの分析経過](knowledge/2026-10-04/20261004_analysis_log_103_104.md) | 334Hz のデータでの最初の評価。ラベルの方針A |
| 2026-10-04 | [次の測定でやること](knowledge/2026-10-04/20261004_next_measurement_plan.md) | 10.3・10.4 の結果を受けた、次の測定の計画 |
| 2026-10-05 | [スマホ固定位置（後ろ／前）の比較](knowledge/2026-10-05/20261005_rear_only_analysis.md) | 前固定を除き、後ろ固定のみで評価する理由。尖度・クレスト・バースト |
| 2026-10-06 | [特徴量の寄与度の確認（バーストあり）](knowledge/2026-10-06/20261006_feature_importance_rear_only.md) | permutation importance・ablation・上位 k 個 |
| 2026-10-06 | [関連研究の特徴量を試す](knowledge/2026-10-06/20261006_related_work_features_eval.md) | 統計量・周波数・STFT・前の窓。上がるのは flat だけ |
| 2026-10-12 | [寄与度・窓幅・誤分類の内訳（バーストなし）](knowledge/2026-10-12/20261012_feature_importance_no_burst.md) | 第 16 回ゼミの発表の構成（xyz18）での分析。混同行列 |
| 2026-10-17 | [性質の違う特徴量を 1 種類ずつ足す](knowledge/2026-10-17/20261017_added_features_eval.md) | ピーク数・帯域パワー比など。step と rough の区別は上がらない |
| 2026-10-17 | [step と rough の取り違えの原因](knowledge/2026-10-17/20261017_step_rough_error_causes.md) | rough → step はラベルの粗さ、step → rough は段差の通過の仕方の違い |
| 2026-10-17 | [x・y は走る向きに依存するか](knowledge/2026-10-17/20261017_heading_dependence.md) | x・y の代わりに水平の大きさを使う（ADR の根拠） |

### 2026-06〜09（6.22・7.12 のデータ、約 4Hz）

| 日付 | メモ |
| --- | --- |
| 2026-06-30 | [前処理・特徴量抽出 実装方針](knowledge/2026-06-30/plan.md) |
| 2026-06-30 | [`world_z_linear` パイプライン実験まとめ](knowledge/2026-06-30/20260630_wheelchair_world_z_experiment_summary.md) |
| 2026-07-12 | [精度改善のためにやれること一覧](knowledge/2026-07-12/20260712_accuracy_improvement_proposals.md) |
| 2026-07-12 | [6.22 + 7.12 結合データセット学習・評価まとめ](knowledge/2026-07-12/20260712_combined_training_summary.md) |
| 2026-07-12 | [6.22 vs 7.12 比較考察](knowledge/2026-07-12/20260712_wheelchair_712_vs_622_comparison.md) |
| 2026-07-13 | [ゼミ報告用まとめ](knowledge/2026-07-13/20260713_semi_report_summary.md) |
| 2026-07-21 | [flat・step・rough の鉛直加速度分析報告書](knowledge/2026-07-21/20260721_flat_event_analysis_report.md) |
| 2026-07-22 | [World Z SVM 学習・評価結果](knowledge/2026-07-22/20260722_wheelchair_world_z_svm_training_report.md) |
| 2026-07-22 | [3 秒窓・境界 window・特徴量削減の比較実験](knowledge/2026-07-22/20260722_window_3s_holdout_experiments.md) |
| 2026-08-02 | [x/y/z 軸別の窓幅比較分析](knowledge/2026-08-02/20260802_xyz_axis_window_width_comparison.md) |
| 2026-09-09 | [クラス均等化（ダウンサンプリング）](knowledge/2026-09-09/20260909_class_balance_downsampling.md) |
| 2026-09-09 | [特徴量重要度による 18 特徴量の削減検討](knowledge/2026-09-09/20260909_feature_importance_reduction.md) |
| 2026-09-09 | [ジャーク特徴量の分析](knowledge/2026-09-09/20260909_jerk_feature_analysis.md) |
| 2026-09-09 | [合成加速度 \|a\| 特徴量の分析](knowledge/2026-09-09/20260909_magnitude_event_analysis.md) |
| 2026-09-09 | [合成加速度 + ジャーク特徴量の重要度](knowledge/2026-09-09/20260909_magnitude_feature_importance.md) |
| 2026-09-09 | [合成加速度 + ジャークとクラス均等化の組み合わせ](knowledge/2026-09-09/20260909_multi_feature_class_balance.md) |

### 2026-05（モックデータ）

| 日付 | メモ |
| --- | --- |
| 2026-05-13 | [ロードマップ](knowledge/2026-05-13/20260513_roadmap.md) |
| 2026-05-13 | [モックデータ生成スクリプト](knowledge/2026-05-13/mock_data_script.md) |
| 2026-05-13 | [Phase 1 ベースラインパイプライン](knowledge/2026-05-13/phase1_baseline_pipeline_summary.md) |
| 2026-05-19 | [Phase 1 ベースラインパイプライン（5.19 版）](knowledge/2026-05-19/phase1_baseline_pipeline_summary.md) |
