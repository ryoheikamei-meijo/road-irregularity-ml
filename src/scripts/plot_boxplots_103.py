"""wheelchair_data/10.3 のみを使って flat/step/rough のz軸基本特徴量箱ひげ図を書く。

10.3 は約334Hzで、イベント(*_cont_start/stop)の elapsed_ms は acc.csv の elapsed と
基準時刻がずれる(PlotThread開始がセンサ開始より遅い)。そのため壁時計の
timestamp(ms)で窓とイベント区間を突き合わせる。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.flat_event import AXIS_FEATURE_COLUMNS
from src.analysis.flat_event import plot_three_class_feature_distributions
from src.analysis.jerk_event import plot_three_class_jerk_distributions
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2
from src.wheelchair_pipeline import compute_axis_window_features
from src.wheelchair_pipeline import compute_overlap_ratio

KINDS = ("dansa", "dekobo")


def build_intervals(run_dir: Path, pre_extension_ms: float) -> dict[str, list[tuple[float, float]]]:
    """dansa/dekobo の start〜stop(通常・_cont とも)を timestamp_ms の区間にする。"""
    intervals: dict[str, list[tuple[float, float]]] = {kind: [] for kind in KINDS}
    for kind in KINDS:
        path = run_dir / f"{kind}.csv"
        if not path.exists():
            continue
        events = pd.read_csv(path).sort_values("timestamp_ms")
        open_start: float | None = None
        for row in events.itertuples(index=False):
            name = str(row.event)
            if name.endswith("_start"):
                open_start = float(row.timestamp_ms)
            elif name.endswith("_stop") and open_start is not None:
                intervals[kind].append((open_start - pre_extension_ms, float(row.timestamp_ms)))
                open_start = None
    return intervals


def label_window(start_ms: float, end_ms: float, intervals, threshold: float) -> str:
    for kind in KINDS:  # 既存パイプライン同様、dansa を優先
        ratio = compute_overlap_ratio(
            window_start_ms=start_ms, window_end_ms=end_ms, intervals=intervals[kind]
        )
        if ratio >= threshold:
            return kind
    return "flat"


def build_run_dataframe(
    run_dir: Path, *, window_ms: float, stride_ms: float, threshold: float,
    pre_extension_ms: float, min_fill: float,
) -> pd.DataFrame:
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    timestamps = world["timestamp"].to_numpy(dtype=float)
    # x/y は水平方向のため重力補正なし、z は重力を引く(既存パイプラインと同じ)。
    linear = {
        "x": world["accWorldX"].to_numpy(dtype=float),
        "y": world["accWorldY"].to_numpy(dtype=float),
        "z": world["accWorldZ"].to_numpy(dtype=float) - GRAVITY_MPS2,
    }
    intervals = build_intervals(run_dir, pre_extension_ms)
    expected = window_ms / np.median(np.diff(timestamps))

    rows = []
    start = timestamps[0]
    while start + window_ms <= timestamps[-1]:
        lo, hi = np.searchsorted(timestamps, [start, start + window_ms])
        if hi - lo >= expected * min_fill:
            features: dict[str, float] = {}
            for axis_key, values in linear.items():
                features.update(
                    compute_axis_window_features(
                        values[lo:hi], prefix=axis_key, timestamps_ms=timestamps[lo:hi]
                    )
                )
            rows.append(
                {
                    "run_id": run_dir.name,
                    "start_ms": start,
                    "label": label_window(start, start + window_ms, intervals, threshold),
                    **features,
                }
            )
        start += stride_ms
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="wheelchair_data/10.3")
    parser.add_argument("--output-dir", default="data/analysis/20261004_boxplot_103")
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument("--stride-seconds", type=float, default=0.25)
    parser.add_argument("--overlap-threshold", type=float, default=0.5)
    parser.add_argument("--pre-event-extension-seconds", type=float, default=0.5)
    parser.add_argument("--min-fill", type=float, default=0.8, help="期待サンプル数に対する最低充足率")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    dataframe = pd.concat(
        [
            build_run_dataframe(
                run_dir,
                window_ms=args.window_seconds * 1000.0,
                stride_ms=args.stride_seconds * 1000.0,
                threshold=args.overlap_threshold,
                pre_extension_ms=args.pre_event_extension_seconds * 1000.0,
                min_fill=args.min_fill,
            )
            for run_dir in run_dirs
        ],
        ignore_index=True,
    )

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_dir / "window_features.csv", index=False)
    plot_three_class_feature_distributions(
        dataframe,
        figures_dir / "three_class_feature_distributions.png",
        features=AXIS_FEATURE_COLUMNS["z"],
        axis_key="z",
    )
    plot_three_class_jerk_distributions(
        dataframe, figures_dir / "three_class_jerk_distributions.png"
    )

    print(f"Saved figures to: {figures_dir}")
    print(dataframe["label"].value_counts().to_string())
    print(dataframe.groupby("label")[AXIS_FEATURE_COLUMNS["z"]].median().round(3).to_string())
    jerk_columns = [f"{a}_jerk_{s}" for a in "xyz" for s in ("rms", "std")]
    print(dataframe.groupby("label")[jerk_columns].median().round(0).to_string())


if __name__ == "__main__":
    main()
