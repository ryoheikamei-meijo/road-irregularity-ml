from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import load_config

SENSOR_COLUMNS = ["acc_x", "acc_y", "acc_z"]
FEATURE_NAMES = ["mean", "rms", "var", "max", "min"]
REQUIRED_COLUMNS = ["elapsed_ms", *SENSOR_COLUMNS, "label"]


def load_sensor_dataframe(input_path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(input_path)
    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing required columns: {joined}")
    return dataframe


def compute_window_sizes(config: dict[str, Any]) -> tuple[int, int]:
    window_config = config["window"]
    sampling_interval = float(window_config["sampling_interval_seconds"])
    window_seconds = float(window_config["window_seconds"])
    stride_seconds = float(window_config["stride_seconds"])

    if sampling_interval <= 0:
        raise ValueError("sampling_interval_seconds must be positive")

    window_size = int(round(window_seconds / sampling_interval))
    stride_size = int(round(stride_seconds / sampling_interval))

    if window_size <= 0 or stride_size <= 0:
        raise ValueError("window_size and stride_size must be positive")

    return window_size, stride_size


def iter_windows(
    dataframe: pd.DataFrame,
    window_size: int,
    stride_size: int,
):
    for start_index in range(0, len(dataframe) - window_size + 1, stride_size):
        yield start_index, dataframe.iloc[start_index : start_index + window_size]


def assign_window_label(window_df: pd.DataFrame) -> int:
    labels = set(window_df["label"].astype(int).tolist())
    if 1 in labels:
        return 1
    if 2 in labels:
        return 2
    return 0


def compute_window_features(
    window_df: pd.DataFrame,
    *,
    window_id: int,
) -> dict[str, int | float]:
    features: dict[str, int | float] = {
        "window_id": window_id,
        "window_start_ms": int(window_df["elapsed_ms"].iloc[0]),
        "window_end_ms": int(window_df["elapsed_ms"].iloc[-1]),
        "n_samples": int(len(window_df)),
        "label": assign_window_label(window_df),
    }

    for column in SENSOR_COLUMNS:
        values = window_df[column].to_numpy(dtype=float)
        features[f"{column}_mean"] = float(np.mean(values))
        features[f"{column}_rms"] = float(np.sqrt(np.mean(np.square(values))))
        features[f"{column}_var"] = float(np.var(values))
        features[f"{column}_max"] = float(np.max(values))
        features[f"{column}_min"] = float(np.min(values))

    return features


def build_feature_dataframe(
    dataframe: pd.DataFrame,
    *,
    window_size: int,
    stride_size: int,
) -> pd.DataFrame:
    rows = [
        compute_window_features(window_df, window_id=window_id)
        for window_id, (_, window_df) in enumerate(
            iter_windows(dataframe, window_size, stride_size),
        )
    ]
    return pd.DataFrame(rows, columns=build_output_columns())


def build_output_columns() -> list[str]:
    columns = ["window_id", "window_start_ms", "window_end_ms", "n_samples", "label"]
    for sensor_column in SENSOR_COLUMNS:
        for feature_name in FEATURE_NAMES:
            columns.append(f"{sensor_column}_{feature_name}")
    return columns


def build_output_path(input_path: str | Path, features_root_dir: str | Path) -> Path:
    input_file = Path(input_path)
    seed_suffix = extract_seed_suffix(input_file.parent.name)
    output_filename = f"{input_file.stem}_features_{seed_suffix}.csv"
    run_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{seed_suffix}"
    return Path(features_root_dir) / run_id / output_filename


def extract_seed_suffix(run_dir_name: str) -> str:
    if "_seed" in run_dir_name:
        seed_value = run_dir_name.rsplit("_seed", maxsplit=1)[-1]
        return f"seed{seed_value}"
    return "seedunknown"


def save_feature_dataframe(
    dataframe: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, index=False)
    return path


def print_summary(dataframe: pd.DataFrame, output_path: Path) -> None:
    print(f"Saved feature data to: {output_path}")
    print(f"Windows: {len(dataframe)}")
    print(f"Feature columns: {len(build_output_columns()) - 5}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    dataframe = load_sensor_dataframe(args.input)
    window_size, stride_size = compute_window_sizes(config)
    feature_dataframe = build_feature_dataframe(
        dataframe,
        window_size=window_size,
        stride_size=stride_size,
    )
    output_path = build_output_path(args.input, config["data"]["features_dir"])
    saved_path = save_feature_dataframe(feature_dataframe, output_path)
    print_summary(feature_dataframe, saved_path)


if __name__ == "__main__":
    main()
