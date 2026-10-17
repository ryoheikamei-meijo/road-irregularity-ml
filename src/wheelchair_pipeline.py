from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

GRAVITY_MPS2 = 9.80665
WORLD_X_COLUMN = "accWorldX"
WORLD_Y_COLUMN = "accWorldY"
WORLD_Z_COLUMN = "accWorldZ"
WORLD_MAG_COLUMN = "accWorldMag"
WORLD_X_LINEAR_COLUMN = "world_x_linear"
WORLD_Y_LINEAR_COLUMN = "world_y_linear"
WORLD_Z_LINEAR_COLUMN = "world_z_linear"
WORLD_MAG_LINEAR_COLUMN = "world_mag_linear"
AXIS_LINEAR_COLUMNS = {
    "x": WORLD_X_LINEAR_COLUMN,
    "y": WORLD_Y_LINEAR_COLUMN,
    "z": WORLD_Z_LINEAR_COLUMN,
    "mag": WORLD_MAG_LINEAR_COLUMN,
}
DEFAULT_LABEL_ORDER = ["flat", "dansa", "dekobo"]
EVENT_FILE_SPECS = {
    "dansa": ("dansa.csv", "dansa_start", "dansa_stop"),
    "dekobo": ("dekobo.csv", "dekobo_start", "dekobo_stop"),
}
WORLD_REQUIRED_COLUMNS = ["elapsed", WORLD_Z_COLUMN]
EVENT_REQUIRED_COLUMNS = ["elapsed_ms", "event"]
DATASET_COLUMNS = [
    "run_id",
    "window_id",
    "start_ms",
    "end_ms",
    "label",
    "z_range",
    "z_diff_max",
    "z_rms",
    "z_std",
]

Interval = tuple[float, float]


@dataclass(frozen=True)
class WindowConfig:
    window_size: int
    stride_size: int
    window_duration_ms: float


def load_world_dataframe(path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    missing_columns = [
        column for column in WORLD_REQUIRED_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing required columns in acc_world.csv: {joined}")

    world_df = dataframe.copy()
    world_df[WORLD_Z_LINEAR_COLUMN] = (
        world_df[WORLD_Z_COLUMN].astype(float) - GRAVITY_MPS2
    )
    # x/y は水平方向のため重力補正は不要で、world 座標系の値をそのまま使う。
    if WORLD_X_COLUMN in world_df.columns:
        world_df[WORLD_X_LINEAR_COLUMN] = world_df[WORLD_X_COLUMN].astype(float)
    if WORLD_Y_COLUMN in world_df.columns:
        world_df[WORLD_Y_LINEAR_COLUMN] = world_df[WORLD_Y_COLUMN].astype(float)
    # 合成加速度（|a|）は静止時でも重力分だけ約9.8で下駄を履くため、z軸と同様に
    # 重力分を引いて「動的な合成加速度」として扱う。
    if WORLD_MAG_COLUMN in world_df.columns:
        world_df[WORLD_MAG_LINEAR_COLUMN] = (
            world_df[WORLD_MAG_COLUMN].astype(float) - GRAVITY_MPS2
        )
    return world_df


def load_event_dataframe(path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    missing_columns = [
        column for column in EVENT_REQUIRED_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing required columns in event CSV: {joined}")
    return dataframe


def compute_window_config(config: dict[str, Any]) -> WindowConfig:
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

    return WindowConfig(
        window_size=window_size,
        stride_size=stride_size,
        window_duration_ms=window_seconds * 1000.0,
    )


def iter_windows(
    dataframe: pd.DataFrame,
    *,
    window_size: int,
    stride_size: int,
):
    for start_index in range(0, len(dataframe) - window_size + 1, stride_size):
        yield start_index, dataframe.iloc[start_index : start_index + window_size]


def build_event_intervals(
    event_df: pd.DataFrame,
    *,
    start_event: str,
    stop_event: str,
    pre_event_extension_ms: float = 0.0,
) -> list[Interval]:
    filtered = event_df[event_df["event"].isin([start_event, stop_event])].copy()
    filtered = filtered.sort_values("elapsed_ms")

    intervals: list[Interval] = []
    open_start: float | None = None

    for row in filtered.itertuples(index=False):
        event_name = str(row.event)
        elapsed_ms = float(row.elapsed_ms)

        if event_name == start_event:
            if open_start is not None:
                raise ValueError(
                    f"Found nested {start_event} before closing the previous interval"
                )
            open_start = elapsed_ms
            continue

        if open_start is None:
            raise ValueError(f"Found {stop_event} without a matching {start_event}")
        if elapsed_ms <= open_start:
            raise ValueError(f"Invalid interval: {stop_event} <= {start_event}")

        extended_start = max(0.0, open_start - pre_event_extension_ms)
        intervals.append((extended_start, elapsed_ms))
        open_start = None

    if open_start is not None:
        raise ValueError(f"Missing {stop_event} for {start_event}")

    return intervals


def load_run_intervals(run_dir: str | Path) -> dict[str, list[Interval]]:
    run_path = Path(run_dir)
    intervals: dict[str, list[Interval]] = {}

    for label, (filename, start_event, stop_event) in EVENT_FILE_SPECS.items():
        event_path = run_path / filename
        if not event_path.exists():
            intervals[label] = []
            continue
        event_df = load_event_dataframe(event_path)
        intervals[label] = build_event_intervals(
            event_df,
            start_event=start_event,
            stop_event=stop_event,
        )

    return intervals


def load_run_intervals_from_config(
    run_dir: str | Path,
    config: dict[str, Any],
) -> dict[str, list[Interval]]:
    run_path = Path(run_dir)
    intervals: dict[str, list[Interval]] = {}
    pre_event_extension_ms = (
        float(config["label"].get("pre_event_extension_seconds", 0.0)) * 1000.0
    )

    for label, (filename, start_event, stop_event) in EVENT_FILE_SPECS.items():
        event_path = run_path / filename
        if not event_path.exists():
            intervals[label] = []
            continue
        event_df = load_event_dataframe(event_path)
        intervals[label] = build_event_intervals(
            event_df,
            start_event=start_event,
            stop_event=stop_event,
            pre_event_extension_ms=pre_event_extension_ms,
        )

    return intervals


def compute_overlap_ratio(
    *,
    window_start_ms: float,
    window_end_ms: float,
    intervals: list[Interval],
) -> float:
    window_duration = window_end_ms - window_start_ms
    if window_duration <= 0:
        raise ValueError("window_end_ms must be greater than window_start_ms")

    overlap_ms = 0.0
    for interval_start, interval_end in intervals:
        overlap_ms += max(
            0.0,
            min(window_end_ms, interval_end) - max(window_start_ms, interval_start),
        )

    return overlap_ms / window_duration


def assign_window_label(
    *,
    window_start_ms: float,
    window_end_ms: float,
    intervals_by_label: dict[str, list[Interval]],
    overlap_threshold: float,
) -> str:
    dansa_ratio = compute_overlap_ratio(
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        intervals=intervals_by_label["dansa"],
    )
    if dansa_ratio >= overlap_threshold:
        return "dansa"

    dekobo_ratio = compute_overlap_ratio(
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        intervals=intervals_by_label["dekobo"],
    )
    if dekobo_ratio >= overlap_threshold:
        return "dekobo"

    return "flat"


def compute_axis_window_features(
    values: np.ndarray,
    *,
    prefix: str,
    timestamps_ms: np.ndarray | None = None,
) -> dict[str, float]:
    if len(values) == 0:
        raise ValueError("Cannot compute features for an empty window")

    diffs = np.diff(values)
    features = {
        f"{prefix}_range": float(np.max(values) - np.min(values)),
        f"{prefix}_diff_max": float(np.max(diffs) if len(diffs) > 0 else 0.0),
        f"{prefix}_rms": float(np.sqrt(np.mean(np.square(values)))),
        f"{prefix}_std": float(np.std(values)),
    }

    if timestamps_ms is None:
        return features

    # ジャーク（加加速度）= 加速度の時間微分。サンプル間隔が不均一な場合に備え、
    # 実際のタイムスタンプ差分から dt を求めて割る。
    dt_seconds = np.diff(timestamps_ms) / 1000.0
    jerk = np.divide(
        diffs,
        dt_seconds,
        out=np.zeros_like(diffs),
        where=dt_seconds > 0,
    )
    features.update(
        {
            f"{prefix}_jerk_max": float(np.max(np.abs(jerk)) if len(jerk) > 0 else 0.0),
            f"{prefix}_jerk_rms": float(
                np.sqrt(np.mean(np.square(jerk))) if len(jerk) > 0 else 0.0
            ),
            f"{prefix}_jerk_std": float(np.std(jerk) if len(jerk) > 0 else 0.0),
        }
    )
    return features


def compute_window_features(values: np.ndarray) -> dict[str, float]:
    return compute_axis_window_features(values, prefix="z")


def build_run_feature_dataframe(
    *,
    run_id: str,
    world_csv_path: str | Path,
    run_dir: str | Path,
    config: dict[str, Any],
) -> pd.DataFrame:
    world_df = load_world_dataframe(world_csv_path)
    intervals_by_label = load_run_intervals_from_config(run_dir, config)
    window_config = compute_window_config(config)
    overlap_threshold = float(config["label"]["overlap_threshold"])

    rows: list[dict[str, str | int | float]] = []
    for window_id, (_, window_df) in enumerate(
        iter_windows(
            world_df,
            window_size=window_config.window_size,
            stride_size=window_config.stride_size,
        )
    ):
        window_start_ms = float(window_df["elapsed"].iloc[0])
        window_end_ms = window_start_ms + window_config.window_duration_ms
        label = assign_window_label(
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            intervals_by_label=intervals_by_label,
            overlap_threshold=overlap_threshold,
        )
        features = compute_window_features(
            window_df[WORLD_Z_LINEAR_COLUMN].to_numpy(dtype=float)
        )
        rows.append(
            {
                "run_id": run_id,
                "window_id": window_id,
                "start_ms": int(round(window_start_ms)),
                "end_ms": int(round(window_end_ms)),
                "label": label,
                **features,
            }
        )

    return pd.DataFrame(rows, columns=DATASET_COLUMNS)


def build_multi_axis_run_feature_dataframe(
    *,
    run_id: str,
    world_csv_path: str | Path,
    run_dir: str | Path,
    config: dict[str, Any],
    axes: tuple[str, ...] = ("x", "y", "z"),
) -> pd.DataFrame:
    """world_x_linear / world_y_linear / world_z_linear の各軸で特徴量を計算する。

    可視化・分析用の拡張版で、学習パイプラインが使う `build_run_feature_dataframe`
    （z軸4特徴量固定）は変更せず別関数として提供する。
    """
    world_df = load_world_dataframe(world_csv_path)
    intervals_by_label = load_run_intervals_from_config(run_dir, config)
    window_config = compute_window_config(config)
    overlap_threshold = float(config["label"]["overlap_threshold"])

    rows: list[dict[str, str | int | float]] = []
    for window_id, (_, window_df) in enumerate(
        iter_windows(
            world_df,
            window_size=window_config.window_size,
            stride_size=window_config.stride_size,
        )
    ):
        window_start_ms = float(window_df["elapsed"].iloc[0])
        window_end_ms = window_start_ms + window_config.window_duration_ms
        label = assign_window_label(
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            intervals_by_label=intervals_by_label,
            overlap_threshold=overlap_threshold,
        )
        timestamps_ms = window_df["elapsed"].to_numpy(dtype=float)
        features: dict[str, float] = {}
        for axis in axes:
            column = AXIS_LINEAR_COLUMNS[axis]
            features.update(
                compute_axis_window_features(
                    window_df[column].to_numpy(dtype=float),
                    prefix=axis,
                    timestamps_ms=timestamps_ms,
                )
            )
        rows.append(
            {
                "run_id": run_id,
                "window_id": window_id,
                "start_ms": int(round(window_start_ms)),
                "end_ms": int(round(window_end_ms)),
                "label": label,
                **features,
            }
        )

    return pd.DataFrame(rows)


def resolve_run_ids(
    *,
    world_csv_root_dir: str | Path,
    requested_run_ids: list[str] | None = None,
) -> list[str]:
    root_path = Path(world_csv_root_dir)
    available_run_ids = sorted(
        path.name for path in root_path.iterdir() if path.is_dir()
    )
    if requested_run_ids is None:
        return available_run_ids

    missing_run_ids = sorted(set(requested_run_ids) - set(available_run_ids))
    if missing_run_ids:
        joined = ", ".join(missing_run_ids)
        raise ValueError(f"Unknown run_id in world_csv_dir: {joined}")
    return requested_run_ids


def build_dataset_dataframe(
    *,
    config: dict[str, Any],
    run_ids: list[str] | None = None,
) -> pd.DataFrame:
    world_csv_root_dir = Path(config["data"]["world_csv_dir"])
    run_root_dir = Path(config["data"]["root_run_dir"])
    resolved_run_ids = resolve_run_ids(
        world_csv_root_dir=world_csv_root_dir,
        requested_run_ids=run_ids,
    )

    frames: list[pd.DataFrame] = []
    for run_id in resolved_run_ids:
        world_csv_path = world_csv_root_dir / run_id / "acc_world.csv"
        run_dir = run_root_dir / run_id
        if not world_csv_path.exists():
            raise ValueError(f"Missing acc_world.csv for run_id={run_id}")
        if not run_dir.exists():
            raise ValueError(f"Missing raw run directory for run_id={run_id}")

        frame = build_run_feature_dataframe(
            run_id=run_id,
            world_csv_path=world_csv_path,
            run_dir=run_dir,
            config=config,
        )
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=DATASET_COLUMNS)

    return pd.concat(frames, ignore_index=True)


def build_multi_axis_dataset_dataframe(
    *,
    config: dict[str, Any],
    run_ids: list[str] | None = None,
    axes: tuple[str, ...] = ("x", "y", "z"),
) -> pd.DataFrame:
    """`build_dataset_dataframe` のx/y/z全軸版。学習パイプラインの出力形式は変えない。"""
    world_csv_root_dir = Path(config["data"]["world_csv_dir"])
    run_root_dir = Path(config["data"]["root_run_dir"])
    resolved_run_ids = resolve_run_ids(
        world_csv_root_dir=world_csv_root_dir,
        requested_run_ids=run_ids,
    )

    frames: list[pd.DataFrame] = []
    for run_id in resolved_run_ids:
        world_csv_path = world_csv_root_dir / run_id / "acc_world.csv"
        run_dir = run_root_dir / run_id
        if not world_csv_path.exists():
            raise ValueError(f"Missing acc_world.csv for run_id={run_id}")
        if not run_dir.exists():
            raise ValueError(f"Missing raw run directory for run_id={run_id}")

        frame = build_multi_axis_run_feature_dataframe(
            run_id=run_id,
            world_csv_path=world_csv_path,
            run_dir=run_dir,
            config=config,
            axes=axes,
        )
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def build_dataset_output_path(config: dict[str, Any]) -> Path:
    features_root_dir = Path(config["data"]["features_dir"])
    output_filename = config["data"].get(
        "dataset_filename",
        "wheelchair_world_z_dataset.csv",
    )
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    return features_root_dir / run_id / output_filename


def build_processed_output_dir(config: dict[str, Any]) -> Path:
    processed_root_dir = Path(config["data"]["processed_dir"])
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir = processed_root_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_dataset_dataframe(
    dataframe: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, index=False)
    return path
