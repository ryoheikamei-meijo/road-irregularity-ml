"""CLI for plotting cropped step/rough world-Z waveforms."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.roadml.visualization.world_z import load_world_dataframe, plot_world_z_event_crop


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot presentation crops of step/rough world-Z events."
    )
    parser.add_argument("--world-csv", required=True, help="Path to acc_world.csv.")
    parser.add_argument(
        "--raw-run-dir",
        required=True,
        help="Run directory containing dansa.csv and dekobo.csv.",
    )
    parser.add_argument("--output-dir", required=True, help="Directory for crop PNGs.")
    parser.add_argument(
        "--step-range",
        nargs=2,
        type=float,
        metavar=("START", "STOP"),
        help="Elapsed-second range for the step crop.",
    )
    parser.add_argument(
        "--rough-range",
        nargs=2,
        type=float,
        metavar=("START", "STOP"),
        help="Elapsed-second range for the rough crop.",
    )
    args = parser.parse_args()

    ranges = {"step": args.step_range, "rough": args.rough_range}
    if not any(ranges.values()):
        parser.error("Specify at least one of --step-range or --rough-range")

    world_csv_path = Path(args.world_csv)
    raw_run_dir = Path(args.raw_run_dir)
    world_df = load_world_dataframe(world_csv_path)
    for event_kind, crop_range in ranges.items():
        if crop_range is None:
            continue
        output_path = plot_world_z_event_crop(
            raw_run_dir.name,
            world_df,
            raw_run_dir,
            Path(args.output_dir),
            event_kind=event_kind,
            xlim=(crop_range[0], crop_range[1]),
        )
        print(f"Saved plot to: {output_path}")


if __name__ == "__main__":
    main()
