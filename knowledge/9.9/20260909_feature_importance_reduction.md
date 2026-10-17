# 特徴量重要度分析による18特徴量の削減検討（RF・SVM比較）

## 1. 背景・目的

本日の一連の分析で、学習に使う特徴量を実運用のz軸4個から全軸(x/y/z)+ジャークの18個に増やすと性能が改善することを確認したが（[合成加速度分析の比較B](./20260909_magnitude_event_analysis.md)で全軸+ジャーク(18)が合成加速度のみ(6)を上回ることを確認済み）、18個は多く、どの特徴量が実際に効いているのか不明なまま使っていた。特徴量が多いほど、この後のサンプル数不足（dansa93件）と組み合わさって過学習のリスクも高まる。

本分析では、SVM・Random Forestそれぞれの最良設定（全軸+ジャーク18特徴量、ダウンサンプリングあり）について特徴量ごとの寄与度を測り、(1) 重要度の低い特徴量を削っても性能が落ちないか、(2) **モデルの種類によって「重要な特徴量」が変わるか**を確認する。permutation importanceはモデルの種類を問わず使える指標なので、SVM（RBFカーネル、決定木のような組み込み重要度を持たない）でも同じ方法で計算できる。

> **注記（2026-09-09）**：当初はジャーク特徴量に`jerk_max`を含む21特徴量で本分析を実施していたが、[ジャーク分析の更新履歴](./20260909_jerk_feature_analysis.md)の通り`jerk_max`を特徴量セットから除外したため、18特徴量に組み直して全面的に再計算した。本ドキュメントの数値・図・結論は全て再計算後のもの。

## 2. 実装した変更

- `src/analysis/feature_importance.py`（新規） / `src/scripts/analyze_feature_importance.py`（新規、CLIエントリ） / `pyproject.toml` に `analyze-feature-importance` を追加
  - [クラス均等化分析](./20260909_class_balance_downsampling.md)と同じrun単位グループ5分割CVの枠組みで、各foldの学習データ（ダウンサンプリング後）でモデルを学習し、**そのfoldのテストデータに対する permutation importance**（`sklearn.inspection.permutation_importance`、`scoring="balanced_accuracy"`、`n_repeats=20`）を計算し、5fold平均を特徴量の重要度とした。**Random ForestとSVMの両方**で計算し、モデルごとに独立してランキングする。
    - permutation importanceを選んだ理由: モデルの種類（SVM/RF問わず）に依存せず、「その特徴量をシャッフルすると性能がどれだけ落ちるか」という汎化への実質的な寄与を直接測れるため。Random Forest組み込みのimpurity-based importance（`feature_importances_`）は参考値として併記した。
  - モデルごとに上位N個（デフォルト10個）を「そのモデル用の縮小特徴量セット」とし、21特徴量版・相手モデルの縮小セットとあわせて、run単位グループ5分割CV評価（[クラス均等化分析](./20260909_class_balance_downsampling.md)と同じ `run_group_cv`）で性能を比較した。
- 既存テスト（`pytest`、17件）は全て通過。

再実行コマンド: `uv run analyze-feature-importance`（`--top-k`で残す特徴量数を変更可能）

## 3. データ・条件

これまでと同じ22走行、窓幅1.0秒、全軸+ジャーク18特徴量。重要度算出はSVM・Random Forest（`configs/wheelchair_world_z_combined_{svm,random_forest}.yaml`）それぞれ、ダウンサンプリングありの設定で実施。

## 4. 結果

出力先: [`data/analysis/20260909_feature_importance/`](../../data/analysis/20260909_feature_importance/)
- モデル間比較図: [figures/feature_importance_agreement.png](../../data/analysis/20260909_feature_importance/figures/feature_importance_agreement.png)
- Random Forest単体の重要度図・表: [figures/feature_importance_random_forest.png](../../data/analysis/20260909_feature_importance/figures/feature_importance_random_forest.png) / [tables/feature_importance_random_forest.csv](../../data/analysis/20260909_feature_importance/tables/feature_importance_random_forest.csv)（fold毎の生値は[feature_importance_random_forest_by_fold.csv](../../data/analysis/20260909_feature_importance/tables/feature_importance_random_forest_by_fold.csv)）
- SVM単体の重要度図・表: [figures/feature_importance_svm.png](../../data/analysis/20260909_feature_importance/figures/feature_importance_svm.png) / [tables/feature_importance_svm.csv](../../data/analysis/20260909_feature_importance/tables/feature_importance_svm.csv)（fold毎の生値は[feature_importance_svm_by_fold.csv](../../data/analysis/20260909_feature_importance/tables/feature_importance_svm_by_fold.csv)）
- RF/SVM並記表: [tables/feature_importance_rf_vs_svm.csv](../../data/analysis/20260909_feature_importance/tables/feature_importance_rf_vs_svm.csv)
- 縮小特徴量セット一覧: [tables/reduced_feature_set_random_forest.txt](../../data/analysis/20260909_feature_importance/tables/reduced_feature_set_random_forest.txt) / [tables/reduced_feature_set_svm.txt](../../data/analysis/20260909_feature_importance/tables/reduced_feature_set_svm.txt)
- 縮小 vs 全特徴量の性能比較: [tables/reduced_vs_full_feature_comparison.csv](../../data/analysis/20260909_feature_importance/tables/reduced_vs_full_feature_comparison.csv)

### 4.0 図の見方

**`feature_importance_random_forest.png` / `feature_importance_svm.png`**（モデル単体の重要度図）は、各特徴量ごとに「●（点）＋横に伸びる細い線」の1セットで表示している（当初は棒グラフ＋エラーバーで作ったが、標準偏差がバーの長さを上回る特徴量が多く、バーが誤差線に埋もれて逆に読みにくかったため、5foldしかないことを活かして「平均点＋実際の最小〜最大の範囲」というシンプルな表現に描き直した）。

- **●（点）の位置＝5foldの平均**。その特徴量の値を無意味になるようランダムにシャッフルしたとき、balanced_accuracyがどれだけ下がったかの平均値。**右にあるほど「シャッフルすると困る＝重要」**。縦の基準線（0の位置）付近や左側にある特徴量は、シャッフルしても性能がほぼ変わらない、つまり実質的に使われていない・ノイズに近いことを意味する（図ではこの2種を色分けし、0以上＝青丸、0未満＝グレー丸としている）。
- **点から左右に伸びる細い灰色の線＝5分割CVの各fold（データの分け方を変えた5パターン）で実際に得られた重要度の最小値〜最大値の範囲**。汎化性能そのものを表す線ではないが、間接的な目安にはなる。
  - 線が短い＝どのfoldで計算してもだいたい同じ値になった＝この特徴量の重要度は安定して信頼できる。
  - 線が長い＝fold（データの分け方）によって値が大きく変動した＝「本当に重要か、たまたま今回のデータ split で高く出ただけか」自信が持てない。特にダウンサンプリング後は1foldあたりのテストデータが少ない（dansaは各fold66〜81件程度）ため、線は全体的に長め＝ばらつきが大きい。線が0をまたいでいる特徴量は、foldによって「重要」と出たり「無意味以下」と出たりしており、特に解釈に注意が必要。

**`feature_importance_agreement.png`**（モデル間比較図）は、単純な横棒グラフに戻した（fold間ばらつきの線は付けず、5fold平均の値だけを表示）。同じ特徴量に対してRF（青）とSVM（オレンジ）の棒を並べている。両方とも右側に長く伸びている特徴量（`z_rms`など）は「モデルが変わっても重要」という強い根拠になり、片方だけ長い特徴量（例:`z_std`はRFのみ長い、`x_jerk_max`はSVMのみ長い）はそのモデル特有の着目点であることを示す。

### 4.1 重要度ランキング（RF・SVMそれぞれの上位10）

| 順位 | Random Forest | importance | SVM | importance |
| ---: | --- | ---: | --- | ---: |
| 1 | `z_rms` | 0.0258 | `z_rms` | 0.0237 |
| 2 | `x_diff_max` | 0.0094 | `z_diff_max` | 0.0115 |
| 3 | `z_jerk_rms` | 0.0093 | `x_diff_max` | 0.0093 |
| 4 | `y_rms` | 0.0086 | `x_range` | 0.0079 |
| 5 | `z_range` | 0.0083 | `x_jerk_std` | 0.0075 |
| 6 | `y_std` | 0.0070 | `x_jerk_rms` | 0.0069 |
| 7 | `y_range` | 0.0068 | `x_std` | 0.0038 |
| 8 | `y_jerk_std` | 0.0055 | `x_rms` | 0.0038 |
| 9 | `z_std` | 0.0044 | `z_range` | 0.0016 |
| 10 | `z_jerk_std` | 0.0039 | `z_std` | -0.0006 |

**両モデルで`z_rms`が1位で一致**し、上位10全体で見ても共通するのは `x_diff_max`, `z_range`, `z_rms`, `z_std` の4個だった（`jerk_max`除外前は3個）。

- **Random Forestはy軸・z軸のRMS/標準偏差**（`y_rms`, `z_range`, `y_std`, `y_range`, `z_std`）や**z軸ジャーク**を重視する。
- **SVMはx軸の差分・ジャーク系**（`x_diff_max`, `x_range`, `x_jerk_std`, `x_jerk_rms`, `x_std`, `x_rms`）や `z_diff_max` を重視する。

モデルの仕組みの違い（RF: 軸ごとの閾値分割の繰り返し、SVM: 標準化後の全特徴量を使った距離ベースの境界）を反映して、着目する特徴量の傾向がかなり異なることが分かった。誤差バー（fold間標準偏差）も大きく、ダウンサンプリング後の少ないテストデータに起因する分散の影響を強く受けている点は注意が必要（詳細は[figures/feature_importance_agreement.png](../../data/analysis/20260909_feature_importance/figures/feature_importance_agreement.png)を参照）。

### 4.2 SVMは「自分の」上位10特徴量が最良だが、RFは全18特徴量のままが最良

| feature_set | model | 条件 | balanced_accuracy | step recall |
| --- | --- | --- | ---: | ---: |
| 全18特徴量 | SVM | downsampled | 0.5000 | 0.2581 |
| RF上位10 | SVM | downsampled | 0.4876 | 0.2366 |
| **SVM上位10** | SVM | downsampled | **0.5356** | **0.3333** |
| **全18特徴量** | RF | downsampled | **0.5139** | **0.3656** |
| RF上位10 | RF | downsampled | 0.4909 | 0.3118 |
| SVM上位10 | RF | downsampled | 0.4836 | 0.2581 |

- **SVMは「SVM自身の上位10特徴量」を使うと、今日の全実験の中で最良のbalanced_accuracy**（0.5356, step recall 0.3333）になった。全18特徴量やRFの上位10特徴量を使うより明確に良い（`jerk_max`除外前とほぼ同水準の結果）。
- **RFは今回、上位10への絞り込みがむしろ逆効果になった**。「RF自身の上位10特徴量」（0.4909, step recall 0.3118）より、**全18特徴量をそのまま使う方が良い**（0.5139, step recall 0.3656＝本日最高のstep recall）。`jerk_max`を含んでいた前回の分析ではRFも上位10への絞り込みが有効だったが、`jerk_max`除外後は逆の結果になった——RFにとっては、除外前に効いていた`z_jerk_max`・`y_jerk_max`が上位10から消えたことで、上位10だけでは情報が足りなくなったと考えられる。
- つまり**「上位10に絞れば必ず良くなる」わけではなく、モデルや特徴量セットの構成によって結果が変わる**。SVMではモデル自身の重要度に基づく絞り込みが有効、RFでは（少なくとも今回のjerk_max除外後の18特徴量では）絞り込まず全部使う方が良い、という非対称な結論になった。

## 5. まとめ・次のステップ

- RFとSVMは全く異なる特徴量に着目している（一致するのは`x_diff_max`, `z_range`, `z_rms`, `z_std`の4個）。RFは鉛直・水平方向の振幅系（RMS/std）、SVMは水平方向の差分・ジャーク系を重視する。
- 特徴量選択の効果はモデルによって非対称：**SVMは自分自身のpermutation importanceに基づく上位10特徴量に絞るのが最良**（balanced_accuracy 0.5356, step recall 0.3333）。**RFは絞り込まず全18特徴量を使う方が良い**（balanced_accuracy 0.5139, step recall 0.3656＝本日最高のstep recall）。
- RFとSVMが異なる情報を見ている（＝互いに補完的な可能性がある）ことから、将来的にはアンサンブル（両モデルの予測を組み合わせる）も検討候補になり得るが、本日は未検証。
- 注意点：重要度の推定は各foldのテストデータ数が少なく（dansaは各fold66〜81件）誤差が大きい。この結果は「大まかな傾向」として扱い、追加計測でサンプル数が増えた際に再検証するのが望ましい。RFの「上位10 vs 全18」の逆転自体も、この誤差の範囲内である可能性がある点には留意する。
- 次の一手: (a) SVMは上位10特徴量に固定した上でのハイパーパラメータ再調整、RFは全18特徴量を使う前提でのハイパーパラメータ再調整、(b) 依然として残るサンプル数不足の解消（追加計測）。合成加速度+ジャーク特徴量(6)についても同様の重要度分析を[別途実施](./20260909_magnitude_feature_importance.md)し、こちらは`mag_rms`のみが有効でRF/SVM間の食い違いも小さいという、より明快な結果が得られた。

## 6. 更新履歴：2026-09-09、`jerk_max`を特徴量セットから除外

当初（21特徴量版）はRFの上位10に`z_jerk_max`（6位）・`y_jerk_max`（8位）、SVMの上位10に`x_jerk_max`（2位）が入っており、特に`x_jerk_max`はSVMにとって2番目に重要な特徴量だった。`jerk_max`除外後（18特徴量版）は全て再計算し、上記の数値・ランキング・図は全て新しい結果に置き換えている（詳細な波及範囲は[ジャーク分析の更新履歴](./20260909_jerk_feature_analysis.md)を参照）。

除外の結果、SVMの結論（自身の上位10特徴量が最良）はほぼ変わらなかったが、**RFは「上位10に絞る」ことの効果自体が逆転した**（除外前は上位10が全特徴量より良かったが、除外後は全18特徴量の方が上位10より良い）。これは特徴量削減の効果がジャーク特徴量の構成に依存する、という追加の学びになった。
