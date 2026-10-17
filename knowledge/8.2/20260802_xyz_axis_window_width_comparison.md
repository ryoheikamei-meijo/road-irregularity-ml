# x/y/z軸別の窓幅比較分析（flat・step・roughの軸別識別力）

## 1. 背景・目的

`data/analysis/20260722_window_width`（窓幅1s/2s/3s比較）はこれまでz軸（鉛直方向、`world_z_linear`）の特徴量のみで分布図・AUCを確認していた。世界座標系データには`accWorldX`・`accWorldY`（水平方向）も既に含まれているため、同じ窓幅比較をx・y軸にも拡張し、どの軸がどのクラス識別に効いているかを確認した。

検証した問い:

1. `flat vs step`、`flat vs rough`、`step vs rough` のそれぞれで、x/y/z軸のどれが最も識別力が高いか。
2. 窓幅（1s/2s/3s）を広げたとき、軸ごとの識別力はどう変化するか。
3. 既存のSVM学習パイプライン（z軸4特徴量のみ）を見直す根拠になるか。

## 2. 実装した変更

CV評価（学習パイプライン）は変更せず、可視化・記述統計側だけをx/y/z全軸に拡張した。

- `src/wheelchair_pipeline.py`
  - `load_world_dataframe`が`accWorldX`/`accWorldY`存在時に`world_x_linear`/`world_y_linear`を追加（水平方向のため重力補正は行わない）。
  - `compute_window_features`（z軸専用、既存の学習パイプラインが使用）は後方互換のまま維持し、内部実装を汎用の`compute_axis_window_features(values, prefix=...)`に委譲するようリファクタ。
  - 新規関数`build_multi_axis_run_feature_dataframe` / `build_multi_axis_dataset_dataframe`を追加し、x/y/z全軸の特徴量（各軸4つ: `_std`, `_range`, `_rms`, `_diff_max`、計12列）を持つデータフレームを作れるようにした。
  - 既存の`build_dataset_dataframe`・`DATASET_COLUMNS`・`compute_window_features`のシグネチャ/出力は不変（学習パイプライン・既存テストへの影響なし）。
- `src/analysis/flat_event.py`
  - `build_analysis_dataframe`が`build_multi_axis_dataset_dataframe`を呼ぶよう変更し、x/y/z全軸の特徴量を持つデータフレームを構築。
  - 分布図（`plot_feature_distributions` / `plot_three_class_feature_distributions`）と代表波形図（`plot_representative_waveforms`）が軸を指定できるようになり、`main()`でx/y/zの3軸分をループして出力。
  - z軸の出力ファイル名は既存の知識ドキュメントとの互換のため維持（`feature_distributions.png`等）、x/y軸は`_x`/`_y`サフィックスを付与（`feature_distributions_x.png`等）。
  - 代表window選定基準（`z_std`の25/50/75パーセンタイル、`choose_representatives`）は軸を変えても固定し、波形の表示のみ多軸化した。
  - `build_pairwise_group_cv_summary` / `build_multiclass_group_cv`（SVM・ロジスティック回帰のCV評価）は`Z_FEATURE_COLUMNS`（z軸4特徴量）に固定し、既存の分類性能評価は変更していない。

再実行後、既存テスト（`pytest tests/`、14件）は全て通過し、z軸のCV評価結果（`pairwise_group_cv_summary.csv`、`multiclass_group_cv_summary.csv`）も再実行前後で変化がないことを確認した。

## 3. データ・条件

[20260721_flat_event_analysis_report.md](../7.21/20260721_flat_event_analysis_report.md)と同じ22走行（6.22の11走行 + 7.12の51kg・有効11走行）。窓幅のみ1.0秒・2.0秒・3.0秒（ストライド0.25秒固定）で比較した。

| window_seconds | 総窓数 | flat | step(dansa) | rough(dekobo) |
| --- | ---: | ---: | ---: | ---: |
| 1.0 | 4,617 | 4,102 | 93 | 422 |
| 2.0 | 4,529 | 4,021 | 92 | 416 |
| 3.0 | 4,441 | 3,948 | 89 | 404 |

## 4. 結果

### 4.1 flat vs step（段差検出）: x/y軸がz軸より強い

各軸内で最良の特徴量AUC（`event`側/第2クラス側を高値としたAUC）を比較した。

| 窓幅 | x軸最良 | y軸最良 | z軸最良 |
| --- | --- | --- | --- |
| 1s | `x_rms` 0.770 | `y_rms` **0.814** | `z_rms` 0.694 |
| 2s | `x_range` 0.863 | `y_std` 0.847 | `z_range` 0.738 |
| 3s | `x_range` **0.915** | `y_std` 0.848 | `z_range` 0.786 |

窓幅を広げるほどx/y軸の識別力が伸びる一方（3sで`x_range`=0.915まで上昇）、z軸は同条件でも0.786止まりである。段差を乗り越える瞬間は、鉛直方向よりも前後・左右方向（水平面）の急な加速度変化の方が強く出ている。z軸のみを使う現行パイプラインは、`step`（dansa）検出に関してx/y軸を使えば伸びる余地がある。

### 4.2 flat vs rough（凹凸検出）: 軸間の差は小さいが、窓幅を広げるとz軸がやや優位に

| 窓幅 | x軸最良 | y軸最良 | z軸最良 |
| --- | --- | --- | --- |
| 1s | `x_rms` 0.801 | `y_rms` 0.805 | `z_rms` **0.810** |
| 2s | `x_rms` 0.855 | `y_rms` 0.855 | `z_rms` **0.870** |
| 3s | `x_rms` 0.877 | `y_rms` 0.874 | `z_rms` **0.893** |

1秒窓ではx/y/zがほぼ横並びだが、窓幅を広げるとz軸（`z_rms`）が最も伸びる。`rough`は元々z軸中心に捉えられていたが、x/yも同程度に有効であり、z軸だけに頼る必要は必ずしもない。

### 4.3 step vs rough（段差と凹凸の判別）: z軸だけが有効、x/yはほぼ無意味

| 窓幅 | x軸最良 | y軸最良 | z軸最良 |
| --- | --- | --- | --- |
| 1s | 0.494 | 0.511 | `z_rms` **0.640** |
| 2s | 0.443 | 0.460 | `z_rms` **0.664** |
| 3s | 0.423 | 0.447 | `z_rms` **0.657** |

x/y軸はどの窓幅でもほぼ0.4〜0.5（ランダム予想と同程度、むしろ0.5を下回る場合すらある）で、判別にほぼ寄与しない。`step`と`rough`を分けているのは実質z軸（特に`z_rms`）のみである。3クラス分類でstep（dansa）のF1が低い傾向は既知の課題だが（[20260722_wheelchair_world_z_svm_training_report.md](../7.22/20260722_wheelchair_world_z_svm_training_report.md)、[20260722_window_3s_holdout_experiments.md](../7.22/20260722_window_3s_holdout_experiments.md)）、x/y軸を追加してもこの境界は改善しない可能性が高く、z軸側の特徴量設計（波形形状・時間文脈など）を工夫する方が筋が良い。

### 4.4 flat vs event（step+rough合算）でもx/y軸がz軸と同等以上

既存分析（7/21レポート）はz軸のみでAUC最大0.789（`z_rms`、1秒窓）としていたが、x/y軸を含めると同等かそれ以上のAUCが確認できた。

| 窓幅 | 最良特徴量（全軸） | AUC |
| --- | --- | ---: |
| 1s | `y_rms` | 0.807 |
| 2s | `x_rms` | 0.853（`z_rms`は0.844） |
| 3s | `x_rms` | 0.879（`z_rms`は0.870） |

`event`の大半（約82%）は`rough`が占めるため、この結果は主に`flat vs rough`の傾向を反映しているが、x/y軸がz軸と同等以上の情報を持つことが改めて確認できた。

### 4.5 3クラス中央値で見るとstepとroughの軸ごとの序列が逆転する

`class_feature_summary.csv`（1秒窓）を見ると、x/y軸では`step`の中央値が`rough`と同等かそれ以上になる場合がある。

| 特徴量 | flat中央値 | step中央値 | rough中央値 |
| --- | ---: | ---: | ---: |
| `x_std` | 2.33 | 4.74 | 4.73（ほぼ同値） |
| `y_std` | 2.02 | **5.32** | 4.60（stepの方が高い） |
| `z_std` | 4.58 | 6.70 | **9.67**（roughの方が高い） |

z軸では一貫して`flat < step < rough`（振幅は継続的な凹凸ほど大きい）だが、x/y軸では`step`の水平方向の振幅が`rough`と同等かそれを上回ることがある。段差通過時は水平方向に短時間の強い衝撃が生じ、持続的な凹凸走行より水平振幅が大きくなり得るという解釈と整合する。この非対称性が、4.3節で「x/yがstep/rough判別に効かない」理由（両クラスの水平振幅が近く、分布が重なる）の裏付けになっている。

## 5. まとめ・解釈

- **flat/step判別はx/y軸を追加すべき**: 現行のz軸4特徴量のみでは`step`（dansa）の情報を大きく失っている。
- **flat/rough判別はz軸のままでほぼ十分**: x/yを足しても大差はなく、窓幅を広げるとz軸がむしろ優位になる。
- **step/rough判別はz軸一択**: x/yはほぼ無効。この境界の難しさは軸を増やしても解決しない。
- x/y軸では`step`と`rough`の水平振幅が近い値になり、これが「z軸のみがstep/rough判別に効く」ことの一因と考えられる。

## 6. 次に検討すること

1. 3クラスSVM（`build_multiclass_group_cv`）にx/y軸の特徴量（特に`x_rms`, `x_range`, `y_std`, `y_rms`）を追加した条件で走行単位CVを再評価し、`step`（dansa）のF1・recallが実際に改善するか確認する。z軸のみ・z軸+x/y軸の2条件を同一のholdout・CV分割で比較する。
2. `step vs rough`の分離はz軸側の特徴量拡充（時間文脈、波形形状特徴など）を優先する。x/y軸の追加はこの境界の改善には直接寄与しない見込み。
3. 今回はいずれも単一特徴量AUC（記述統計）の比較であり、多変量モデルでの寄与とは異なる可能性がある。上記1の多変量CV評価で最終確認する。

## 7. 再現方法・関連ファイル

分析スクリプト:

- `src/analysis/flat_event.py`（分析本体、x/y/z全軸対応）
- `src/scripts/analyze_flat_event.py`（CLI入口）
- `src/wheelchair_pipeline.py`（`build_multi_axis_dataset_dataframe`等、多軸対応の追加関数）

実行コマンド（各窓幅ごと）:

```bash
python -m src.scripts.analyze_flat_event --output-dir data/analysis/20260722_window_width/window_1s --window-seconds 1.0
python -m src.scripts.analyze_flat_event --output-dir data/analysis/20260722_window_width/window_2s --window-seconds 2.0
python -m src.scripts.analyze_flat_event --output-dir data/analysis/20260722_window_width/window_3s --window-seconds 3.0
```

主要な数値結果（`window_1s` / `window_2s` / `window_3s` 共通の相対パス、`data/analysis/20260722_window_width/<window>/tables/`配下）:

- `pairwise_feature_auc.csv`（クラス対ごと・軸ごとの単一特徴量AUC、4節の主データ）
- `feature_summary.csv`（flat vs event、全12特徴量）
- `class_feature_summary.csv`（3クラス中央値・IQR、`auc_rough_high_vs_step`）
- `analysis_metadata.csv`（窓数・ラベル内訳）

画像（各`window_1s`/`window_2s`/`window_3s`の`figures/`配下、z軸は既存ファイル名を維持、x/yは`_x`/`_y`サフィックス）:

- `feature_distributions.png` / `feature_distributions_x.png` / `feature_distributions_y.png`
- `three_class_feature_distributions.png` / `three_class_feature_distributions_x.png` / `three_class_feature_distributions_y.png`
- `representative_waveforms.png` / `representative_waveforms_x.png` / `representative_waveforms_y.png`

例（1秒窓、絶対パス）:

- `/Users/kameiryouhei/code/research/road-irregularity-ml/data/analysis/20260722_window_width/window_1s/figures/three_class_feature_distributions_x.png`
- `/Users/kameiryouhei/code/research/road-irregularity-ml/data/analysis/20260722_window_width/window_1s/figures/three_class_feature_distributions_y.png`
