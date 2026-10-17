"""モデルと、セッション単位の交差検証(LOGO)の評価。"""

from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import f1_score
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

LABELS = ["flat", "dansa", "dekobo"]
DISPLAY = {"flat": "flat", "dansa": "step", "dekobo": "rough"}


def models():
    return {
        "SVM": make_pipeline(
            StandardScaler(), SVC(kernel="rbf", C=1.0, gamma="scale", class_weight="balanced")
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=42
        ),
    }


def summarize(y, pred) -> dict[str, float]:
    recall = recall_score(y, pred, labels=LABELS, average=None, zero_division=0)
    return {"bal_acc": balanced_accuracy_score(y, pred),
            "macro_f1": f1_score(y, pred, labels=LABELS, average="macro", zero_division=0),
            "r_flat": recall[0], "r_step": recall[1], "r_rough": recall[2]}


def vote(df: pd.DataFrame, unit_col: str) -> pd.DataFrame:
    """単位ごとに窓予測の多数決を取る。"""
    rows = []
    for unit, sub in df.groupby(unit_col):
        counts = sub["pred"].value_counts()
        rows.append({"unit": unit, "label": sub["label"].iloc[0], "n": len(sub),
                     "pred": counts.idxmax(), "share": counts.max() / len(sub)})
    return pd.DataFrame(rows)


def logo_predict(df: pd.DataFrame, feature_cols: list[str], model):
    """セッション(flat はブロック)単位の Leave-One-Group-Out の予測。"""
    return cross_val_predict(model, df[feature_cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())


def evaluate(df: pd.DataFrame, feature_cols: list[str], model) -> dict[str, float]:
    """3 クラスの評価に加えて、step と rough だけで学習し直した 2 クラスの balanced accuracy(sr_bal_acc)。"""
    pred = logo_predict(df, feature_cols, model)
    result = summarize(df["label"], pred)
    # step と rough だけに絞った2クラス評価(flat が1セッションしかない影響を除いて、本来の課題を見る)。
    sr = df[df["label"] != "flat"]
    sr_pred = logo_predict(sr, feature_cols, model)
    return {**result, "sr_bal_acc": balanced_accuracy_score(sr["label"], sr_pred)}
