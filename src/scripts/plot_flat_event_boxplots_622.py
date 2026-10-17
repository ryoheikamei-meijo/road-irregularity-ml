"""wheelchair_data/6.22 のみを使って flat/step/rough の特徴量箱ひげ図を書き直す。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

from src.analysis.flat_event import AXES
from src.analysis.flat_event import AXIS_FEATURE_COLUMNS
from src.analysis.flat_event import plot_feature_distributions
from src.analysis.flat_event import plot_three_class_feature_distributions
from src.config import load_config
from src.wheelchair_pipeline import build_multi_axis_dataset_dataframe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/analysis/20260825_flat_event_622only")
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()

    config = deepcopy(load_config("configs/wheelchair_world_z_svm.yaml"))
    config["window"]["window_seconds"] = args.window_seconds
    dataframe = build_multi_axis_dataset_dataframe(config=config, axes=AXES)

    figures_dir = Path(args.output_dir) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    for axis_key in AXES:
        suffix = "" if axis_key == "z" else f"_{axis_key}"
        plot_feature_distributions(
            dataframe,
            figures_dir / f"feature_distributions{suffix}.png",
            features=AXIS_FEATURE_COLUMNS[axis_key],
            axis_key=axis_key,
        )
        plot_three_class_feature_distributions(
            dataframe,
            figures_dir / f"three_class_feature_distributions{suffix}.png",
            features=AXIS_FEATURE_COLUMNS[axis_key],
            axis_key=axis_key,
        )

    print(f"Saved figures to: {figures_dir}")
    print(dataframe["label"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
