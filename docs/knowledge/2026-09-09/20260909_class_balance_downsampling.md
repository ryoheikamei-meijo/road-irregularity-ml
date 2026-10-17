# クラス均等化（ダウンサンプリング）による3クラス分類性能への影響

## 1. 背景・目的

現状、flat/step(dansa)/rough(dekobo)の3クラスには大きな不均衡があり（[20260909のジャーク分析](20260909_jerk_feature_analysis.md)と同じ22走行データで flat 88.8%・rough 9.1%・step 2.0%）、`src/models.py` では既に `class_weight="balanced"`（コスト側の重み付け）を実装済みだが、それでも過去のゼミ報告（[7/13報告](../2026-07-13/20260713_semi_report_summary.md)等）で「段差(dansa) recallが低い」ことが繰り返し課題として挙がっている。

本分析では、`class_weight="balanced"` に加えて／代えて、学習データそのものをクラスごとに等数までダウンサンプリング（33%均等化）した場合に、識別性能、特にstep(段差)のrecallがどう変わるかを確認する。

## 2. 実装した変更

学習パイプライン本体（`train_wheelchair_model.py` / `src/models.py`）は変更せず、新しい分析専用スクリプトを追加した。

- `src/analysis/class_balance.py`（新規） / `src/scripts/analyze_class_balance.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-class-balance` を追加
  - [ジャーク分析](20260909_jerk_feature_analysis.md)と同じ `flat_event.py` の `build_analysis_dataframe`（22走行）を再利用し、実運用と同じ z軸4特徴量（`Z_FEATURE_COLUMNS`）のみを使用。
  - モデル設定は実運用の `configs/wheelchair_world_z_combined_svm.yaml` / `configs/wheelchair_world_z_combined_random_forest.yaml` をそのまま読み込み、`build_model()` で生成（パラメータの二重管理を避けた）。
  - run単位のグループ5分割CV（`StratifiedGroupKFold`、`flat_event.py`の`build_multiclass_group_cv`と同じ`random_state=42`）で評価。**各foldの学習データのみ**、クラスごとに最小クラス件数（＝そのfoldのdansa件数）まで無作為抽出してダウンサンプリングする。**テストfoldは一切加工せず**、実運用時と同じ自然なクラス比率のまま評価する。
  - `balance_classes=False`（ベースライン、`class_weight="balanced"`のみ）と `balance_classes=True`（ダウンサンプリング、追加の重み付けなし）を、SVM・Random Forestそれぞれで実行し、balanced_accuracy・macro F1・クラス別recall・混同行列を比較。
- 既存テスト（`pytest`、17件）は全て通過。

再実行コマンド: `uv run analyze-class-balance`

## 3. データ・条件

[ジャーク分析](20260909_jerk_feature_analysis.md)と同じ22走行（6.22の11走行 + 7.12の51kg・有効11走行）、窓幅1.0秒、z軸4特徴量（`z_range`, `z_diff_max`, `z_rms`, `z_std`）のみ。

各foldでのダウンサンプリング後の学習データ件数（[fold_class_counts_svm.csv](../../../data/analysis/20260909_class_balance/tables/fold_class_counts_svm.csv)）:

| fold | ダウンサンプリング前(flat/dansa/dekobo) | ダウンサンプリング後(各クラス) |
| --- | --- | --- |
| 1 | 3305 / 76 / 345 | 76 / 76 / 76 |
| 2 | 3195 / 76 / 330 | 76 / 76 / 76 |
| 3 | 3276 / 73 / 349 | 73 / 73 / 73 |
| 4 | 3302 / 66 / 349 | 66 / 66 / 66 |
| 5 | 3330 / 81 / 315 | 81 / 81 / 81 |

dansaが各foldで66〜81件しかないため、ダウンサンプリング後の学習データは**1foldあたり合計200〜243件**（ダウンサンプリング前の合計約3700〜3980件から約94〜95%を捨てる計算）になる。これが後述の精度低下の主要因である。

## 4. 結果

出力先: [`data/analysis/20260909_class_balance/`](../../../data/analysis/20260909_class_balance)
- 比較図: [figures/class_balance_comparison.png](../../../data/analysis/20260909_class_balance/figures/class_balance_comparison.png)
- 集計表: [tables/class_balance_summary.csv](../../../data/analysis/20260909_class_balance/tables/class_balance_summary.csv)
- 混同行列・classification_report: `tables/confusion_matrix_{svm,random_forest}_{baseline,downsampled}.csv`、`tables/classification_report_{svm,random_forest}_{baseline,downsampled}.txt`

| model | 条件 | balanced_accuracy | macro_f1 | flat recall | step recall | rough recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| SVM | baseline (class_weight=balanced) | 0.4314 | 0.3886 | 0.6646 | **0.0753** | 0.5545 |
| SVM | downsampled (33%均等) | 0.4650 | 0.3913 | 0.6616 | **0.1290** | 0.6043 |
| Random Forest | baseline (class_weight=balanced) | 0.3955 | 0.4125 | 0.9766 | **0.0108** | 0.1991 |
| Random Forest | downsampled (33%均等) | 0.4572 | 0.3384 | 0.5256 | **0.3011** | 0.5450 |

### 4.1 SVM：穏当な改善

ダウンサンプリングにより、step recallが 0.075→0.129（約1.7倍）、rough recallも 0.555→0.604 に改善し、flat recallはほぼ変わらない（0.665→0.662）。balanced_accuracyも 0.431→0.465 に改善し、macro F1はほぼ横ばい（0.389→0.391）。**SVMでは、ダウンサンプリングは他の指標を大きく犠牲にせずにstep recallを改善できる。**

### 4.2 Random Forest：大きなトレードオフを伴う改善

ベースラインのRFは、flat recallが0.977と極端に高い一方でstep recallは0.011とほぼ検出できていない（「ほぼ全部flatと予測する」状態に近い）。ダウンサンプリング後はstep recallが0.011→0.301（約27倍）、rough recallも0.199→0.545に大きく改善するが、その代償として**flat recallが0.977→0.526まで急落し、全体の正解率（accuracy）も88.6%→52.3%まで低下する**。balanced_accuracyは0.396→0.457に改善するが、**macro F1はむしろ0.413→0.338に悪化**している（flatの適合率低下が全体のF1バランスを崩すため）。

## 5. まとめ・次のステップ

- ダウンサンプリング（33%均等化）は、SVM・RFいずれでもstep(段差)のrecallを確実に改善する。特にRFでの改善幅は大きい（1.1%→30.1%）。
- ただしその効果はモデルによってトレードオフの大きさが大きく異なる。**SVMは穏当な改善**（他指標をほぼ犠牲にしない）だが、**RFは全体の正解率を大きく犠牲にする**（88.6%→52.3%）荒い改善であり、単純に「良くなった」とは言えない。
- 根本原因は、dansa(段差)がそもそも1foldあたり66〜81件しかなく、ダウンサンプリング後の学習データが200件程度まで激減すること。**サンプル数不足という制約自体は解消していない**ため、真に必要なのは段差データの追加計測、またはSMOTE等の合成サンプル生成（本分析では未実施）である。
- 次の一手としては、(a) SVMでのダウンサンプリング＋`class_weight="balanced"`の併用、(b) 窓幅を広げてstepの有効サンプル数自体を変化させる、(c) 段差データの重点的な追加計測、が検討候補。→ (a)に関連して、上表のRFではダウンサンプリングによりflat recallが0.9766→0.5256まで急落していたが、z軸のみから全軸(x/y/z)+ジャーク(18特徴量、`jerk_max`除外後)に増やすと、ダウンサンプリングしてもflat recallは0.6997まで回復することを確認した（[特徴量重要度分析](20260909_feature_importance_reduction.md)の`reduced_vs_full_feature_comparison.csv`より）。
