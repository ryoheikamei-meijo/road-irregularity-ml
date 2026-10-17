"""方針Aのラベル(flat=平坦のみセッション、event=区間内窓)で、窓内のz加速度の最大・最小の振れを比較する。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from src.scripts.plot_boxplots_103 import build_intervals
from src.scripts.plot_boxplots_103 import label_window
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"
NAMES = {"flat": "flat", "dansa": "step", "dekobo": "rough"}


def windows(run_dir: Path, window_ms: float) -> pd.DataFrame:
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    ts = world["timestamp"].to_numpy(float)
    z = world["accWorldZ"].to_numpy(float) - GRAVITY_MPS2
    has_events = (run_dir / "dansa.csv").exists() or (run_dir / "dekobo.csv").exists()
    intervals = build_intervals(run_dir, 500.0)
    rows, start = [], ts[0]
    while start + window_ms <= ts[-1]:
        lo, hi = np.searchsorted(ts, [start, start + window_ms])
        if hi - lo >= 0.8 * window_ms / np.median(np.diff(ts)):
            if has_events:
                label = label_window(start, start + window_ms, intervals, 0.5)
            else:
                label = "flat"
            if has_events and label == "flat":  # 方針A: 区間外は使わない
                start += window_ms / 4
                continue
            seg = z[lo:hi]
            rows.append({"run_id": run_dir.name, "label": NAMES[label],
                         "z_max": seg.max(), "z_min": seg.min(), "z_absmax": np.abs(seg).max()})
        start += window_ms / 4
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", default="data/analysis/20261004_boxplot_103_104")
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()

    dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    df = pd.concat([windows(d, args.window_seconds * 1000.0) for d in dirs], ignore_index=True)
    out = Path(args.output_dir)
    df.to_csv(out / "peak_windows.csv", index=False)

    cols = ["z_max", "z_min", "z_absmax"]
    print(df.groupby("label")[cols].describe(percentiles=[0.05, 0.5, 0.95]).T.round(1).to_string())
    event = df[df["label"] != "flat"]
    flat = df[df["label"] == "flat"]
    # 閾値(flat窓のabsmaxの何%点を基準にするか)ごとの、flat/eventの判定率
    for q in (0.90, 0.95, 0.99, 1.0):
        thr = flat["z_absmax"].quantile(q)
        print(f"閾値=flat窓 |z|max の{q:.0%}点({thr:.1f}): event窓の検出率={np.mean(event['z_absmax'] > thr):.1%}")
    y = (df["label"] != "flat").astype(int)
    for c in cols:
        print(f"AUC flat vs event ({c}):", round(roc_auc_score(y, df[c] if c != 'z_min' else -df[c]), 3))
    print("event窓のうち step/rough 別 検出率(flat窓|z|max 95%点):")
    thr = flat["z_absmax"].quantile(0.95)
    print(event.groupby("label")["z_absmax"].apply(lambda s: np.mean(s > thr)).round(3).to_string())
    print("\nsession別 flat/event 窓の |z|max 中央値:")
    print(df.groupby(["run_id", "label"])["z_absmax"].median().round(1).to_string())

    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    for ax, c, t in zip(axes, cols, ("窓内の最大値", "窓内の最小値", "窓内の|z|最大")):
        data = [df.loc[df["label"] == g, c] for g in ("flat", "step", "rough")]
        ax.boxplot(data, tick_labels=[f"{g}\n(n={len(d)})" for g, d in zip(("flat", "step", "rough"), data)],
                   showfliers=False, medianprops={"color": "tab:orange", "linewidth": 1.5})
        ax.set_title(t); ax.set_ylabel("[m/s²]"); ax.grid(axis="y", alpha=0.3)
    fig.suptitle(f"z加速度(重力除去)の窓内最大・最小(窓{args.window_seconds}秒, 方針Aラベル)")
    fig.tight_layout()
    fig.savefig(out / "figures" / "peak_flat_vs_event.png", dpi=180)


if __name__ == "__main__":
    main()
