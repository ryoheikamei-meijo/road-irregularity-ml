"""後ろ固定のみ(10.3 + 10.4)の主な評価値が変わっていないことを確かめる回帰テスト。

リファクタリングの前後で、窓の切り出し・ラベル付け・特徴量・評価の結果が変わらないことを見る。
値は docs/knowledge/2026-10-12 と 2026-10-17 のメモに書いた値。
実測データ(wheelchair_data/、git 管理外)が無い環境ではスキップする。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.roadml.datasets import load_dataset
from src.roadml.evaluation import models
from src.roadml.evaluation import summarize
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.features import cols
from src.roadml.features import horizontal_axes
from src.roadml.windows import build_run

ROOT = Path(__file__).resolve().parents[1]

try:
    RUN_DIRS = load_dataset("rear_only_103_104", root=ROOT)
except FileNotFoundError:
    RUN_DIRS = []

pytestmark = pytest.mark.skipif(not RUN_DIRS, reason="実測データ(wheelchair_data/)が無い")


@pytest.fixture(scope="module")
def windows() -> dict[float, pd.DataFrame]:
    return {
        w: pd.concat([build_run(d, w, 5, extra_axes=horizontal_axes) for d in RUN_DIRS], ignore_index=True)
        for w in (2.0, 1.0)
    }


def bal_acc(df: pd.DataFrame, feature_cols: list[str], model_name: str) -> float:
    model = models()[model_name]
    pred = cross_val_predict(model, df[feature_cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
    return summarize(df["label"], pred)["bal_acc"]


def test_window_counts(windows):
    assert dict(windows[2.0]["label"].value_counts()) == {"dansa": 371, "dekobo": 296, "flat": 116}
    assert dict(windows[1.0]["label"].value_counts()) == {"dansa": 746, "dekobo": 597, "flat": 267}
    assert windows[2.0]["group"].nunique() == 16


@pytest.mark.parametrize(
    ("window_s", "axes", "model_name", "expected"),
    [
        (2.0, "xyz", "SVM", 0.861),
        (2.0, "xyz", "RandomForest", 0.811),
        (2.0, "m", "SVM", 0.849),
        (2.0, "z", "SVM", 0.822),
        (2.0, "zh", "SVM", 0.876),
        (1.0, "xyz", "SVM", 0.832),
    ],
)
def test_balanced_accuracy(windows, window_s, axes, model_name, expected):
    got = bal_acc(windows[window_s], cols(axes, BASIC + SHAPE), model_name)
    assert np.round(got, 3) == pytest.approx(expected, abs=1e-9)
