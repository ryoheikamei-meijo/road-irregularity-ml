"""CLI for plotting world-frame vertical acceleration waveforms."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.visualization.world_z import iter_world_csv_dirs, load_world_dataframe, plot_world_z


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot world-frame Z-axis waveforms from acc_world.csv files."
    )
    parser.add_argument("--world-csv-dir", required=True, help="Directory containing run CSVs.")
    parser.add_argument("--raw-dir", required=True, help="Directory containing raw run data.")
    parser.add_argument("--output-dir", required=True, help="Directory for PNG files.")
    args = parser.parse_args()

    entries = iter_world_csv_dirs(Path(args.world_csv_dir))
    if not entries:
        raise ValueError(f"No acc_world.csv files found under {args.world_csv_dir}")
    for run_name, csv_path in entries:
        output_path = plot_world_z(
            run_name,
            load_world_dataframe(csv_path),
            Path(args.raw_dir) / run_name,
            Path(args.output_dir),
        )
        print(f"Saved plot to: {output_path}")


if __name__ == "__main__":
    main()
