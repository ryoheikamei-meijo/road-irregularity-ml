from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.config import load_config
from src.scripts.generate_mock_data import (
    build_mock_dataframe,
    build_output_path,
    count_label_runs,
    generate_gyroscope_axes,
    save_mock_dataframe,
)


def test_build_mock_dataframe_without_gyro_has_expected_columns() -> None:
    config = load_config("configs/mock_data_acc_only.yaml")

    dataframe = build_mock_dataframe(config)

    assert list(dataframe.columns) == [
        "timestamp",
        "elapsed_ms",
        "acc_x",
        "acc_y",
        "acc_z",
        "label",
    ]
    assert sorted(dataframe["label"].unique().tolist()) == [0, 1, 2]
    assert dataframe["elapsed_ms"].diff().dropna().eq(250).all()


def test_build_mock_dataframe_with_gyro_has_expected_columns() -> None:
    config = load_config("configs/mock_data_with_gyro.yaml")

    dataframe = build_mock_dataframe(config)

    assert list(dataframe.columns) == [
        "timestamp",
        "elapsed_ms",
        "acc_x",
        "acc_y",
        "acc_z",
        "label",
        "gyro_x",
        "gyro_y",
        "gyro_z",
    ]
    assert sorted(dataframe["label"].unique().tolist()) == [0, 1, 2]
    assert len(dataframe) == 960
    assert count_label_runs(dataframe["label"].to_numpy()) > 3


def test_build_mock_dataframe_is_reproducible() -> None:
    config = load_config("configs/mock_data_with_gyro.yaml")

    left = build_mock_dataframe(config)
    right = build_mock_dataframe(config)

    pd.testing.assert_frame_equal(left, right)


def test_build_mock_dataframe_is_not_fixed_label_order() -> None:
    config = load_config("configs/mock_data_with_gyro.yaml")

    dataframe = build_mock_dataframe(config)
    run_labels = dataframe.loc[
        dataframe["label"].ne(dataframe["label"].shift()),
        "label",
    ].tolist()

    assert run_labels[:6] != [0, 1, 2, 0, 1, 2]


def test_save_mock_dataframe_creates_csv(tmp_path: Path) -> None:
    config = load_config("configs/mock_data_acc_only.yaml")
    config["mock_data"]["output_root_dir"] = str(tmp_path)
    config["mock_data"]["output_filename"] = "mock.csv"
    dataframe = build_mock_dataframe(config)

    output_path = save_mock_dataframe(
        dataframe,
        tmp_path / "20260513112233" / config["mock_data"]["output_filename"],
    )

    assert output_path.exists()
    loaded = pd.read_csv(output_path)
    assert len(loaded) == len(dataframe)


def test_build_output_path_uses_timestamp_directory(tmp_path: Path) -> None:
    config = load_config("configs/mock_data_acc_only.yaml")
    config["mock_data"]["output_root_dir"] = str(tmp_path)
    config["mock_data"]["output_filename"] = "mock.csv"

    with patch("src.scripts.generate_mock_data.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "20260513112233"
        output_path = build_output_path(config)

    assert output_path == tmp_path / "20260513112233" / "mock.csv"


def test_generate_gyroscope_axes_allows_single_sample_segment() -> None:
    gyro_x, gyro_y, gyro_z = generate_gyroscope_axes(
        label=1,
        time_axis=np.array([0.0]),
        acc_x=np.array([0.5]),
        acc_y=np.array([0.1]),
        acc_z=np.array([1.2]),
        noise_std=0.03,
        rng=np.random.default_rng(42),
    )

    assert len(gyro_x) == 1
    assert len(gyro_y) == 1
    assert len(gyro_z) == 1
