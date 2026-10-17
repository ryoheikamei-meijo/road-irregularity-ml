# 2026-07-12 精度改善のためにやれること一覧

## 背景

6.22 + 7.12 結合データセットでの再学習（[[20260712_combined_training_summary]]）でも dansa recall はほぼ0のままだった。データ量以前に、現在のパイプラインには構造的なボトルネックがあるため、それを整理し改善案をまとめる。

## 現状の構造的ボトルネック

1. **1窓あたり実質4サンプルしかない**
   サンプリング間隔が約257ms（≒4Hz）で窓が1.0秒のため、`z_std` / `z_rms` は「4点の統計量」になっており、統計量として極めてノイジー。窓ごとのばらつきが本質的な信号差を覆い隠している。
2. **振幅系特徴量しかなく、dansa と dekobo が分離できない**
   現在の4特徴量の平均は dansa（z_range 20.7）と dekobo（24.6）でほぼ重なる。両者の本当の違いは振幅ではなく**時間構造**（dansa=約2秒の単発衝撃、dekobo=5〜8秒の持続振動）だが、1秒窓単体からはその違いが原理的に見えない。
3. **取得済みなのに捨てている列がある**
   `speedMps`・`accWorldX`・`accWorldY`・`accWorldMag` は全runに存在するが未使用。実測で `wy_std` と `z_std` の相関は約0.40で、Y軸はZ軸と独立な情報を持つ。

## 提案A: 今のデータのまま実装できる改善（優先度順）

### A-1. 時間文脈を特徴量に入れる（dansa/dekobo分離の本命）★実装済み

前後の窓の情報を特徴量に加える。「周囲は静かなのにこの窓だけ跳ねた」=dansa、「周囲もずっと荒れている」=dekobo という duration 差を窓単位の特徴に翻訳する。

実装内容（`src/wheelchair_pipeline.py`）:
- `z_std_prev` / `z_std_next`: 前後の窓の `z_std`（端は自身の値で埋める）
- `z_std_ratio`: `z_std` ÷ 周囲±4窓（±1秒）の `z_std` 移動中央値。孤立スパイクで大、持続振動で≒1

### A-2. 予測の後処理（スムージング）★実装済み

窓単位の予測をそのまま使わず、連続性ルールで整形する。event系予測の連続区間の推定継続時間が閾値以上なら dekobo、未満なら dansa に揃える。

実装内容: `smooth_predicted_labels(labels, window_seconds, stride_seconds, dekobo_min_duration_seconds=3.5)`
- 既定閾値3.5秒は「dansa最長 3.1秒 < 3.5 < dekobo中央値 4.9秒（6.22実測）」から設定
- 注意: 6.22には0.5秒しかない短い dekobo イベントも存在し、それらは dansa 側に倒れる。閾値は要チューニング

### A-3. X/Y軸・合成加速度・速度の特徴量追加 ★実装済み

- `accWorldX` / `accWorldY` の std・range: 段差乗り越えは前輪の突き上げ+前後方向の減速が同時に起きるため、Z単独より判別材料が増える
- `accWorldMag` の std・range
- `speedMps`: `speed_mean`（窓内平均速度）と `speed_delta`（窓内の速度変化。段差前の減速行動が負値として現れる）。速度正規化は 6.22（速度0〜4.0m/s）と 7.12（0.75〜1.67m/s）のベースラインノイズ差の吸収にも効く

実装内容: config の `feature.extended: true` で有効化（既定 false、既存データセットとの互換維持）。

### A-4. dansa向けの形状特徴量（未実装）

4点しかない窓内でも計算できるもの: 符号付き最大変化（落ち込み→突き上げの順序）、窓内最小値（段差落下の負ピーク）、歪度。dansa は「一方向の急変」、dekobo は「両方向のランダム振動」なので符号情報が効く。[[20260630_wheelchair_world_z_experiment_summary]] の「次にやるべきこと」5とも合致。

### A-5. 2段階分類器（未実装）

「flat vs イベント」→「dansa vs dekobo」の2段構成。1段目は不均衡が緩く高精度にでき、2段目は dansa 93 vs dekobo 422 の比較的マシな比率で、A-1/A-4 の時間構造特徴が最も効く問題設定になる。

### A-6. 評価方法の変更（未実装）

- **leave-one-run-out 交差検証**: eval 2件⇔4件の切り替えで指標が大きく動いた通り、固定splitでは偶然に左右される。22 run で LORO-CV を回せば安定した比較基準になる
- **イベント単位の評価**: 「その dansa イベントを1窓でも検出できたか」で数える評価を併設する。窓単位 recall は境界窓の失敗で過小評価される

### A-7. モデル側のチューニング（未実装）

- SVM の `C` / `gamma` を GroupKFold（run単位）でグリッドサーチ（現状デフォルト値のまま）
- `HistGradientBoostingClassifier` の追加（表形式データでは RF より強いことが多い）
- SVM を確率出力にして dansa の判定閾値を下げる（recall重視の運用チューニング）

## 提案B: 次回収集時のプロトコル変更

1. **サンプリングレートを50〜100Hzに上げる（最重要）**
   路面振動の主成分は数Hz〜数十Hzにあり、4Hzでは物理的に情報が消失している（エイリアシングも発生）。上がれば FFT 系特徴量（周波数帯域別パワー）が使えるようになり、dansa/dekobo 判別は質的に変わる。アプリ側の設定変更で済むなら費用対効果が最も高い。
2. **端末の固定方法を統一**する（6.22 と 7.12 で flat ノイズが2割違った原因の切り分け）
3. **速度を意図的に変えた同一路面の走行**を数本入れる（速度正規化特徴の検証用）
4. **stop未押下のままセッション終了したら自動でstopを打つ**仕様をアプリに入れる（`20260711202058` の dekobo_stop 欠損の再発防止）

## 推奨着手順

効果/コスト比で: **A-2（後処理）→ A-1（時間文脈特徴）→ A-3（XY・速度特徴）→ A-6（LORO-CV）→ A-5（2段階分類）**。A-1〜A-3 は実装済み（2026-07-12）。B-1 は次回収集までにアプリ設定を必ず確認する。

## 実装済み分の使い方

```yaml
# config に追記すると拡張特徴量が有効になる
feature:
  axis: world_z_linear
  extended: true
```

```python
# 予測後のスムージング
from src.wheelchair_pipeline import smooth_predicted_labels

smoothed = smooth_predicted_labels(
    y_pred.tolist(),
    window_seconds=1.0,
    stride_seconds=0.25,
)
```

## 検証結果（2026-07-12実装後、同一条件で再学習）

[[20260712_combined_training_summary]] の「採用版（eval 2run）」と全く同じ train/eval split（train 20 run・3,990 windows / eval 2 run・627 windows: `20260622180835`, `20260622182112`）で、拡張特徴量（A-1+A-3）とスムージング（A-2）の効果を検証した。

- データセット: `data/features/20260712_combined/wheelchair_world_z_dataset_combined_51kg_extended.csv`（15列→20列に拡張、ラベル数は従来版と完全一致 dansa 93 / dekobo 422 / flat 4,102）
- config: `configs/wheelchair_world_z_622_extended.yaml`, `configs/wheelchair_world_z_712_extended.yaml`（`feature.extended: true`）

### 結果比較（all_eval）

| 条件 | モデル | accuracy | dansa recall | dekobo recall | macro f1 |
|---|---|---:|---:|---:|---:|
| 従来（4特徴量, ベースライン） | RF | 0.7927 | 0.0000 | 0.1053 | 0.3533 |
| 従来（4特徴量, ベースライン） | SVM | 0.7129 | 0.0789 | 0.4526 | 0.4425 |
| **A-1+A-3（拡張特徴量, raw）** | RF | 0.8022 | 0.0000 | 0.1474 | 0.3756 |
| **A-1+A-3（拡張特徴量, raw）** | SVM | 0.7624 | 0.1316 | 0.4316 | 0.4745 |
| A-1+A-3+A-2（拡張特徴量+スムージング） | RF | 0.7879 | 0.1316 | 0.0000 | 0.3509 |
| A-1+A-3+A-2（拡張特徴量+スムージング） | SVM | 0.7464 | 0.5000 | 0.1789 | 0.4680 |

### 考察

- **拡張特徴量（A-1+A-3）は raw predictionの時点で両モデルとも一貫して改善**。SVMは accuracy +5pt、dansa recall +5pt、macro f1 +0.03。RFも accuracy・dekobo recall・macro f1 が全て微増。XY軸・速度・時間文脈特徴が実際に効いている。
- **スムージング（A-2）は狙い通りには効かず、dansa/dekoboの間でトレードオフが発生**。SVMではdansa recallが0.13→0.50に激増した一方、dekobo recallが0.43→0.18に激減。RFに至ってはdekobo recallが0.15→0.00に潰れた。
  - 原因: 現在の実装は「非flatの連続区間をまとめて1つのイベントとみなし、継続時間だけでdansa/dekoboを二択で決め打ちする」ため、raw predictionが本来のdekobo区間を細切れに検出していた場合（間に誤ってflat予測が挟まる等）、各断片が3.5秒未満と判定されてdansaに誤って統合されてしまう。逆に本来1回のdansaでも近接する別イベントと連結されるとdekobo扱いになる。
  - **結論: A-2は現状の閾値ロジックのままでは無条件に採用すべきではない**。dansa recallを最優先する運用であれば有効だが、dekoboを犠牲にする。閾値のチューニングや「多数決＋継続時間」のハイブリッド化など改良の余地あり。
- 総合すると、**今回の実装分でまず確実に採用すべきはA-1+A-3（拡張特徴量）**。A-2（スムージング）は運用目的（dansa重視かdekobo重視か）に応じて選択的に使うべきもので、現状は無条件の改善策ではないと判断する。

## dekobo recall向け追加検証（2026-07-12, neighbor特徴 → 境界window除外）

上記の考察を受けて、dekobo recallを上げる方向で追加検証した。同一train/eval split（train 20 run・eval `20260622180835`, `20260622182112`）で段階的に検証。

### 診断結果

SVM(拡張特徴量版)のeval予測を分析したところ:

1. **dekoboイベントは5/5全て「1窓でも」検出できている**（イベント単位の検出漏れはゼロ）。問題は「イベント内窓の取りこぼし率」。
2. **取りこぼした窓のz_std平均は6.1**で、検出できた窓（12.0）よりflat（4.7）に近い。「dekoboイベント内の相対的に静かな瞬間」が原因で、これは**振幅特徴量だけでは原理的に解決できない**。
3. `z_std_ratio`（A-1で追加済み）は「自分÷周囲」の**比**なので、周囲も持続的に荒れているdekobo区間では1に近づき、flatと区別がつかなくなる欠陥があった。

### 対策1: neighbor特徴量の追加（`z_std_neighbor_mean` / `z_std_neighbor_max`）★実装済み

`z_std_ratio`が捉え損ねる「周囲の絶対的な荒れ具合」を直接特徴量にした。`add_context_features()`に追加（`CONTEXT_FEATURE_COLUMNS`に追加、rolling mean/maxを計算）。

| モデル | 条件 | accuracy | dansa recall | dekobo recall | macro f1 |
|---|---|---:|---:|---:|---:|
| SVM | A-1+A-3のみ | 0.7624 | 0.1316 | 0.4316 | 0.4745 |
| SVM | **+neighbor特徴** | 0.7751 | 0.1053 | **0.5789** | **0.4991** |
| RF | A-1+A-3のみ | 0.8022 | 0.0000 | 0.1474 | 0.3756 |
| RF | +neighbor特徴 | 0.7974 | 0.0000 | 0.1789 | 0.3841 |

SVMのdekobo recallが+15pt改善。**スムージング等の後処理を一切使わず、raw predictionの時点で改善**した点が重要（前回のA-2はdekobo recallを犠牲にdansaを稼ぐ副作用があったが、neighbor特徴はその副作用なしに両方微増〜大幅増）。

### smooth_v2の再検証（neighbor特徴込みのraw predictionに適用）

「flatギャップ2窓まで許容してイベント断片をマージ→区間の継続時間+多数決でdansa/dekoboを決定」というA-2改良版（`smooth_v2`、パイプラインには未組み込みの検証用実装）を、neighbor特徴込みのraw predictionに適用した。

| 条件 | dansa recall | dekobo recall | macro f1 |
|---|---:|---:|---:|
| raw（neighbor特徴込み） | 0.1053 | 0.5789 | 0.4991 |
| + A-2（旧スムージング） | 0.1842 | 0.2947 | 0.4466 |
| + smooth_v2（gap許容+多数決） | 0.0000 | **0.7263** | 0.4712 |

smooth_v2はdekobo recallを0.73まで押し上げる最強の設定だが、**dansaが完全に0になる**トレードオフは解消されなかった。「dekobo検出を最優先する運用」なら有効だが、多クラス全体の性能（macro f1）としてはneighbor特徴のみのrawの方が優れる。→ **デフォルトでは採用せず、dekobo特化運用向けのオプションとして温存**（`smooth_predicted_labels`は実装済みだが呼び出し側で明示的に選択する形のまま）。

### 対策2: 境界windowをtrainから除外

overlap 0.05〜0.5（イベントに部分的にかかっているが閾値0.5未満なのでflatラベルになった窓）が73窓（train中52窓）あり、flatクラスの特徴分布を汚していると仮説を立てて検証。`load_run_intervals_from_config` + `compute_overlap_ratio`（既存の公開関数）で該当windowを特定し、**trainからのみ除外**（evalは変更なし）して再学習。

| モデル | 条件 | accuracy | dansa recall | dekobo recall | macro f1 |
|---|---|---:|---:|---:|---:|
| SVM | neighbor特徴のみ | 0.7751 | 0.1053 | 0.5789 | 0.4991 |
| SVM | **+境界window除外** | 0.7767 | 0.1053 | 0.5895 | **0.5014** |
| RF | neighbor特徴のみ | 0.7974 | 0.0000 | 0.1789 | 0.3841 |
| RF | **+境界window除外** | 0.7974 | 0.0000 | 0.2105 | 0.3948 |

小幅だが両モデルで一貫して改善。改善幅がneighbor特徴ほど大きくないため、これは**パイプラインへの恒久組み込みは見送り、検証済みレシピとして記録**するに留める（理由: 6.22/7.12を結合したデータセットは単一の`root_run_dir`を持たないため、train/eval分割後にのみ適用するこの処理を`build-wheelchair-dataset`の標準フローに組み込むには、trainスクリプト側でrun_idごとのroot解決とラベルリーク防止の作り込みが追加で必要になり、現時点の改善幅（macro f1 +0.002〜+0.01）に見合わない）。

### 改善の積み上げまとめ（SVM, 同一2-run eval split）

| 段階 | accuracy | dansa recall | dekobo recall | macro f1 |
|---|---:|---:|---:|---:|
| 従来（4特徴量） | 0.7129 | 0.0789 | 0.4526 | 0.4425 |
| + A-1+A-3（拡張特徴量） | 0.7624 | 0.1316 | 0.4316 | 0.4745 |
| + neighbor特徴 | 0.7751 | 0.1053 | 0.5789 | 0.4991 |
| **+ 境界window除外（現時点のベスト）** | **0.7767** | 0.1053 | **0.5895** | **0.5014** |

macro f1は0.4425→0.5014まで一貫して改善（+0.059）。dansaを潰さずにdekobo recallを+13pt積み上げられた。RFは終始flat寄りの傾向が変わらず、改善の恩恵はSVMほど大きくない。

### 次にやるべきこと（更新）

1. **境界window除外の恒久組み込み**（優先度: 中）。combined datasetでのrun_id→root解決を`train_wheelchair_model.py`側に持たせるか、`build-wheelchair-dataset`にrun_idごとの複数root対応を入れるかの設計判断が必要。
2. A-4（dansa向け形状特徴）: neighbor特徴でdekoboは伸びたがdansaはほぼ変化なし。dansa専用の特徴量（符号付き最大変化・歪度）が引き続き必要。
3. A-6（leave-one-run-out CV）: 2-run evalでの数値は依然としてブレやすい。安定した評価基盤の構築を優先すべき。
4. smooth_v2は「dekobo検出を最優先したい」という明確な運用要求が出た場合にのみ適用する、という判断基準をチームで共有しておく。

## 根本原因の切り分け（2026-07-12, 混同行列による診断）

「結局いちばんのボトルネックは何か」を数値で確認するため、現状ベスト（neighbor特徴+境界window除外, SVM）の混同行列を直接計算した。

### 分類器の構成（確認結果）

**現在は1段階のままの3クラス分類器**。`src/models.py`の`build_model()`は`SVC`または`RandomForestClassifier`を1つ作り、flat/dansa/dekoboを一発で分類しているだけで、A-5（flat vs イベント→dansa vs dekobo の2段階）は未実装。`smooth_v2`は1段階分類器の生予測を後から継続時間ルールで塗り替える後処理であり、学習された2段目ではない。

### 混同行列（true dansa 38件の内訳）

```
             pred_flat  pred_dansa  pred_dekobo
true_dansa          11           4          23   ← 61%がdekoboに誤判定
```

**dansaの問題は「静かすぎて見逃される」ではなく、大半（61%）がdekoboと誤判定されていること**。特徴量を比較すると、train平均で dansa z_std=8.10 / dekobo z_std=9.75、dansa neighbor_mean=7.79 / dekobo neighbor_mean=9.54 と、振幅ベースの特徴量では両者がかなり近い。両者を確実に分ける物理特性は**継続時間**（dansa≒2秒の単発、dekobo≒5〜8秒の持続）だが、**現在の特徴量セットに時間・経過情報が一切なく**、各窓は独立に1秒波形だけを見て判定しているため、モデルの目には短い衝撃の一部も長い振動の一部も同じに見えている。

### 伸び代の定量比較

現状（macro f1 = 0.5014）の内訳: flat_f1=0.889 / dekobo_f1=0.498 / dansa_f1=0.118。

- dansa_f1をdekobo_f1と同水準（0.498）まで改善 → macro f1は **0.5014 → 0.628**（+0.127）
- dekobo_f1をさらに0.70まで頑張って上げる → macro f1は 0.569止まり（+0.068）

**残りの伸び代はdekoboよりdansa側の方が圧倒的に大きい**、というのが今回の結論。

## 本日のまとめ（2026-07-12時点）

- **実装済み**: A-1（時間文脈特徴）、A-3（XY・速度特徴）、neighbor特徴（`z_std_neighbor_mean/max`）。いずれも`feature.extended: true`で有効。テスト14件追加、全21件パス。
- **検証済み・未組み込み**: smooth_v2（dekobo特化運用向けのオプションとして温存）、境界window除外（レシピとして記録、恒久組み込みは見送り）。
- **現状ベスト数値**（SVM, 6.22+7.12結合・71kg除外・2-run eval）: accuracy 0.7767 / dansa recall 0.1053 / dekobo recall 0.5895 / macro f1 0.5014（従来4特徴量ベースラインのmacro f1 0.4425から+0.059）。
- **根本原因**: 分類器は1段階のままで、dansaの誤りの61%はdekoboとの混同（flat見逃しではない）。原因は特徴量に継続時間・経過時間の情報が無いこと。macro f1の伸び代はdekoboよりdansa側が圧倒的に大きい。
- **次回着手すべき最優先事項**: A-4（dansa向け形状特徴: 符号付き最大変化・窓内最小値・歪度）またはA-5（2段階分類器の正式実装：セグメント化してから継続時間特徴で判定）。どちらも「継続時間・時間構造をモデルに教える」という同じ根本原因に対する対策であり、次回はここから着手するのが筋が良い。
