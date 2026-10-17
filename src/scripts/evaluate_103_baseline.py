"""10.3 の z軸基本4特徴量で SVM / RandomForest をセッション単位CV(LOGO)で評価する。

比較用に、窓をシャッフルして分けるリークありのStratifiedKFoldも出す(参考値)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix
from sklearn.metrics import f1_score
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import StratifiedKFold
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

FEATURES = ["z_std", "z_range", "z_rms", "z_diff_max"]
LABELS = ["flat", "dansa", "dekobo"]


def models():
    return {
        "SVM": make_pipeline(
            StandardScaler(), SVC(kernel="rbf", C=1.0, gamma="scale", class_weight="balanced")
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=42
        ),
    }


def report(name: str, scheme: str, y: np.ndarray, pred: np.ndarray) -> None:
    recalls = recall_score(y, pred, labels=LABELS, average=None)
    print(
        f"[{scheme}] {name}: balanced_acc={balanced_accuracy_score(y, pred):.3f} "
        f"macro_F1={f1_score(y, pred, labels=LABELS, average='macro'):.3f} "
        f"recall(flat/step/rough)={recalls[0]:.2f}/{recalls[1]:.2f}/{recalls[2]:.2f}"
    )
    matrix = pd.DataFrame(
        confusion_matrix(y, pred, labels=LABELS),
        index=[f"true_{l}" for l in LABELS],
        columns=[f"pred_{l}" for l in LABELS],
    )
    print(matrix.to_string(), "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features-csv", default="data/analysis/20261004_boxplot_103/window_features.csv")
    args = parser.parse_args()

    df = pd.read_csv(args.features_csv)
    X, y, groups = df[FEATURES], df["label"].to_numpy(), df["run_id"].to_numpy()
    print(df["label"].value_counts().to_string(), "\n")

    for name, model in models().items():
        pred = cross_val_predict(model, X, y, groups=groups, cv=LeaveOneGroupOut())
        report(name, "LOGO(セッション単位)", y, pred)
    for name, model in models().items():
        pred = cross_val_predict(model, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=42))
        report(name, "参考:窓シャッフル5fold(リークあり)", y, pred)


if __name__ == "__main__":
    main()
