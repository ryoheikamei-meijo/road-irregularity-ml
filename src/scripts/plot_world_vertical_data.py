from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

ACC_COLUMNS = ["accX", "accY", "accZ"]
ROTATION_COLUMNS = ["rotX", "rotY", "rotZ", "rotW"]
GRAVITY_MPS2 = 9.80665
EVENT_STYLES = {
    "dansa_start": ("tab:red", "--"),
    "dansa_stop": ("tab:red", "-"),
    "dekobo_start": ("tab:orange", "--"),
    "dekobo_stop": ("tab:orange", "-"),
}


def load_acc_dataframe(path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    required_columns = ["elapsed", *ACC_COLUMNS, *ROTATION_COLUMNS]
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


def transform_to_world_frame(acc_df: pd.DataFrame) -> pd.DataFrame:
    acc_values = acc_df[ACC_COLUMNS].to_numpy(dtype=float)
    quaternions = acc_df[ROTATION_COLUMNS].to_numpy(dtype=float)
    rotations = Rotation.from_quat(quaternions)

    # Android の rotation vector は端末座標 -> 実空間座標の回転として扱う。
    world_values = rotations.apply(acc_values)

    world_df = acc_df.copy()
    world_df["accWorldX"] = world_values[:, 0]
    world_df["accWorldY"] = world_values[:, 1]
    world_df["accWorldZ"] = world_values[:, 2]
    world_df["accWorldMag"] = np.linalg.norm(world_values, axis=1)
    return world_df


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--csv-output-dir", required=True)
    parser.add_argument("--plot-output-dir", required=True)
    args = parser.parse_args()

    run_dirs = iter_run_dirs(args.input_dir)
    if not run_dirs:
        raise ValueError("No run directories found")

    for run_dir in run_dirs:
        acc_path = run_dir / "acc.csv"
        if not acc_path.exists():
            continue
        acc_df = load_acc_dataframe(acc_path)
        transformed_df = transform_to_world_frame(acc_df)
        csv_output_path = Path(args.csv_output_dir) / run_dir.name / "acc_world.csv"
        plot_output_path = plot_world_run(
            run_dir,
            Path(args.plot_output_dir),
            transformed_df,
        )
        saved_csv_path = save_transformed_dataframe(transformed_df, csv_output_path)
        print(f"Saved transformed csv to: {saved_csv_path}")
        print(f"Saved plot to: {plot_output_path}")


if __name__ == "__main__":
    main()
