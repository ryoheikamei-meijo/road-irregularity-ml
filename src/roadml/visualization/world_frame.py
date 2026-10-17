"""World-frame transformation and waveform plotting."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

EVENT_STYLES = {
    "dansa_start": ("tab:red", "--"),
    "dansa_stop": ("tab:red", "-"),
    "dekobo_start": ("tab:orange", "--"),
    "dekobo_stop": ("tab:orange", "-"),
}


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


def save_transformed_dataframe(dataframe: pd.DataFrame, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False)
    return output_path


def add_event_lines(
    axes,
    event_frames: list[pd.DataFrame],
) -> None:
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


def plot_world_run(run_dir: Path, output_dir: Path, transformed_df: pd.DataFrame) -> Path:
    event_frames = build_event_frames(run_dir)
    elapsed_seconds = transformed_df["elapsed"].to_numpy(dtype=float) / 1000.0

    figure, axes = plt.subplots(
        nrows=4,
        ncols=1,
        figsize=(14, 10),
        sharex=True,
        constrained_layout=True,
    )

    series = [
        ("accWorldX", "world_x"),
        ("accWorldY", "world_y"),
        ("accWorldZ", "world_z"),
        ("accWorldMag", "|a|"),
    ]
    for axis, (column, label) in zip(axes, series, strict=True):
        axis.plot(elapsed_seconds, transformed_df[column], linewidth=1.0)
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)

    axes[-1].set_xlabel("elapsed [s]")
    add_event_lines(axes, event_frames)

    weight_kg = load_weight_kg(run_dir)
    title = (
        f"{run_dir.name} world-frame"
        if weight_kg is None
        else f"{run_dir.name} world-frame ({weight_kg:g}kg)"
    )
    filename_suffix = "" if weight_kg is None else f"_{weight_kg:g}kg"
    figure.suptitle(title)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_dir.name}{filename_suffix}_world_plot.png"
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def iter_run_dirs(input_dir: str | Path) -> list[Path]:
    input_path = Path(input_dir)
    if (input_path / "acc.csv").exists():
        return [input_path]
    return sorted(path for path in input_path.iterdir() if path.is_dir())
