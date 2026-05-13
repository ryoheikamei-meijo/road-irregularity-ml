from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import load_config

LABEL_FLAT = 0
LABEL_BUMP = 1
LABEL_ROUGH = 2


def build_mock_dataframe(config: dict[str, Any]) -> pd.DataFrame:
    mock_config = config["mock_data"]
    sampling_interval = float(mock_config["sampling_interval_seconds"])
    total_duration_seconds = float(mock_config["total_duration_seconds"])
    include_gyro = bool(mock_config["include_gyro"])
    random_state = int(mock_config.get("random_state", 42))
    noise_std = float(mock_config.get("noise_std", 0.03))
    rng = np.random.default_rng(random_state)

    segments: list[pd.DataFrame] = []
    elapsed_ms_offset = 0
    base_timestamp = pd.Timestamp("2026-01-01T00:00:00")
    label_sequence = generate_label_sequence(
        total_duration_seconds=total_duration_seconds,
        sampling_interval=sampling_interval,
        label_duration_seconds=mock_config["label_duration_seconds"],
        label_weights=mock_config.get("label_weights"),
        rng=rng,
    )

    for label, samples_per_segment in label_sequence:
        segment = generate_label_segment(
            label=label,
            samples_per_segment=samples_per_segment,
            sampling_interval=sampling_interval,
            elapsed_ms_offset=elapsed_ms_offset,
            base_timestamp=base_timestamp,
            noise_std=noise_std,
            include_gyro=include_gyro,
            rng=rng,
        )
        segments.append(segment)
        elapsed_ms_offset = int(
            segment["elapsed_ms"].iloc[-1] + sampling_interval * 1000,
        )

    return pd.concat(segments, ignore_index=True)


def generate_label_sequence(
    *,
    total_duration_seconds: float,
    sampling_interval: float,
    label_duration_seconds: dict[str, dict[str, float]],
    label_weights: dict[str, float] | None,
    rng: np.random.Generator,
) -> list[tuple[int, int]]:
    total_samples = max(1, int(round(total_duration_seconds / sampling_interval)))
    weights = normalize_label_weights(label_weights)

    segments: list[tuple[int, int]] = []
    remaining_samples = total_samples
    previous_label: int | None = None

    while remaining_samples > 0:
        label = choose_next_label(
            weights=weights,
            previous_label=previous_label,
            rng=rng,
        )
        duration_range = label_duration_seconds[str(label)]
        min_samples = max(
            1,
            int(round(float(duration_range["min"]) / sampling_interval)),
        )
        max_samples = max(
            min_samples,
            int(round(float(duration_range["max"]) / sampling_interval)),
        )
        samples = int(rng.integers(min_samples, max_samples + 1))
        samples = min(samples, remaining_samples)

        if segments and segments[-1][0] == label:
            previous_samples = segments[-1][1]
            segments[-1] = (label, previous_samples + samples)
        else:
            segments.append((label, samples))

        remaining_samples -= samples
        previous_label = label

    return segments


def normalize_label_weights(label_weights: dict[str, float] | None) -> dict[int, float]:
    if label_weights is None:
        weights = {
            LABEL_FLAT: 0.55,
            LABEL_BUMP: 0.15,
            LABEL_ROUGH: 0.30,
        }
    else:
        weights = {int(label): float(weight) for label, weight in label_weights.items()}

    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("label_weights must sum to a positive value")

    return {label: weight / total_weight for label, weight in weights.items()}


def choose_next_label(
    *,
    weights: dict[int, float],
    previous_label: int | None,
    rng: np.random.Generator,
) -> int:
    labels = sorted(weights)
    probabilities = np.array([weights[label] for label in labels], dtype=float)

    if previous_label is not None and len(labels) > 1:
        previous_index = labels.index(previous_label)
        probabilities[previous_index] *= 0.35
        probabilities /= probabilities.sum()

    return int(rng.choice(labels, p=probabilities))


def generate_label_segment(
    *,
    label: int,
    samples_per_segment: int,
    sampling_interval: float,
    elapsed_ms_offset: int,
    base_timestamp: pd.Timestamp,
    noise_std: float,
    include_gyro: bool,
    rng: np.random.Generator,
) -> pd.DataFrame:
    time_axis = np.arange(samples_per_segment, dtype=float) * sampling_interval
    elapsed_ms = elapsed_ms_offset + (time_axis * 1000).astype(int)
    timestamps = base_timestamp + pd.to_timedelta(elapsed_ms, unit="ms")

    acc_x, acc_y, acc_z = generate_accelerometer_axes(
        label=label,
        time_axis=time_axis,
        noise_std=noise_std,
        rng=rng,
    )

    data: dict[str, Any] = {
        "timestamp": timestamps.astype(str),
        "elapsed_ms": elapsed_ms,
        "acc_x": acc_x,
        "acc_y": acc_y,
        "acc_z": acc_z,
        "label": np.full(samples_per_segment, label, dtype=int),
    }

    if include_gyro:
        gyro_x, gyro_y, gyro_z = generate_gyroscope_axes(
            label=label,
            time_axis=time_axis,
            acc_x=acc_x,
            acc_y=acc_y,
            acc_z=acc_z,
            noise_std=noise_std,
            rng=rng,
        )
        data["gyro_x"] = gyro_x
        data["gyro_y"] = gyro_y
        data["gyro_z"] = gyro_z

    return pd.DataFrame(data)


def generate_accelerometer_axes(
    *,
    label: int,
    time_axis: np.ndarray,
    noise_std: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if label == LABEL_FLAT:
        acc_x = 0.03 * np.sin(2 * np.pi * 0.35 * time_axis)
        acc_y = 0.02 * np.sin(2 * np.pi * 0.20 * time_axis + 0.4)
        acc_z = 1.00 + 0.04 * np.sin(2 * np.pi * 0.45 * time_axis + 0.8)
    elif label == LABEL_BUMP:
        center = time_axis[len(time_axis) // 2]
        spike = np.exp(-((time_axis - center) ** 2) / 0.01)
        rebound = np.exp(-((time_axis - (center + 0.25)) ** 2) / 0.03)
        acc_x = 0.10 * np.sin(2 * np.pi * 0.60 * time_axis) + 0.90 * spike
        acc_y = 0.08 * np.sin(2 * np.pi * 0.50 * time_axis + 0.3) - 0.35 * rebound
        acc_z = 1.00 + 1.40 * spike - 0.45 * rebound
    elif label == LABEL_ROUGH:
        acc_x = 0.18 * np.sin(2 * np.pi * 2.40 * time_axis) + 0.09 * np.sin(
            2 * np.pi * 4.80 * time_axis + 0.2,
        )
        acc_y = 0.16 * np.sin(2 * np.pi * 2.10 * time_axis + 0.7) + 0.08 * np.sin(
            2 * np.pi * 5.10 * time_axis,
        )
        acc_z = (
            1.00
            + 0.22 * np.sin(2 * np.pi * 2.80 * time_axis + 0.5)
            + 0.10 * np.sin(2 * np.pi * 6.00 * time_axis)
        )
    else:
        raise ValueError(f"Unsupported label: {label}")

    noise = rng.normal(0.0, noise_std, size=(3, len(time_axis)))
    return acc_x + noise[0], acc_y + noise[1], acc_z + noise[2]


def generate_gyroscope_axes(
    *,
    label: int,
    time_axis: np.ndarray,
    acc_x: np.ndarray,
    acc_y: np.ndarray,
    acc_z: np.ndarray,
    noise_std: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    gradient_scale = (
        max(time_axis[1] - time_axis[0], 1e-6) if len(time_axis) > 1 else 1.0
    )
    acc_dx = np.gradient(acc_x, gradient_scale)
    acc_dy = np.gradient(acc_y, gradient_scale)
    acc_dz = np.gradient(acc_z, gradient_scale)

    if label == LABEL_FLAT:
        base_x = 0.02 * np.sin(2 * np.pi * 0.25 * time_axis)
        base_y = 0.015 * np.sin(2 * np.pi * 0.30 * time_axis + 0.4)
        base_z = 0.01 * np.sin(2 * np.pi * 0.20 * time_axis + 0.9)
    elif label == LABEL_BUMP:
        base_x = 0.10 * acc_dx
        base_y = 0.08 * acc_dy
        base_z = 0.12 * acc_dz
    elif label == LABEL_ROUGH:
        base_x = 0.07 * acc_dx + 0.03 * np.sin(2 * np.pi * 3.00 * time_axis)
        base_y = 0.07 * acc_dy + 0.03 * np.sin(2 * np.pi * 3.20 * time_axis + 0.2)
        base_z = 0.07 * acc_dz + 0.02 * np.sin(2 * np.pi * 2.80 * time_axis + 0.5)
    else:
        raise ValueError(f"Unsupported label: {label}")

    noise = rng.normal(0.0, noise_std * 0.5, size=(3, len(time_axis)))
    return base_x + noise[0], base_y + noise[1], base_z + noise[2]


def save_mock_dataframe(dataframe: pd.DataFrame, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, index=False)
    return path


def build_output_path(config: dict[str, Any]) -> Path:
    mock_config = config["mock_data"]
    output_root_dir = Path(mock_config["output_root_dir"])
    output_filename = mock_config["output_filename"]
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    return output_root_dir / run_id / output_filename


def print_summary(
    dataframe: pd.DataFrame,
    output_path: Path,
    include_gyro: bool,
) -> None:
    print(f"Saved mock data to: {output_path}")
    print(f"Rows: {len(dataframe)}")
    print(f"Gyro included: {include_gyro}")
    print("Label counts:")
    for label, count in dataframe["label"].value_counts().sort_index().items():
        print(f"  {label}: {count}")
    print(f"Label runs: {count_label_runs(dataframe['label'].to_numpy())}")


def count_label_runs(labels: np.ndarray) -> int:
    if len(labels) == 0:
        return 0
    return int(np.count_nonzero(labels[1:] != labels[:-1]) + 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    dataframe = build_mock_dataframe(config)
    output_path = save_mock_dataframe(dataframe, build_output_path(config))
    print_summary(
        dataframe=dataframe,
        output_path=output_path,
        include_gyro=bool(config["mock_data"]["include_gyro"]),
    )


if __name__ == "__main__":
    main()
