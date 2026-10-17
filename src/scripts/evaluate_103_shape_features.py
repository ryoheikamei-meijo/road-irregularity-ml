"""方針A(flat=平坦のみセッション, 区間外窓は捨てる)で、尖度・クレストファクターを足した特徴量を比較する。

flat は1セッションのため、時間方向5ブロックの擬似グループでLOGOに混ぜる(evaluate_103_planA と同じ)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import f1_score
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.scripts.evaluate_103_baseline import LABELS
from src.scripts.evaluate_103_baseline import models
from src.scripts.plot_boxplots_103 import build_intervals
from src.scripts.plot_boxplots_103 import label_window
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

BASIC = ["std", "range", "rms", "diff_max"]
SHAPE = ["kurt", "crest"]
FEATURE_SETS = {
    "z4": [f"z_{f}" for f in BASIC],
    "z4+kurt+crest": [f"z_{f}" for f in BASIC + SHAPE],
    "xyz12": [f"{a}_{f}" for a in "xyz" for f in BASIC],
    "xyz12+kurt+crest": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE],
    "xyz_kurt+crest_only": [f"{a}_{f}" for a in "xyz" for f in SHAPE],
}


def axis_features(values: np.ndarray, prefix: str) -> dict[str, float]:
    rms = float(np.sqrt(np.mean(values**2)))
    return {
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_range": float(np.ptp(values)),
        f"{prefix}_rms": rms,
        f"{prefix}_diff_max": float(np.max(np.diff(values))),
        f"{prefix}_kurt": float(kurtosis(values)),  # Fisher(正規分布=0)
        f"{prefix}_crest": float(np.max(np.abs(values)) / rms) if rms > 0 else 0.0,
    }


def build_run(run_dir: Path, window_s: float, flat_blocks: int) -> pd.DataFrame:
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    ts = world["timestamp"].to_numpy(float)
    axes = {
        "x": world["accWorldX"].to_numpy(float),
        "y": world["accWorldY"].to_numpy(float),
        "z": world["accWorldZ"].to_numpy(float) - GRAVITY_MPS2,
    }
    has_events = (run_dir / "dansa.csv").exists() or (run_dir / "dekobo.csv").exists()
    intervals = build_intervals(run_dir, 500.0)
    window_ms, stride_ms = window_s * 1000.0, window_s * 250.0
    expected = window_ms / np.median(np.diff(ts))
    rows, start = [], ts[0]
    while start + window_ms <= ts[-1]:
        lo, hi = np.searchsorted(ts, [start, start + window_ms])
        if hi - lo >= 0.8 * expected:
            label = label_window(start, start + window_ms, intervals, 0.5) if has_events else "flat"
            if not (has_events and label == "flat"):  # 区間外は捨てる
                row = {"start_ms": start, "label": label}
                for key, values in axes.items():
                    row.update(axis_features(values[lo:hi], key))
                rows.append(row)
        start += stride_ms
    df = pd.DataFrame(rows)
    if has_events:
        return df.assign(group=run_dir.name)
    edges = np.linspace(df["start_ms"].min(), df["start_ms"].max(), flat_blocks + 1)
    block = np.clip(np.searchsorted(edges, df["start_ms"], side="right") - 1, 0, flat_blocks - 1)
    near = np.min(np.abs(df["start_ms"].to_numpy()[:, None] - edges[1:-1]), axis=1) < window_ms
    return df.assign(group=[f"{run_dir.name}_b{b}" for b in block])[~near]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--windows", type=float, nargs="+", default=[0.5, 1.0, 2.0])
    parser.add_argument("--flat-blocks", type=int, default=5)
    parser.add_argument("--output", default="data/analysis/20261004_boxplot_103_104/shape_features_sweep.csv")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    rows = []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, args.flat_blocks) for d in run_dirs], ignore_index=True)
        if window_s == 1.0:
            df.to_csv(Path(args.output).with_name("shape_features_windows_1s.csv"), index=False)
        print(f"\n=== window {window_s}s: {dict(df['label'].value_counts())}", flush=True)
        for set_name, cols in FEATURE_SETS.items():
            for model_name, model in models().items():
                pred = cross_val_predict(model, df[cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
                recall = recall_score(df["label"], pred, labels=LABELS, average=None)
                rows.append({
                    "window_s": window_s, "features": set_name, "model": model_name,
                    "balanced_acc": balanced_accuracy_score(df["label"], pred),
                    "macro_f1": f1_score(df["label"], pred, labels=LABELS, average="macro"),
                    "recall_flat": recall[0], "recall_step": recall[1], "recall_rough": recall[2],
                })
                print(f"  {set_name:22s} {model_name:12s} bal_acc={rows[-1]['balanced_acc']:.3f}", flush=True)
    result = pd.DataFrame(rows)
    result.to_csv(args.output, index=False)
    print(result.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
