"""10.3 の z軸基本4特徴量で、窓幅を変えながらセッション単位CV(LOGO)の精度を比較する。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import f1_score
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.scripts.evaluate_103_baseline import FEATURES
from src.scripts.evaluate_103_baseline import LABELS
from src.scripts.evaluate_103_baseline import models
from src.scripts.plot_boxplots_103 import build_run_dataframe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="wheelchair_data/10.3")
    parser.add_argument("--windows", type=float, nargs="+", default=[0.1, 0.2, 0.3, 0.5, 1.0, 2.0])
    parser.add_argument("--stride-ratio", type=float, default=0.25, help="stride = window * ratio")
    parser.add_argument("--output", default="data/analysis/20261004_boxplot_103/window_sweep.csv")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    rows = []
    for window_s in args.windows:
        df = pd.concat(
            [
                build_run_dataframe(
                    run_dir,
                    window_ms=window_s * 1000.0,
                    stride_ms=window_s * 1000.0 * args.stride_ratio,
                    threshold=0.5,
                    pre_extension_ms=500.0,
                    min_fill=0.8,
                )
                for run_dir in run_dirs
            ],
            ignore_index=True,
        )
        counts = df["label"].value_counts()
        for name, model in models().items():
            pred = cross_val_predict(
                model, df[FEATURES], df["label"], groups=df["run_id"], cv=LeaveOneGroupOut()
            )
            recall = recall_score(df["label"], pred, labels=LABELS, average=None)
            rows.append(
                {
                    "window_s": window_s,
                    "model": name,
                    "n_windows": len(df),
                    "n_flat": counts.get("flat", 0),
                    "balanced_acc": balanced_accuracy_score(df["label"], pred),
                    "macro_f1": f1_score(df["label"], pred, labels=LABELS, average="macro"),
                    "recall_flat": recall[0],
                    "recall_step": recall[1],
                    "recall_rough": recall[2],
                }
            )
    result = pd.DataFrame(rows)
    result.to_csv(args.output, index=False)
    print(result.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
