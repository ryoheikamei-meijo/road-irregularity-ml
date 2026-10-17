"""CLI for plotting three-axis world-frame acceleration waveforms."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.visualization.world_frame import (
    iter_run_dirs,
    load_acc_dataframe,
    plot_world_run,
    transform_to_world_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot three-axis world-frame acceleration from raw acc.csv files."
    )
    parser.add_argument("--input-dir", required=True, help="Run directory or its parent.")
    parser.add_argument("--output-dir", required=True, help="Directory for PNG files.")
    args = parser.parse_args()

    run_dirs = iter_run_dirs(args.input_dir)
    if not run_dirs:
        raise ValueError(f"No run directories found under {args.input_dir}")
    for run_dir in run_dirs:
        acc_path = run_dir / "acc.csv"
        if acc_path.exists():
            world_df = transform_to_world_frame(load_acc_dataframe(acc_path))
            print(f"Saved plot to: {plot_world_run(run_dir, Path(args.output_dir), world_df)}")


if __name__ == "__main__":
    main()
