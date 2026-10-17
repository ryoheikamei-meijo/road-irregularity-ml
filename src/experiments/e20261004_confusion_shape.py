"""尖度・クレスト追加後の主要設定の混同行列(セッション単位CV)を出す。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.experiments.e20261004_shape_features import FEATURE_SETS
from src.experiments.e20261004_shape_features import build_run
from src.roadml.datasets import load_dataset

CASES = [(2.0, "xyz12+kurt+crest", "RandomForest"), (1.0, "xyz12+kurt+crest", "RandomForest"),
         (1.0, "z4+kurt+crest", "SVM")]
NAMES = ["flat", "step", "rough"]

# 10.3 + 10.4 の全セッション(前固定を含む)。以前は一時ディレクトリにリンクを並べて使っていた
run_dirs = load_dataset("all_103_104")
cache: dict[float, pd.DataFrame] = {}
for window_s, feats, model_name in CASES:
    if window_s not in cache:
        cache[window_s] = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
    df = cache[window_s]
    pred = cross_val_predict(models()[model_name], df[FEATURE_SETS[feats]], df["label"],
                             groups=df["group"], cv=LeaveOneGroupOut())
    cm = pd.DataFrame(confusion_matrix(df["label"], pred, labels=LABELS), index=NAMES, columns=NAMES)
    print(f"\n### 窓{window_s}s / {feats} / {model_name}  (行=正解, 列=予測)")
    print(cm.to_string())
    print((cm.div(cm.sum(axis=1), axis=0) * 100).round(0).astype(int).to_string())
    # セッション別: 各セッションで正解クラスと予測の内訳
    detail = df.assign(pred=pred).groupby(["group", "label", "pred"]).size().unstack(fill_value=0)
    print(detail.rename(columns={"dansa": "step", "dekobo": "rough"}).to_string())
