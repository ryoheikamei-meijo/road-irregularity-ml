<script type="text/javascript" async src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.min.js">
</script>
<script type="text/x-mathjax-config">
 MathJax.Hub.Config({
 tex2jax: {
 inlineMath: [['$', '$'] ],
 displayMath: [ ['$$','$$'], ["\\[","\\]"] ]
 }
 });
</script>

# 2026-05-13 Phase 1 Baseline Pipeline Summary

## 対象

- モックデータ生成
- スライディングウィンドウ特徴量抽出
- 別 run を使った学習・評価

## 実装概要

- `generate-mock-data`
  - `--seed` を追加
  - 出力先を `data/raw/YYYYMMDDHHMMSS_seedN/` に変更
- `extract-features`
  - 2.0秒窓，1.0秒ストライドで特徴量化
  - 出力先を `data/features/YYYYMMDDHHMMSS_seedN/` に変更
  - 出力ファイル名を `mock_acc_only_features_seedN.csv` に変更
  - window ラベルは `1 > 2 > 0` の優先ルール
- `train-dummy`
  - ダミーデータ入力を廃止
  - `--train-input` と複数の `--eval-input` を受ける学習 CLI に変更
  - 別 run の特徴量 CSV を使って評価可能に変更
  - 評価結果を `data/processed/YYYYMMDDHHMMSS/` に保存

## ロジック説明

### 1. モックデータ生成ロジック

- 目的
  - 実データ収集前に，学習評価パイプライン全体を通すための疑似センサ時系列を作る
- 入力条件
  - サンプリング間隔: `0.25s`
  - 総時間: `240s`
  - 総サンプル数: `240 / 0.25 = 960`
  - ラベル: `0=平坦`, `1=段差`, `2=粗さ`
- seed の役割
  - `np.random.default_rng(seed)` を使って乱数系列を初期化する
  - 同じ seed なら同じラベル遷移，同じ継続長，同じノイズが再現される
  - 異なる seed なら，同じルールに従う別 run が生成される

#### ラベル列の生成

- ラベルはサンプルごとに独立に振るのではなく，区間単位で生成する
- 各ラベルの重み
  - `0`: `0.55`
  - `1`: `0.15`
  - `2`: `0.30`
- 各ラベルの継続時間レンジ
  - `0=平坦`: `5.0s - 20.0s`
  - `1=段差`: `0.25s - 1.0s`
  - `2=粗さ`: `3.0s - 10.0s`
- 生成手順
  1. 次に出すラベルを重み付き乱数で選ぶ
  2. そのラベルの継続時間をレンジ内で乱数サンプリングする
  3. 残りサンプル数がなくなるまで繰り返す
- 同じラベルが連続しすぎないように，直前ラベルの確率を一時的に `0.35` 倍にしている

#### 波形の作り方

時間軸 $t$（単位: 秒）に対してサンプリング間隔 $\Delta t = 0.25\,\mathrm{s}$ で離散化した配列を作り，ラベルごとに以下の式で加速度 3 軸を生成する。
最後にすべての軸へガウスノイズ $\varepsilon \sim \mathcal{N}(0,\, 0.03^2)$ を加算する。

---

##### label=0（平坦）

加速度の式：

$$
\begin{aligned}
a_x &= 0.03 \sin(2\pi \cdot 0.35\, t) \\
a_y &= 0.02 \sin(2\pi \cdot 0.20\, t + 0.4) \\
a_z &= 1.00 + 0.04 \sin(2\pi \cdot 0.45\, t + 0.8)
\end{aligned}
$$

| 軸  | 振幅 [g]          | 周波数 [Hz] | 意図                             |
| --- | ----------------- | ----------- | -------------------------------- |
| X   | 0.03              | 0.35        | 左右の微細な揺れ                 |
| Y   | 0.02              | 0.20        | 前後の微細な揺れ                 |
| Z   | ±0.04 (中心 1.00) | 0.45        | 重力 1g を中心に±4% の上下微振動 |

- 振幅が非常に小さく（X/Y は $\pm 0.03\,\mathrm{g}$ 以下），周波数も 0.5 Hz 未満に抑えている
- Z 軸は $1.0\,\mathrm{g}$（重力加速度）を中心に微振動する形にすることで「水平面を走行中」を表現している
- 大きな衝撃・高周波成分は含まない

---

##### label=1（段差）

加速度の式（$t_c$ はセグメント中央の時刻）：

$$
\text{spike}(t) = \exp\!\left(-\frac{(t - t_c)^2}{0.01}\right)
$$

$$
\text{rebound}(t) = \exp\!\left(-\frac{(t - (t_c + 0.25))^2}{0.03}\right)
$$

$$
\begin{aligned}
a_x &= 0.10 \sin(2\pi \cdot 0.60\, t) + 0.90\,\text{spike}(t) \\
a_y &= 0.08 \sin(2\pi \cdot 0.50\, t + 0.3) - 0.35\,\text{rebound}(t) \\
a_z &= 1.00 + 1.40\,\text{spike}(t) - 0.45\,\text{rebound}(t)
\end{aligned}
$$

- $\text{spike}$：ガウス関数で形作った瞬間的な衝撃。Z 軸に最大 $+1.40\,\mathrm{g}$ の跳ね上がりを生む
  - 分散 $0.01$ → 標準偏差 $\approx 0.1\,\mathrm{s}$ の鋭いパルス
- $\text{rebound}$：衝撃から $0.25\,\mathrm{s}$ 後に現れる「揺れ返し」。Z 軸に $-0.45\,\mathrm{g}$，Y 軸にも負方向の変動を加える
  - 分散 $0.03$ → 標準偏差 $\approx 0.17\,\mathrm{s}$ でやや広がったパルス
- Z 軸の最大振幅は平坦の約 35 倍（$0.04\,\mathrm{g} \to 1.40\,\mathrm{g}$）

---

##### label=2（粗さ）

加速度の式：

$$
\begin{aligned}
a_x &= 0.18 \sin(2\pi \cdot 2.40\, t) + 0.09 \sin(2\pi \cdot 4.80\, t + 0.2) \\
a_y &= 0.16 \sin(2\pi \cdot 2.10\, t + 0.7) + 0.08 \sin(2\pi \cdot 5.10\, t) \\
a_z &= 1.00 + 0.22 \sin(2\pi \cdot 2.80\, t + 0.5) + 0.10 \sin(2\pi \cdot 6.00\, t)
\end{aligned}
$$

| 成分     | 振幅 [g] | 周波数 [Hz] |
| -------- | -------- | ----------- |
| X 基本波 | 0.18     | 2.40        |
| X 倍音   | 0.09     | 4.80        |
| Y 基本波 | 0.16     | 2.10        |
| Y 倍音   | 0.08     | 5.10        |
| Z 基本波 | 0.22     | 2.80        |
| Z 倍音   | 0.10     | 6.00        |

- 2〜6 Hz 帯の高周波成分を複数重ねて「細かく連続する振動」を表現している
- 振幅は平坦の約 5〜6 倍（X 軸: $0.03\,\mathrm{g} \to 0.18\,\mathrm{g}$，Z 軸: $0.04\,\mathrm{g} \to 0.22\,\mathrm{g}$）
- 単一周波数ではなく 2 成分の重ね合わせにすることで，アスファルトのランダムな凸凹感に近づけている

---

##### 3 ラベルの比較まとめ

| ラベル | Z 振幅 [g]    | 主周波数 [Hz] | 波形の特徴                                 |
| ------ | ------------- | ------------- | ------------------------------------------ |
| 0 平坦 | ±0.04         | 0.45          | 小振幅・低周波の正弦波                     |
| 1 段差 | +1.40 / −0.45 | —             | ガウス型スパイク＋揺れ返し（瞬間イベント） |
| 2 粗さ | ±0.22 + ±0.10 | 2.8 + 6.0     | 高振幅・高周波の複合正弦波（連続振動）     |

---

##### ノイズの付加

すべてのラベルに共通して，最後に全 3 軸へ独立にガウスノイズを加える：

$$
\varepsilon \sim \mathcal{N}(0,\, \sigma^2), \quad \sigma = 0.03\,[\mathrm{g}]
$$

- 同じ seed なら同一ノイズ系列が再現される
- seed が異なれば，同じ波形モデルでも毎回異なるノイズが乗る

### 2. スライディングウィンドウの切り方

- 目的
  - 生の時系列をそのまま分類器に入れず，固定長の特徴量ベクトルへ変換する
- 設定
  - `window_seconds = 2.0`
  - `stride_seconds = 1.0`
  - `sampling_interval_seconds = 0.25`
- サンプル数換算
  - 1 window の長さ: `2.0 / 0.25 = 8 samples`
  - stride: `1.0 / 0.25 = 4 samples`
- 生成される window
  - 先頭から `8` サンプルを 1 window とする
  - 次は `4` サンプル進めて，重なりありで次の window を作る
  - この処理を末尾まで繰り返す
  - 不完全な末尾 window は捨てる

#### 具体例

- window 0
  - サンプル index `0-7`
  - `elapsed_ms = 0 - 1750`
- window 1
  - サンプル index `4-11`
  - `elapsed_ms = 1000 - 2750`
- つまり 50% オーバーラップで window を切っている

### 3. 特徴量計算

- 対象列
  - `acc_x`, `acc_y`, `acc_z`
- 各 window で各軸に対して以下を計算する
  - `mean`: 算術平均
  - `rms`: Root Mean Square
    - `sqrt(mean(x^2))`
  - `var`: 分散
    - 実装では `np.var(...)`
  - `max`: 最大値
  - `min`: 最小値
- 1 window あたりの特徴量次元
  - 3軸 × 5特徴量 = `15`
- 追加で持つメタ情報
  - `window_id`
  - `window_start_ms`
  - `window_end_ms`
  - `n_samples`
  - `label`

### 4. window ラベル付け

- 単純多数決ではなく，`1 > 2 > 0` の優先ルールを採用した
- 理由
  - `1=段差` は短い瞬間イベントなので，多数決だと平坦や粗さに埋もれやすい
- ルール
  - window 内に `1` が1つでもあれば `label=1`
  - `1` がなく `2` が1つでもあれば `label=2`
  - それ以外は `label=0`

### 5. 学習・評価ロジック

- 学習入力
  - `--train-input` に指定した特徴量 CSV
- 評価入力
  - `--eval-input` に指定した1本以上の特徴量 CSV
- 説明変数
  - `label` を除外
  - `window_id`, `window_start_ms`, `window_end_ms`, `n_samples` も除外
  - 実際に学習に入るのは 15次元特徴量
- 目的変数
  - `label`
- モデル
  - SVM
  - Random Forest
- 評価方法
  - `seed43` を train run として学習
  - `seed42` と `seed45` を unseen run として評価
  - 同一 CSV のランダム分割ではなく，別 run 評価にしたことで，より厳しい検証に寄せている

### 6. 出力される評価指標

- classification report
  - precision
  - recall
  - f1-score
  - support
- confusion matrix
  - 行: 正解ラベル
  - 列: 予測ラベル
- 今回は特に `1=段差` の recall を重視している

## 生成した run

### Raw CSV

- train 用
  - `data/raw/20260513152209_seed43/mock_acc_only.csv`
- eval 用
  - `data/raw/20260513152216_seed42/mock_acc_only.csv`
  - `data/raw/20260513152641_seed45/mock_acc_only.csv`

### Raw CSV Details

- `seed43`
  - output: `data/raw/20260513152209_seed43/mock_acc_only.csv`
  - rows: `960`
  - gyro included: `False`
  - label counts
    - `0`: `684`
    - `1`: `18`
    - `2`: `258`
  - label runs: `32`
- `seed42`
  - output: `data/raw/20260513152216_seed42/mock_acc_only.csv`
  - rows: `960`
  - gyro included: `False`
  - label counts
    - `0`: `656`
    - `1`: `26`
    - `2`: `278`
  - label runs: `29`
- `seed45`
  - output: `data/raw/20260513152641_seed45/mock_acc_only.csv`
  - rows: `960`
  - gyro included: `False`
  - label counts
    - `0`: `628`
    - `1`: `15`
    - `2`: `317`
  - label runs: `22`

### Feature CSV

- train 用
  - `data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv`
- eval 用
  - `data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv`
  - `data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv`

## 特徴量仕様

- 対象軸
  - `acc_x`
  - `acc_y`
  - `acc_z`
- 各軸で算出する特徴量
  - `mean`
  - `rms`
  - `var`
  - `max`
  - `min`
- メタ列
  - `window_id`
  - `window_start_ms`
  - `window_end_ms`
  - `n_samples`
  - `label`

## 学習・評価条件

- 学習元
  - `seed43` の特徴量 CSV
- 評価先
  - `seed42` の特徴量 CSV
  - `seed45` の特徴量 CSV
- モデル
  - SVM
  - Random Forest
- ラベル体系
  - multiclass (`0=平坦`, `1=段差`, `2=粗さ`)

## 実行コマンド

### Raw 生成

```bash
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 43
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 42
uv run generate-mock-data --config configs/mock_data_acc_only.yaml --seed 45
```

### Feature 抽出

```bash
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152209_seed43/mock_acc_only.csv
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152216_seed42/mock_acc_only.csv
uv run extract-features --config configs/mock_data_acc_only.yaml --input data/raw/20260513152641_seed45/mock_acc_only.csv
```

### 学習・評価

```bash
uv run train-dummy --config configs/svm.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv

uv run train-dummy --config configs/random_forest.yaml \
  --train-input data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv \
  --eval-input data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv \
  --eval-input data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv
```

## 評価結果サマリー

### SVM

- eval on `seed42`
  - accuracy: `0.9582`
  - macro avg f1: `0.9394`
  - `label=1` recall: `0.8333`
- eval on `seed45`
  - accuracy: `0.9749`
  - macro avg f1: `0.9553`
  - `label=1` recall: `0.8462`

### Random Forest

- eval on `seed42`
  - accuracy: `0.9623`
  - macro avg f1: `0.9431`
  - `label=1` recall: `0.8333`
- eval on `seed45`
  - accuracy: `0.9707`
  - macro avg f1: `0.9522`
  - `label=1` recall: `0.8462`

### Evaluation Output Details

#### SVM

```text
Train feature data: data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv
Eval feature data: data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv
Model: svm
Train samples: 239
Eval samples: 239
Saved evaluation to: data/processed/20260513153954

Classification report:
              precision    recall  f1-score   support

           0     0.9545    1.0000    0.9767       147
           1     1.0000    0.8333    0.9091        24
           2     0.9538    0.9118    0.9323        68

    accuracy                         0.9582       239
   macro avg     0.9695    0.9150    0.9394       239
weighted avg     0.9589    0.9582    0.9573       239
```

```text
Train feature data: data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv
Eval feature data: data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv
Model: svm
Train samples: 239
Eval samples: 239
Saved evaluation to: data/processed/20260513153954

Classification report:
              precision    recall  f1-score   support

           0     0.9730    1.0000    0.9863       144
           1     1.0000    0.8462    0.9167        13
           2     0.9750    0.9512    0.9630        82

    accuracy                         0.9749       239
   macro avg     0.9827    0.9325    0.9553       239
weighted avg     0.9751    0.9749    0.9745       239
```

#### Random Forest

```text
Train feature data: data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv
Eval feature data: data/features/20260513153504_seed42/mock_acc_only_features_seed42.csv
Model: random_forest
Train samples: 239
Eval samples: 239
Saved evaluation to: data/processed/20260513154036

Classification report:
              precision    recall  f1-score   support

           0     0.9608    1.0000    0.9800       147
           1     1.0000    0.8333    0.9091        24
           2     0.9545    0.9265    0.9403        68

    accuracy                         0.9623       239
   macro avg     0.9718    0.9199    0.9431       239
weighted avg     0.9629    0.9623    0.9616       239
```

```text
Train feature data: data/features/20260513153446_seed43/mock_acc_only_features_seed43.csv
Eval feature data: data/features/20260513153504_seed45/mock_acc_only_features_seed45.csv
Model: random_forest
Train samples: 239
Eval samples: 239
Saved evaluation to: data/processed/20260513154036

Classification report:
              precision    recall  f1-score   support

           0     0.9728    0.9931    0.9828       144
           1     1.0000    0.8462    0.9167        13
           2     0.9630    0.9512    0.9571        82

    accuracy                         0.9707       239
   macro avg     0.9786    0.9301    0.9522       239
weighted avg     0.9709    0.9707    0.9704       239
```

## 解釈メモ

- 別 run 評価でも accuracy は `95.8% - 97.5%` と高い
- `0` と `2` は比較的安定している
- 現時点で最も弱いのは `1=段差` の recall
- モックデータ上ではベースラインとして十分機能している
- ただし実データへの一般化は未検証

## 出力先

- SVM の評価結果
  - `data/processed/20260513153954/`
- Random Forest の評価結果
  - `data/processed/20260513154036/`

## 次の候補

- 学習済みモデルの保存
- 実験条件を metadata として保存
- ジャイロあり条件で同じ流れを実行
- 実データでの評価に向けた分割方針の整理
