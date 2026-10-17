"""セッションの読み込みと、世界座標系への変換。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

ACC_COLUMNS = ["accX", "accY", "accZ"]
ROTATION_COLUMNS = ["rotX", "rotY", "rotZ", "rotW"]
GRAVITY_MPS2 = 9.80665


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


def load_world_session(run_dir: Path) -> pd.DataFrame:
    """セッションのフォルダの acc.csv を読み、世界座標系に変換する。"""
    return transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
