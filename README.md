# Road Irregularity ML

手動式車椅子走行時の加速度データを用いて，路面凹凸を検知するための機械学習実験用リポジトリ．

## Environment

Python 3.13 を使用する．

## Setup

```bash
uv sync
```

## Install dependencies

```bash
uv add numpy pandas scipy scikit-learn matplotlib pyyaml
uv add --dev ruff pytest ipykernel
```

## Run dummy training

```bash
uv run python -m src.train_dummy --config configs/svm.yaml
uv run python -m src.train_dummy --config configs/random_forest.yaml
```

## Notes

- data/raw/，data/processed/，data/features/ はGit管理しない．
- 実験データには位置情報が含まれる可能性があるため，GitHubには原則アップロードしない．
