from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

EVENT_STYLES = {
    "dansa_start":  ("tab:red",  "--", "step_start"),
    "dansa_stop":   ("tab:red",  "-",  "step_stop"),
    "dekobo_start": ("magenta", "--", "rough_start"),
    "dekobo_stop":  ("magenta", "-",  "rough_stop"),
}


def load_world_dataframe(path: Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    for col in ("elapsed", "accWorldZ"):
        if col not in dataframe.columns:
            raise ValueError(f"Missing required column '{col}' in {path}")
    return dataframe


def load_event_dataframe(path: Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    for col in ("elapsed_ms", "event"):
        if col not in dataframe.columns:
            raise ValueError(f"Missing required column '{col}' in {path}")
    return dataframe


def build_event_frames(raw_run_dir: Path) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for filename in ("dansa.csv", "dekobo.csv"):
        path = raw_run_dir / filename
        if path.exists():
            frames.append(load_event_dataframe(path))
    return frames


def load_weight_kg(raw_run_dir: Path) -> float | None:
    result_path = raw_run_dir / "session_result.csv"
    if not result_path.exists():
        return None
    dataframe = pd.read_csv(result_path)
    if "weight_kg" not in dataframe.columns or dataframe.empty:
        return None
    value = dataframe["weight_kg"].iloc[0]
    return None if pd.isna(value) else float(value)


def add_event_lines(axis, event_frames: list[pd.DataFrame]) -> None:
    labeled: set[str] = set()
    for event_df in event_frames:
        for row in event_df.itertuples(index=False):
            event_name = str(row.event)
            if event_name.endswith("_during"):
                continue
            if event_name not in EVENT_STYLES:
                continue
            color, linestyle, display_label = EVENT_STYLES[event_name]
            event_seconds = float(row.elapsed_ms) / 1000.0
            label = display_label if event_name not in labeled else None
            axis.axvline(
                event_seconds,
                color=color,
                linestyle=linestyle,
                linewidth=1.0,
                alpha=0.8,
                label=label,
            )
            labeled.add(event_name)
    if labeled:
        axis.legend(loc="upper right")


def plot_world_z(
    run_name: str,
    world_df: pd.DataFrame,
    raw_run_dir: Path,
    output_dir: Path,
) -> Path:
    event_frames = build_event_frames(raw_run_dir)
    elapsed_seconds = world_df["elapsed"].to_numpy(dtype=float) / 1000.0

    figure, axis = plt.subplots(figsize=(14, 4), constrained_layout=True)

    axis.plot(elapsed_seconds, world_df["accWorldZ"], linewidth=1.0)
    axis.set_ylabel("world_z [m/s²]")
    axis.set_xlabel("elapsed [s]")
    axis.grid(True, alpha=0.3)

    add_event_lines(axis, event_frames)

    weight_kg = load_weight_kg(raw_run_dir)
    title = (
        f"{run_name} world-z"
        if weight_kg is None
        else f"{run_name} world-z ({weight_kg:g}kg)"
    )
    filename_suffix = "" if weight_kg is None else f"_{weight_kg:g}kg"
    figure.suptitle(title)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_name}{filename_suffix}_world_z_plot.png"
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def iter_world_csv_dirs(world_csv_dir: Path) -> list[tuple[str, Path]]:
    """world_csv_dir/<run_name>/acc_world.csv を列挙する。"""
    results = []
    for subdir in sorted(world_csv_dir.iterdir()):
        if not subdir.is_dir():
            continue
        csv_path = subdir / "acc_world.csv"
        if csv_path.exists():
            results.append((subdir.name, csv_path))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot world-frame Z-axis waveform from acc_world.csv files."
    )
    parser.add_argument(
        "--world-csv-dir",
        required=True,
        help="Directory containing <run_name>/acc_world.csv subdirectories.",
    )
    parser.add_argument(
        "--raw-dir",
        required=True,
        help="Directory containing original run subdirectories (for event CSV files).",
    )
    parser.add_argument(
        "--plot-output-dir",
        required=True,
        help="Directory where plot images will be saved.",
    )
    args = parser.parse_args()

    world_csv_dir = Path(args.world_csv_dir)
    raw_dir = Path(args.raw_dir)
    plot_output_dir = Path(args.plot_output_dir)

    entries = iter_world_csv_dirs(world_csv_dir)
    if not entries:
        raise ValueError(f"No acc_world.csv files found under {world_csv_dir}")

    for run_name, csv_path in entries:
        world_df = load_world_dataframe(csv_path)
        raw_run_dir = raw_dir / run_name
        output_path = plot_world_z(run_name, world_df, raw_run_dir, plot_output_dir)
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
