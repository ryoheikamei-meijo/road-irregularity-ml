# 2026-07-12 6.22 + 7.12 結合データセット学習・評価まとめ

## 概要

`wheelchair_data/6.22` と `wheelchair_data/7.12`（71kgデータ除外）を結合した1つのデータセットで、Random Forest / SVM を再学習・評価した。目的は、収集日・収集方法が異なる2つのデータソースを混ぜたときに段差（dansa）・凹凸（dekobo）の検出性能がどう変化するかを確認すること。

## データセット構築

- 6.22側: `data/features/20260630092253/wheelchair_world_z_dataset.csv`（前倒し0.5秒版、11 run）
- 7.12側: `data/features/20260712215522/wheelchair_world_z_dataset_712.csv` から **71kg run `20260711201934` を除外**（`20260711202058` は [[20260712_wheelchair_712_vs_622_comparison]] の理由で既に除外済み）
- 結合後: `data/features/20260712_combined/wheelchair_world_z_dataset_combined_51kg.csv`
  - 22 run（6.22: 11 / 7.12: 11、いずれも51kgのみ）
  - 4,617 windows（dansa 93 / dekobo 422 / flat 4,102）

コンフィグは新規作成:
- `configs/wheelchair_world_z_combined_random_forest.yaml`
- `configs/wheelchair_world_z_combined_svm.yaml`

window設定は既存6.22実験と同一（window 1.0秒 / stride 0.25秒 / ラベル前倒し0.5秒）。

## train / eval split（初回: eval 4run版）

各収集日から dansa・dekobo を含む run を2つずつ eval に割り当てた。

- eval run:
  - `20260622180835`（dansa 27 / dekobo 27 / flat 332）
  - `20260622182112`（dansa 11 / dekobo 68 / flat 162）
  - `20260711202154`（dansa 6 / flat 27）
  - `20260711201718`（dekobo 32 / flat 1）
- train run: 上記4件を除く残り18 run（train samples: 3,924 / eval samples: 693）

### 結果（all_eval, 4run版）

| モデル | accuracy | flat precision/recall/f1 | dansa precision/recall/f1 | dekobo precision/recall/f1 | macro f1 |
|---|---:|---|---|---|---:|
| Random Forest | 0.7792 | 0.7778 / 0.9923 / 0.8721 | 0.0000 / 0.0000 / 0.0000 | 0.8148 / 0.1732 / 0.2857 | 0.3859 |
| SVM | 0.7085 | 0.8621 / 0.8027 / 0.8313 | 0.0694 / 0.1136 / 0.0862 | 0.4963 / 0.5276 / 0.5115 | 0.4763 |

- `data/processed/20260712220425`（Random Forest）
- `data/processed/20260712220433`（SVM）

ただでさえ dansa のサンプルが少ない中で、eval に4 run（693 windows）も割くと train に回せる dansa データがさらに減ってしまうため、**eval を2 runに絞って再学習**した（下記）。

## train / eval split（採用版: eval 2run）

7.12の dansa単発run（`20260711202154`）と dekobo単発run（`20260711201718`）を train側に戻し、eval は6.22の dansa・dekobo混在run 2つのみに絞った。

- eval run:
  - `20260622180835`（dansa 27 / dekobo 27 / flat 332）
  - `20260622182112`（dansa 11 / dekobo 68 / flat 162）
- train run: 上記2件を除く残り20 run（train samples: 3,990 / eval samples: 627）

### 結果（all_eval, 2run版）

| モデル | accuracy | flat precision/recall/f1 | dansa precision/recall/f1 | dekobo precision/recall/f1 | macro f1 |
|---|---:|---|---|---|---:|
| Random Forest | 0.7927 | 0.7997 / 0.9858 / 0.8830 | 0.0000 / 0.0000 / 0.0000 | 0.5556 / 0.1053 / 0.1770 | 0.3533 |
| SVM | 0.7129 | 0.8717 / 0.8117 / 0.8407 | 0.0500 / 0.0789 / 0.0612 | 0.4019 / 0.4526 / 0.4257 | 0.4425 |

- `data/processed/20260712221029`（Random Forest）
- `data/processed/20260712221031`（SVM）

### run別の内訳（2run版）

| eval run | モデル | accuracy | dansa recall | dekobo recall |
|---|---|---:|---:|---:|
| `20260622180835` | RF | 0.8601 | 0.0000 | 0.0741 |
| `20260622180835` | SVM | 0.8135 | 0.0741 | 0.5185 |
| `20260622182112` | RF | 0.6846 | 0.0000 | 0.1176 |
| `20260622182112` | SVM | 0.5519 | 0.0909 | 0.4265 |

## 考察

- train samplesは 3,924 → 3,990（+66）に増加し、dansaの学習サンプルは 55 → 63（+8）、dekoboは 295 → 327（+32）に増えた。ただしeval runが6.22の2件のみになったため、7.12データに対する汎化性能はこの評価だけでは分からなくなった点に注意（7.12の`20260711202154`・`20260711201718`は今回train専用になった）。
- **Random Forest**は4run版・2run版いずれもdansa recall = 0.0000で変化なし。dekobo recallはむしろ0.1732→0.1053に低下しており、依然として`flat`に強く偏る傾向（[[20260630_wheelchair_world_z_experiment_summary]] 実験Eと同様の傾向）が変わらない。
- **SVM**はaccuracy 0.7085→0.7129とほぼ横ばい、dekobo recallは0.5276→0.4526に低下、dansa recallも0.1136→0.0789に低下している。7.12のdekobo単発run（旧evalでrecall 0.7188と最も高い成績だった`20260711201718`）がtrainに移ったことで、eval側（6.22のみ）の平均は下がった形。
- 全体として、**eval runを絞ったことで6.22データに対する評価は安定して見られるようになった**が、train samplesが増えた割にはdansa/dekoboの評価指標は改善しておらず、eval run数を減らすこと自体がモデル性能を底上げするわけではないことが分かった。dansaが依然0件しか拾えない点は一貫しており、根本原因（イベント絶対数の少なさ）は解消されていない。

## 次にやるべきこと

1. dansa専用の追加収集（現状9イベント程度では学習・評価とも成立しない）
2. `pre_event_extension_seconds` を結合データセットでも 0.25/0.5/0.75/1.0 で系統比較
3. 71kgデータの追加収集後、体重を特徴量またはグルーピング変数として組み込めるか検討
4. 7.12の「単一イベント特化収集」と6.22の「長時間混在収集」を分けて train/eval したときの性能差を定量比較（収集方式そのものがモデル性能に与える影響の切り分け）
5. eval run数を2⇔4で切り替えた際の指標変動が大きいため、run単位の交差検証（leave-one-run-out）で安定した評価を取ることを検討
