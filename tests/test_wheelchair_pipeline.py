from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.config import load_config
from src.scripts.train_wheelchair_model import main as train_wheelchair_model_main
from src.wheelchair_pipeline import GRAVITY_MPS2
from src.wheelchair_pipeline import assign_window_label
from src.wheelchair_pipeline import build_dataset_dataframe
from src.wheelchair_pipeline import build_event_intervals
from src.wheelchair_pipeline import compute_window_features
from src.wheelchair_pipeline import load_world_dataframe


def test_load_world_dataframe_adds_world_z_linear(tmp_path: Path) -> None:
    input_path = tmp_path / "acc_world.csv"
    pd.DataFrame(
        {
            "elapsed": [0.0, 250.0],
            "accWorldZ": [GRAVITY_MPS2 + 1.0, GRAVITY_MPS2 - 0.5],
        }
    ).to_csv(input_path, index=False)

    dataframe = load_world_dataframe(input_path)

    assert dataframe["world_z_linear"].tolist() == pytest.approx([1.0, -0.5])


def test_build_event_intervals_ignores_during_rows() -> None:
    event_df = pd.DataFrame(
        {
            "elapsed_ms": [100.0, 150.0, 200.0, 400.0],
            "event": [
                "dekobo_start",
                "dekobo_during",
                "dekobo_during",
                "dekobo_stop",
            ],
        }
    )

    intervals = build_event_intervals(
        event_df,
        start_event="dekobo_start",
        stop_event="dekobo_stop",
    )

    assert intervals == [(100.0, 400.0)]


def test_build_event_intervals_extends_start_earlier() -> None:
    event_df = pd.DataFrame(
        {
            "elapsed_ms": [1200.0, 1800.0],
            "event": ["dansa_start", "dansa_stop"],
        }
    )

    intervals = build_event_intervals(
        event_df,
        start_event="dansa_start",
        stop_event="dansa_stop",
        pre_event_extension_ms=1000.0,
    )

    assert intervals == [(200.0, 1800.0)]


def test_assign_window_label_prioritizes_dansa() -> None:
    label = assign_window_label(
        window_start_ms=0.0,
        window_end_ms=1000.0,
        intervals_by_label={
            "dansa": [(300.0, 900.0)],
            "dekobo": [(0.0, 1000.0)],
        },
        overlap_threshold=0.5,
    )

    assert label == "dansa"


def test_compute_window_features_matches_expected_values() -> None:
    features = compute_window_features(pd.Series([0.0, 1.0, 3.0, 2.0]).to_numpy())

    assert features["z_range"] == pytest.approx(3.0)
    assert features["z_diff_max"] == pytest.approx(2.0)
    assert features["z_rms"] == pytest.approx((14.0 / 4.0) ** 0.5)
    assert features["z_std"] == pytest.approx(1.118033988749895)


def test_build_dataset_dataframe_labels_windows_from_real_layout(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    root_run_dir = tmp_path / "runs"
    world_csv_dir = tmp_path / "world_csv"
    run_id = "run01"
    run_dir = root_run_dir / run_id
    run_world_dir = world_csv_dir / run_id
    run_dir.mkdir(parents=True)
    run_world_dir.mkdir(parents=True)

    pd.DataFrame(
        {
            "elapsed": [0.0, 250.0, 500.0, 750.0, 1000.0],
            "accWorldZ": [
                GRAVITY_MPS2 + 0.0,
                GRAVITY_MPS2 + 1.0,
                GRAVITY_MPS2 + 3.0,
                GRAVITY_MPS2 + 2.0,
                GRAVITY_MPS2 + 0.0,
            ],
        }
    ).to_csv(run_world_dir / "acc_world.csv", index=False)
    pd.DataFrame(
        {
            "elapsed_ms": [0.0, 500.0],
            "event": ["dansa_start", "dansa_stop"],
        }
    ).to_csv(run_dir / "dansa.csv", index=False)
    pd.DataFrame(
        {
            "elapsed_ms": [750.0, 1250.0],
            "event": ["dekobo_start", "dekobo_stop"],
        }
    ).to_csv(run_dir / "dekobo.csv", index=False)
    config_path.write_text(
        "\n".join(
            [
                "data:",
                f"  root_run_dir: {root_run_dir}",
                f"  world_csv_dir: {world_csv_dir}",
                f"  features_dir: {tmp_path / 'features'}",
                f"  processed_dir: {tmp_path / 'processed'}",
                "window:",
                "  window_seconds: 1.0",
                "  stride_seconds: 0.25",
                "  sampling_interval_seconds: 0.25",
                "label:",
                "  mode: multiclass",
                "  overlap_threshold: 0.5",
                "  pre_event_extension_seconds: 1.0",
                "  labels:",
                "    - flat",
                "    - dansa",
                "    - dekobo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)
    dataframe = build_dataset_dataframe(config=config)

    assert dataframe["run_id"].tolist() == ["run01", "run01"]
    assert dataframe["label"].tolist() == ["dansa", "dekobo"]
    assert dataframe["z_diff_max"].tolist() == pytest.approx([2.0, 2.0])


def test_train_wheelchair_model_main_saves_eval_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "dataset.csv"
    config_path = tmp_path / "config.yaml"
    processed_dir = tmp_path / "processed"

    pd.DataFrame(
        [
            {
                "run_id": "20260622175452",
                "window_id": 0,
                "start_ms": 0,
                "end_ms": 1000,
                "label": "flat",
                "z_range": 0.1,
                "z_diff_max": 0.0,
                "z_rms": 0.1,
                "z_std": 0.05,
            },
            {
                "run_id": "20260622175452",
                "window_id": 1,
                "start_ms": 250,
                "end_ms": 1250,
                "label": "dansa",
                "z_range": 3.0,
                "z_diff_max": 2.0,
                "z_rms": 2.5,
                "z_std": 1.0,
            },
            {
                "run_id": "20260622175452",
                "window_id": 2,
                "start_ms": 500,
                "end_ms": 1500,
                "label": "dekobo",
                "z_range": 1.5,
                "z_diff_max": 0.6,
                "z_rms": 1.2,
                "z_std": 0.6,
            },
            {
                "run_id": "20260622182555",
                "window_id": 0,
                "start_ms": 0,
                "end_ms": 1000,
                "label": "flat",
                "z_range": 0.2,
                "z_diff_max": 0.1,
                "z_rms": 0.2,
                "z_std": 0.05,
            },
            {
                "run_id": "20260622182555",
                "window_id": 1,
                "start_ms": 250,
                "end_ms": 1250,
                "label": "dansa",
                "z_range": 2.8,
                "z_diff_max": 2.1,
                "z_rms": 2.4,
                "z_std": 0.9,
            },
            {
                "run_id": "20260622182555",
                "window_id": 2,
                "start_ms": 500,
                "end_ms": 1500,
                "label": "dekobo",
                "z_range": 1.4,
                "z_diff_max": 0.5,
                "z_rms": 1.1,
                "z_std": 0.5,
            },
        ]
    ).to_csv(dataset_path, index=False)
    config_path.write_text(
        "\n".join(
            [
                "data:",
                f"  processed_dir: {processed_dir}",
                "label:",
                "  mode: multiclass",
                "  labels:",
                "    - flat",
                "    - dansa",
                "    - dekobo",
                "model:",
                "  name: random_forest",
                "  n_estimators: 16",
                "  random_state: 42",
                "  class_weight: balanced",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "train-wheelchair-model",
            "--config",
            str(config_path),
            "--input",
            str(dataset_path),
            "--train-run-id",
            "20260622175452",
            "--eval-run-id",
            "20260622182555",
        ],
    )

    train_wheelchair_model_main()

    output_dirs = sorted(path for path in processed_dir.iterdir() if path.is_dir())
    assert len(output_dirs) == 1
    output_dir = output_dirs[0]
    assert (output_dir / "run_split.txt").exists()
    assert (
        output_dir / "classification_report_random_forest_20260622182555.txt"
    ).exists()
    assert (output_dir / "classification_report_random_forest_all_eval.txt").exists()
    assert (output_dir / "confusion_matrix_random_forest_20260622182555.csv").exists()
