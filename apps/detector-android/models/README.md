# 判定モデル

アプリに入れる判定モデルを、版ごとのフォルダで管理する。アプリが使う版は `../gradle.properties` の `roaddetector.modelVersion` で 1 つだけ選び、ビルドのときにそのフォルダの中身がアセットになる。

## 版の一覧

| 版 | 日付 | 特徴量 | モデル | 学習データ | 再現率（flat / step / rough。セッション単位の交差検証） | メモ |
| --- | --- | --- | --- | --- | --- | --- |
| `v1_20261116` | 2026-11-16 | core の 5 個（z_rms・z_kurt・h_std・h_crest・tilt_range）。傾きの基準は 30 秒の指数移動平均（v2 で置き換え） | StandardScaler + SVM（RBF、C=1） | 汎用の車椅子・68〜69 kg の 16 セッション。段差のラベルは衝撃の 0.5 秒前から | 0.958 / 0.976 / 0.917 | [11.16 のメモ](../../../docs/knowledge/2026-11-16/20261116_onnx_edge_inference.md) |
| `v2_20261117` | 2026-11-17 | core の 5 個。傾きの基準は**直近 30 秒の平均**（Mizell 2003 の窓の平均。Hemminki ら 2013）。v3 で置き換え | StandardScaler + SVM（RBF、C=1） | v1 と同じ。ただし計測2-2 の #9・#11（STOP が遅れた凸凹の通過）を除く（`configs/sessions/excluded_passes.csv`） | 0.955 / 0.972 / 0.945（#9・#11 を除いた評価） | [11.16 のメモ](../../../docs/knowledge/2026-11-16/20261116_onnx_edge_inference.md) |
| `v3_20261118` | 2026-11-18 | core の 5 個。傾きの基準は**直近 10 秒の平均**（第19回ゼミで採用。v2 と同じ計算で、平均する長さだけ 30 → 10 秒）。基準がサンプルごとに動く。v4 で置き換え | StandardScaler + SVM（RBF、C=1） | v2 と同じ（#9・#11 を除く） | 0.955 / 0.976 / 0.945（#9・#11 を除いた評価） | [11.16 のメモ](../../../docs/knowledge/2026-11-16/20261116_onnx_edge_inference.md) |
| `v4_20261118` | 2026-11-18 | core の 5 個。傾きの基準は**窓の最初のサンプルの時点の直近 10 秒の平均を、窓の中で固定**（`startmean10`。tilt_range を 1 つの基準から見た幅にするため）。**今アプリで使っている版** | StandardScaler + SVM（RBF、C=1） | v2 と同じ（#9・#11 を除く） | 0.950 / 0.972 / 0.935（#9・#11 を除いた評価） | [11.18 のメモ](../../../docs/knowledge/2026-11-18/20261118_window_fixed_tilt_reference.md) |

## 1 つの版のフォルダの中身

| ファイル | 中身 |
| --- | --- |
| `core_svm.onnx` | モデル。入力 `features` float32 [N, 5]（順番は model_info.json の features）、出力 `label` string [N] と `probabilities` float32 [N, 3]（SVM の決定関数の値。確率ではない） |
| `model_info.json` | 版、特徴量の順番、クラス、窓の長さ、学習の条件、セッション単位の交差検証での再現率、使ったライブラリの版、書き出したときの研究リポジトリのコミット |
| `replay/<session>_expected.csv` | この版での PC の判定。アプリの「再生」で、端末の判定と比べる正解（入力のデータは `app/src/debug/assets/replay/`） |

## 新しい版を作るとき

研究リポジトリ（road-irregularity-ml）で次を行う。

```sh
uv run python -m src.experiments.e20261116_export_onnx --version v<番号>_<日付> --tilt-ref startmean10  # モデルと model_info.json
uv run python -m src.experiments.e20261116_make_replay_assets --version v<番号>_<日付>             # 再生の正解
```

1. `../gradle.properties` の `roaddetector.modelVersion` を新しい版にする。
2. `./gradlew :app:testDebugUnitTest` で、アプリの実装と PC の判定が一致するかを確かめる。
3. 上の表に 1 行足す。古い版のフォルダは消さない（判定の記録と、どの版で出した結果かを対応づけるため）。

傾きの基準は `model_info.json` の `tilt_ref` で、アプリはそれを読んで同じ基準で計算する（`startmean<秒>`・`mean<秒>`・`ema<秒>` に対応）。それ以外の特徴量の計算の手順（窓の長さなど）を変えたときは、`app/src/main/java/.../core/CoreFeatureExtractor.kt` と研究リポジトリの `src/roadml/core_model.py` を、同じように直す必要がある。
