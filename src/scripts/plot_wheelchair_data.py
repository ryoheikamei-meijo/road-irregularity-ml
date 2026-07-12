from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ACC_COLUMNS = ["accX", "accY", "accZ"]
EVENT_STYLES = {
    "dansa_start": ("tab:red", "--"),
    "dansa_stop": ("tab:red", "-"),
    "dekobo_start": ("tab:orange", "--"),
    "dekobo_stop": ("tab:orange", "-"),
}


def load_acc_dataframe(path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    required_columns = ["elapsed", *ACC_COLUMNS]
    missing_columns = [
        column for column in required_columns if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing required columns in acc.csv: {joined}")
    return dataframe


def load_event_dataframe(path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    required_columns = ["elapsed_ms", "event"]
    missing_columns = [
        column for column in required_columns if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing required columns in event csv: {joined}")
    return dataframe


def build_event_frames(run_dir: Path) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for filename in ["dansa.csv", "dekobo.csv"]:
        path = run_dir / filename
        if not path.exists():
            continue
        frames.append(load_event_dataframe(path))
    return frames


def load_weight_kg(run_dir: Path) -> float | None:
    result_path = run_dir / "session_result.csv"
    if not result_path.exists():
        return None
    dataframe = pd.read_csv(result_path)
    if "weight_kg" not in dataframe.columns or dataframe.empty:
        return None
    value = dataframe["weight_kg"].iloc[0]
    return None if pd.isna(value) else float(value)


def compute_acc_magnitude(dataframe: pd.DataFrame) -> np.ndarray:
    values = dataframe[ACC_COLUMNS].to_numpy(dtype=float)
    return np.linalg.norm(values, axis=1)


def plot_run(run_dir: Path, output_dir: Path) -> Path:
    acc_path = run_dir / "acc.csv"
    acc_df = load_acc_dataframe(acc_path)
    event_frames = build_event_frames(run_dir)
    elapsed_seconds = acc_df["elapsed"].to_numpy(dtype=float) / 1000.0

    figure, axes = plt.subplots(
        nrows=4,
        ncols=1,
        figsize=(14, 10),
        sharex=True,
        constrained_layout=True,
    )

    for axis, column in zip(axes[:3], ACC_COLUMNS, strict=True):
        axis.plot(elapsed_seconds, acc_df[column], linewidth=1.0)
        axis.set_ylabel(column)
        axis.grid(True, alpha=0.3)

    axes[3].plot(
        elapsed_seconds,
        compute_acc_magnitude(acc_df),
        color="black",
        linewidth=1.0,
    )
    axes[3].set_ylabel("|a|")
    axes[3].set_xlabel("elapsed [s]")
    axes[3].grid(True, alpha=0.3)

    labeled_events: set[str] = set()
    for event_df in event_frames:
        for row in event_df.itertuples(index=False):
            event_name = str(row.event)
            if event_name.endswith("_during"):
                continue
            color, linestyle = EVENT_STYLES.get(event_name, ("gray", ":"))
            event_seconds = float(row.elapsed_ms) / 1000.0
            label = event_name if event_name not in labeled_events else None
            for axis in axes:
                axis.axvline(
                    event_seconds,
                    color=color,
                    linestyle=linestyle,
                    linewidth=1.0,
                    alpha=0.8,
                    label=label,
                )
            labeled_events.add(event_name)

    if labeled_events:
        axes[0].legend(loc="upper right")

    weight_kg = load_weight_kg(run_dir)
    title = run_dir.name if weight_kg is None else f"{run_dir.name} ({weight_kg:g}kg)"
    filename_suffix = "" if weight_kg is None else f"_{weight_kg:g}kg"
    figure.suptitle(title)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_dir.name}{filename_suffix}_acc_plot.png"
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def iter_run_dirs(input_dir: str | Path) -> list[Path]:
    input_path = Path(input_dir)
    if (input_path / "acc.csv").exists():
        return [input_path]
    return sorted(path for path in input_path.iterdir() if path.is_dir())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    run_dirs = iter_run_dirs(args.input_dir)
    if not run_dirs:
        raise ValueError("No run directories found")

    for run_dir in run_dirs:
        if not (run_dir / "acc.csv").exists():
            continue
        output_path = plot_run(run_dir, Path(args.output_dir))
        print(f"Saved plot to: {output_path}")


if __name__ == "__main__":
    main()
