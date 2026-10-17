"""CLI for plotting raw device-frame acceleration waveforms."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.roadml.visualization.raw_acc import iter_run_dirs, plot_run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot device-frame acceleration waveforms from acc.csv files."
    )
    parser.add_argument("--input-dir", required=True, help="Run directory or its parent.")
    parser.add_argument("--output-dir", required=True, help="Directory for PNG files.")
    args = parser.parse_args()

    run_dirs = iter_run_dirs(args.input_dir)
    if not run_dirs:
        raise ValueError(f"No run directories found under {args.input_dir}")
    for run_dir in run_dirs:
        if (run_dir / "acc.csv").exists():
            print(f"Saved plot to: {plot_run(run_dir, Path(args.output_dir))}")


if __name__ == "__main__":
    main()
