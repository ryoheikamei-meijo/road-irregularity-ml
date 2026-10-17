"""方針A: flat は「イベント無し」セッションのみ。イベントセッションの区間外窓は使わない。

flat セッションは1つしか無いため、時間方向に連続した N ブロックへ分けて擬似グループとし、
ブロック境界から窓幅以内の窓は捨てて(リーク防止)セッション単位CV(LOGO)に混ぜる。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix
from sklearn.metrics import f1_score
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.scripts.evaluate_103_baseline import FEATURES
from src.scripts.evaluate_103_baseline import LABELS
from src.scripts.evaluate_103_baseline import models
from src.scripts.plot_boxplots_103 import build_run_dataframe


def build_planA_dataframe(run_dirs: list[Path], window_s: float, flat_blocks: int) -> pd.DataFrame:
    frames = []
    for run_dir in run_dirs:
        df = build_run_dataframe(
            run_dir, window_ms=window_s * 1000.0, stride_ms=window_s * 250.0,
            threshold=0.5, pre_extension_ms=500.0, min_fill=0.8,
        )
        has_events = (run_dir / "dansa.csv").exists() or (run_dir / "dekobo.csv").exists()
        if has_events:
            df = df[df["label"] != "flat"].assign(group=run_dir.name)  # 区間外は捨てる
        else:
            df = df.assign(label="flat")
            edges = np.linspace(df["start_ms"].min(), df["start_ms"].max(), flat_blocks + 1)
            block = np.clip(np.searchsorted(edges, df["start_ms"], side="right") - 1, 0, flat_blocks - 1)
            near_edge = np.min(np.abs(df["start_ms"].to_numpy()[:, None] - edges[1:-1]), axis=1) < window_s * 1000.0
            df = df.assign(group=[f"{run_dir.name}_b{b}" for b in block])[~near_edge]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--windows", type=float, nargs="+", default=[0.3, 0.5, 1.0, 2.0])
    parser.add_argument("--flat-blocks", type=int, default=5)
    parser.add_argument("--output", default="data/analysis/20261004_boxplot_103_104/planA_sweep.csv")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    rows = []
    for window_s in args.windows:
        df = build_planA_dataframe(run_dirs, window_s, args.flat_blocks)
        if window_s == 1.0:
            df.to_csv(Path(args.output).with_name("planA_window_features_1s.csv"), index=False)
        counts = df["label"].value_counts()
        print(f"\n=== window {window_s}s: {dict(counts)}")
        for name, model in models().items():
            pred = cross_val_predict(model, df[FEATURES], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
            y = df["label"]
            recall = recall_score(y, pred, labels=LABELS, average=None)
            rows.append({
                "window_s": window_s, "model": name, "n_flat": counts["flat"],
                "n_step": counts["dansa"], "n_rough": counts["dekobo"],
                "balanced_acc": balanced_accuracy_score(y, pred),
                "macro_f1": f1_score(y, pred, labels=LABELS, average="macro"),
                "recall_flat": recall[0], "recall_step": recall[1], "recall_rough": recall[2],
            })
            if window_s == 1.0:
                print(name)
                print(pd.DataFrame(confusion_matrix(y, pred, labels=LABELS), index=LABELS, columns=LABELS).to_string())
    result = pd.DataFrame(rows)
    result.to_csv(args.output, index=False)
    print(result.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
