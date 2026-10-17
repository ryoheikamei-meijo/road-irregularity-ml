# 2026-07-22 Wheelchair World Z SVM 学習・評価結果

## 概要

`wheelchair_data/6.22` と `wheelchair_data/7.12` の世界座標系加速度データを用いて、`flat` / `dansa` / `dekobo` の3クラス分類を行った。

- モデル: RBF SVM
- 学習サンプル: 3,990 windows（20 run）
- 評価サンプル: 627 windows（2 run）
- 総サンプル: 4,617 windows（22 run）

## 入力データ

世界座標へ変換済みの各runの `acc_world.csv` を入力とした。

- 6.22: `wheelchair_data/6.22/analysis/world_csv/*/acc_world.csv`（11 run）
- 7.12: `wheelchair_data/7.12/analysis/world_csv/*/acc_world.csv` のうち、成功かつ51kgの11 run

  7.12では71kgのrunと、イベント終了ラベルが欠ける失敗runを対象外とした。

生成した結合データセットは以下。

- [wheelchair_world_z_dataset_combined_51kg_z4.csv](../../../data/features/20260722134930/wheelchair_world_z_dataset_combined_51kg_z4.csv)

クラス別のwindow数は、`flat` 4,102、`dansa` 93、`dekobo` 422である。

## 特徴量とラベル

1.0秒のwindowを0.25秒ずつ移動して切り出した。重力を除いたWorld Z軸加速度（`world_z_linear`）から、以下の4特徴量を計算した。

- `z_range`
- `z_diff_max`
- `z_rms`
- `z_std`

イベントラベルは `dansa.csv` / `dekobo.csv` の区間との重なりがwindowの50%以上の場合に付与した。イベント開始時刻は0.5秒前倒しした。

## 学習・評価分割

評価用runは、`dansa` と `dekobo` の双方を含む以下の2 runとした。

| eval run         | flat | dansa | dekobo | windows |
| ---------------- | ---: | ----: | -----: | ------: |
| `20260622180835` |  332 |    27 |     27 |     386 |
| `20260622182112` |  162 |    11 |     68 |     241 |
| 合計             |  494 |    38 |     95 |     627 |

残り20 runを学習に使用した。正確なrun一覧は以下に保存している。

- [run_split.txt](../../../data/processed/20260722134933/run_split.txt)

## モデル設定

`StandardScaler` で標準化した後、以下のSVMを学習した。

- kernel: RBF
- `C`: 1.0
- `gamma`: `scale`
- `class_weight`: `balanced`

## 評価結果

### 全評価runの合算結果

z
| class | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| flat | 0.8717 | 0.8117 | 0.8407 | 494 |
| dansa | 0.0500 | 0.0789 | 0.0612 | 38 |
| dekobo | 0.4019 | 0.4526 | 0.4257 | 95 |
| macro average | 0.4412 | 0.4478 | 0.4425 | 627 |

- accuracy: **0.7129**
- macro F1: **0.4425**
- weighted F1: 0.7306

### run別 accuracy / macro F1

| eval run         | accuracy | macro F1 |
| ---------------- | -------: | -------: |
| `20260622180835` |   0.8135 |   0.4801 |
| `20260622182112` |   0.5519 |   0.3826 |

## 出力ファイル

- 全評価の分類レポート: [classification_report_svm_all_eval.txt](../../../data/processed/20260722134933/classification_report_svm_all_eval.txt)
- 全評価の混同行列: [confusion_matrix_svm_all_eval.csv](../../../data/processed/20260722134933/confusion_matrix_svm_all_eval.csv)
- run `20260622180835` の分類レポート: [classification_report_svm_20260622180835.txt](../../../data/processed/20260722134933/classification_report_svm_20260622180835.txt)
- run `20260622182112` の分類レポート: [classification_report_svm_20260622182112.txt](../../../data/processed/20260722134933/classification_report_svm_20260622182112.txt)

## 実装・設定のソース

今回のデータセット生成、学習、評価に使ったソースと設定は以下。

- データセット生成CLI: [build_wheelchair_dataset.py](../../../src/legacy/scripts/build_wheelchair_dataset.py)
- 前処理・特徴量計算・ラベル付与: [wheelchair_pipeline.py](../../../src/legacy/wheelchair_pipeline.py)
- 学習・評価CLI: [train_wheelchair_model.py](../../../src/legacy/scripts/train_wheelchair_model.py)
- モデル定義: [models.py](../../../src/legacy/models.py)
- SVM設定: [wheelchair_world_z_combined_svm.yaml](../../../configs/legacy/wheelchair_world_z_combined_svm.yaml)

## 窓幅別の特徴量分布比較（1秒・2秒・3秒）

4 HzのWorld Z軸データについて、1秒（4点）、2秒（8点）、3秒（12点）のwindowで同じ4特徴量を算出し、分布と3クラス分離性能を比較した。strideは全条件で0.25秒、イベント開始の0.5秒前倒しと50%重なりによるラベル付与も全条件で共通とした。

### 生成物

| window | 3クラス特徴量分布図                                                                                                                        | 分析表                                                                |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------- |
| 1秒    | [three_class_feature_distributions.png](../../../data/analysis/20260722_window_width/window_1s/figures/three_class_feature_distributions.png) | [tables](../../../data/analysis/20260722_window_width/window_1s/tables) |
| 2秒    | [three_class_feature_distributions.png](../../../data/analysis/20260722_window_width/window_2s/figures/three_class_feature_distributions.png) | [tables](../../../data/analysis/20260722_window_width/window_2s/tables) |
| 3秒    | [three_class_feature_distributions.png](../../../data/analysis/20260722_window_width/window_3s/figures/three_class_feature_distributions.png) | [tables](../../../data/analysis/20260722_window_width/window_3s/tables) |

### サンプル数と3クラスrun単位CV

全22 runを対象に、同一runが学習・評価の両方へ入らない5分割の`StratifiedGroupKFold`でRBF SVMを評価した。

| window | windows |  flat | dansa | dekobo | balanced accuracy |  macro F1 |
| ------ | ------: | ----: | ----: | -----: | ----------------: | --------: |
| 1秒    |   4,617 | 4,102 |    93 |    422 |             0.431 |     0.389 |
| 2秒    |   4,529 | 4,021 |    92 |    416 |             0.511 |     0.429 |
| 3秒    |   4,441 | 3,948 |    89 |    404 |         **0.571** | **0.451** |

窓幅が長くなるにつれて、3クラス分類のbalanced accuracyは0.431→0.571、macro F1は0.389→0.451へ一貫して上昇した。

### 分布の観察

- `flat` と `rough` は全条件で分離傾向があり、3秒では単一特徴量のAUCが`z_rms` 0.893、`z_std` 0.884まで上昇した。
- `flat` と `step` も、3秒では`z_range` 0.786、`z_std` 0.775となり、1秒条件（おおむね0.64〜0.69）より改善した。
- `step` と `rough` の分離は依然として弱く、最も高い単一特徴量AUCでも2秒の`z_rms` 0.664である。3秒にしてもこの2クラスの重なりは残る。
- 箱ひげ図でも、窓幅を広げるにつれて各特徴量の中央値は上昇しつつ、`flat` → `step` → `rough` の順序がより明瞭になった。

### 解釈上の注意

窓幅を広げると、同じ50%重なり条件を満たすために必要なイベント継続時間も長くなる。そのため、event window数は1秒の515件から3秒の493件へ少し減少している。また`range`や最大差分の絶対値は、より長い区間から最大値を取ること自体でも増える。したがって、絶対値の大小ではなく、run分離CV・AUC・クラス間の分布重なりを主な比較指標とする。

### 窓幅比較に使った実装

- 分析CLI: [analyze_flat_event.py](../../../src/legacy/scripts/analyze_flat_event.py)
- 窓幅の反映、分布図、3クラスrun単位CV: [flat_event.py](../../../src/legacy/analysis/flat_event.py)
- window生成とラベル付与: [wheelchair_pipeline.py](../../../src/legacy/wheelchair_pipeline.py)

## 今後のTODO

### 現状の判断

窓幅を1秒から3秒へ広げることで、3クラスrun単位CVのbalanced accuracyは0.431から0.571、macro F1は0.389から0.451へ改善した。一方、3秒窓でもstepはprecision 0.051、recall 0.292、F1 0.087であり、現状の4特徴量だけで安定した3分類ができる状態ではない。

現在の主な課題は以下である。

- 3秒窓のstepは89 windowsあるが、元になる独立イベントは約9件しかない。
- `z_std` / `z_range` / `z_rms` / `z_diff_max` の相関は0.86〜0.99であり、いずれも主に振幅の大きさを表している。
- stepとroughの単一特徴量AUCは最大でも約0.66で、箱ひげ図の分布も大きく重なる。
- イベントに一部重なるものの50%未満のためflatになる境界windowは、1秒の73件（flatの1.8%）から3秒の234件（5.9%）へ増える。
- 4 Hzでは段差の瞬間的な落下・突き上げ波形を十分に観測できていない可能性がある。

### 優先度A: 3秒窓を同一holdout条件で学習・評価する

- [ ] 3秒窓、stride 0.25秒で22 runのデータセットを生成する。
- [ ] 1秒窓の評価と同じ2 run（`20260622180835`, `20260622182112`）をholdoutにする。
- [ ] 残り20 runでSVMを学習し、1秒窓と同じclassification report・混同行列を出力する。
- [ ] accuracyだけでなく、macro F1、balanced accuracy、step precision / recall / F1を比較する。
- [ ] 1秒窓に対して3秒窓が同一holdoutでも改善するかを確認する。

完了条件は、同一データ分割で1秒・2秒・3秒の結果を比較でき、窓幅による改善が分割方法の違いではないと確認できることである。

### 優先度A: 境界windowのラベル汚染を検証する

- [ ] イベントとの重なりが0%超50%未満のwindowを境界windowとして明示的に抽出する。
- [ ] 境界windowを学習データからのみ除外した条件を作る。評価データは実運用条件を保つため除外しない。
- [ ] 50%固定に加えて、中心時刻ベースのラベル付与またはsoft label相当の扱いを比較する。
- [ ] 1秒・2秒・3秒で境界window数と各クラス指標への影響を記録する。

### 優先度A: 二段階分類を検証する

現状のペア分類では、3秒窓でflat vs roughのbalanced accuracyが0.785、flat vs stepが0.654、step vs roughが0.610である。最初から3クラスを同時に判別するより、以下の二段階構成を検証する。

- [ ] 第1段階としてflat vs event（step + rough）の二値分類器を作る。
- [ ] 連続するevent予測windowを1つのイベント候補へまとめる。
- [ ] 第2段階として、イベント継続時間とイベント内特徴量からstep / roughを分類する。
- [ ] window単位だけでなく、イベント単位のprecision / recall / F1を定義して評価する。
- [ ] 単純な継続時間閾値、SVM、ロジスティック回帰を同じrun単位CVで比較する。

### 優先度B: 既存特徴量を整理する

既存4特徴量の全組合せを同じ3秒・run単位CVで試算したところ、4特徴量のmacro F1 0.451に対し、`z_std + z_range + z_diff_max` は0.465だった。

- [ ] `z_rms` を除いた3特徴量を候補とする。
- [ ] 特徴量選択と性能評価を同じfoldで行う過大評価を避けるため、nested group CVまたは固定holdoutで再確認する。
- [ ] 削除後もstep recallだけを上げてprecisionが悪化していないことを確認する。

### 優先度B: step / roughの時間構造を表す特徴量を検証する

正負ピーク、最大絶対差分、jerk RMS、crest factor、上位2点のエネルギー割合、1秒ごとの標準偏差変動、差分符号反転率を予備試算したが、候補9特徴量のみのmacro F1は0.411、既存特徴への追加は0.414であり、採用根拠は得られなかった。これらは現時点ではパイプラインへ追加しない。

次は単純な振幅統計ではなく、段差の瞬発性と凹凸の持続性を直接表す以下を検証する。

- [ ] 3秒窓内でエネルギーが最大となる連続1秒区間のエネルギー比率を計算する。
- [ ] 最大負ピークから最大正ピークまでの時間差と発生順序を計算する。
- [ ] 自己相関（lag 1 / 2）とピーク間隔を計算する。
- [ ] 0.5〜2 Hz帯域パワーとスペクトルエントロピーを試算する。ただし4 Hz・12点で安定するかを先に確認する。
- [ ] 各候補について3クラス箱ひげ図、step vs rough AUC、run単位CVを出す。
- [ ] 単一特徴量AUC、macro F1、step F1のいずれも改善しない特徴量は採用しない。

### 優先度A: stepデータを追加収集する

- [ ] 現在約9件の独立stepイベントを増やし、走行日・走行者・速度を分散させる。
- [ ] 連続window数ではなく独立イベント数を収集目標として管理する。
- [ ] 可能であればサンプリング周波数を10〜20 Hz以上へ引き上げ、段差の瞬間波形を取得する。
- [ ] 4 Hzと高周波数の同一走行データを比較し、ピーク形状・差分・周波数特徴の再現性を確認する。

### 優先度B: 評価方法を安定化する

- [ ] 同一runがtrain / evalへ混入しないgroup splitを全実験で維持する。
- [ ] 2-run holdoutに加えて、leave-one-run-outまたはrepeated group CVを実施する。
- [ ] window単位の件数だけでなく、独立イベント数とイベント単位検出率を必ず併記する。
- [ ] 窓幅、stride、ラベル閾値、対象run、特徴量一覧を結果ディレクトリへ保存し、実験の再現性を確保する。

### 推奨する実施順序

1. 3秒窓を既存と同じ2-run holdoutで再学習し、直接比較する。
2. 境界window除外を同じ条件で比較する。
3. `z_rms` 除外をnested group CVまたはholdoutで確認する。
4. flat vs event → event単位step / roughの二段階分類を実装する。
5. 時間構造の候補特徴量を個別に評価する。
6. 並行してstepイベント追加収集と高サンプリング周波数化を進める。
