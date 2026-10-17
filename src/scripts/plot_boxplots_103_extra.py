"""10.3 の追加箱ひげ図: (1) z軸加速度(サンプル単位) (2) x/y軸の基本4特徴量(窓単位)。

(2) は plot_boxplots_103.py が出力した window_features.csv を使う。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analysis.flat_event import AXIS_FEATURE_COLUMNS
from src.analysis.flat_event import DISPLAY_LABELS
from src.analysis.flat_event import plot_three_class_feature_distributions
from src.scripts.plot_boxplots_103 import KINDS
from src.scripts.plot_boxplots_103 import build_intervals
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"
GROUPS = ("flat", "step", "rough")


def load_sample_dataframe(data_dir: Path, pre_extension_ms: float) -> pd.DataFrame:
    frames = []
    for run_dir in sorted(p for p in data_dir.iterdir() if (p / "acc.csv").exists()):
        world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
        timestamps = world["timestamp"].to_numpy(dtype=float)
        intervals = build_intervals(run_dir, pre_extension_ms)
        label = np.full(len(timestamps), "flat", dtype=object)
        for kind in reversed(KINDS):  # dansa を優先するため後から上書き
            for start, end in intervals[kind]:
                label[(timestamps >= start) & (timestamps <= end)] = kind
        frames.append(
            pd.DataFrame(
                {
                    "run_id": run_dir.name,
                    "label": label,
                    "z_acc": world["accWorldZ"].to_numpy(dtype=float) - GRAVITY_MPS2,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def plot_z_acc(dataframe: pd.DataFrame, output_path: Path) -> None:
    dataframe = dataframe.assign(group=dataframe["label"].map(DISPLAY_LABELS))
    figure, axes = plt.subplots(nrows=1, ncols=2, figsize=(11, 5))
    for axis, (title, column) in zip(
        axes, (("z加速度(重力除去)", "z_acc"), ("z加速度の絶対値", "z_abs")), strict=True
    ):
        values = [
            dataframe.loc[dataframe["group"] == g, "z_acc"].to_numpy(dtype=float) for g in GROUPS
        ]
        if column == "z_abs":
            values = [np.abs(v) for v in values]
        axis.boxplot(
            values,
            tick_labels=[f"{g}\n(n={len(v)})" for g, v in zip(GROUPS, values, strict=True)],
            showfliers=False,
            medianprops={"color": "tab:orange", "linewidth": 1.5},
        )
        axis.set_title(title)
        axis.set_ylabel("[m/s²]")
        axis.grid(axis="y", alpha=0.3)
    figure.suptitle("flat・step・rough のz軸加速度分布(サンプル単位, 10.3)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="wheelchair_data/10.3")
    parser.add_argument("--output-dir", default="data/analysis/20261004_boxplot_103")
    parser.add_argument("--pre-event-extension-seconds", type=float, default=0.5)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    samples = load_sample_dataframe(Path(args.data_dir), args.pre_event_extension_seconds * 1000.0)
    plot_z_acc(samples, figures_dir / "z_acceleration_boxplot.png")
    samples["group"] = samples["label"].map(DISPLAY_LABELS)
    print(samples.groupby("group")["z_acc"].describe(percentiles=[0.25, 0.5, 0.75]).round(2).to_string())

    windows = pd.read_csv(output_dir / "window_features.csv")
    for axis_key in ("x", "y"):
        plot_three_class_feature_distributions(
            windows,
            figures_dir / f"three_class_feature_distributions_{axis_key}.png",
            features=AXIS_FEATURE_COLUMNS[axis_key],
            axis_key=axis_key,
        )
    print(windows.groupby("label")[AXIS_FEATURE_COLUMNS["x"] + AXIS_FEATURE_COLUMNS["y"]].median().round(2).to_string())


if __name__ == "__main__":
    main()
