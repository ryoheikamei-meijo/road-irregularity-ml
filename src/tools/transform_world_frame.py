"""CLI for converting raw acceleration logs to the world coordinate frame."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.roadml.io import load_acc_dataframe, transform_to_world_frame
from src.roadml.visualization.world_frame import iter_run_dirs, save_transformed_dataframe


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create <run_id>/acc_world.csv files from raw acc.csv files."
    )
    parser.add_argument("--input-dir", required=True, help="Run directory or its parent.")
    parser.add_argument("--output-dir", required=True, help="Directory for world-frame CSV files.")
    args = parser.parse_args()

    run_dirs = iter_run_dirs(args.input_dir)
    if not run_dirs:
        raise ValueError(f"No run directories found under {args.input_dir}")
    for run_dir in run_dirs:
        acc_path = run_dir / "acc.csv"
        if not acc_path.exists():
            continue
        world_df = transform_to_world_frame(load_acc_dataframe(acc_path))
        output_path = Path(args.output_dir) / run_dir.name / "acc_world.csv"
        print(f"Saved transformed csv to: {save_transformed_dataframe(world_df, output_path)}")


if __name__ == "__main__":
    main()
