"""セッションを窓に切り出して、特徴量とラベルを付ける(方針A)。

方針A: step・rough は、ボタンの区間(開始の 0.5 秒前から)に窓の半分以上が重なる窓だけを使う。
イベントのあるセッションの区間外の窓は捨てる。flat は、平坦だけのセッションを時間で
flat_blocks 個のブロックに分け、それぞれを LOGO の 1 グループにする(ブロックの境目の窓は捨てる)。
窓は窓幅の 1/4 ずつずらす。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.roadml.features import axis_features
from src.roadml.io import GRAVITY_MPS2
from src.roadml.io import load_world_session
from src.roadml.labeling import build_intervals
from src.roadml.labeling import label_window


def build_run(
    run_dir: Path, window_s: float, flat_blocks: int, pre_extension_ms: float = 500.0,
    extra_features: tuple = (),
    extra_axes=None,
) -> pd.DataFrame:
    """extra_features: axis_features と同じ引数 (values, prefix, fs, window_s) で dict を返す関数。
    窓・軸ごとに追加の特徴量を計算する (既定は空で、従来と同じ出力)。
    extra_axes: world(世界座標系の DataFrame)を受け取り、{軸名: 1次元配列} を返す関数。
    x/y/z/m に加えて、その軸の特徴量も計算する (既定は None で、従来と同じ出力)。"""
    world = load_world_session(run_dir)
    ts = world["timestamp"].to_numpy(float)
    axes = {
        "x": world["accWorldX"].to_numpy(float),
        "y": world["accWorldY"].to_numpy(float),
        "z": world["accWorldZ"].to_numpy(float) - GRAVITY_MPS2,
        # 合成加速度|a|は姿勢(向き)に依存しない。静止時の下駄(重力分)を引く。
        "m": world["accWorldMag"].to_numpy(float) - GRAVITY_MPS2,
    }
    if extra_axes is not None:
        axes.update(extra_axes(world))
    fs = 1000.0 / np.median(np.diff(ts))
    has_events = (run_dir / "dansa.csv").exists() or (run_dir / "dekobo.csv").exists()
    intervals = build_intervals(run_dir, pre_extension_ms)
    window_ms, stride_ms = window_s * 1000.0, window_s * 250.0
    expected = window_ms / np.median(np.diff(ts))
    rows, start = [], ts[0]
    while start + window_ms <= ts[-1]:
        lo, hi = np.searchsorted(ts, [start, start + window_ms])
        if hi - lo >= 0.8 * expected:
            label = label_window(start, start + window_ms, intervals, 0.5) if has_events else "flat"
            if not (has_events and label == "flat"):
                row = {"start_ms": start, "t_rel_ms": start - ts[0], "label": label}
                for key, values in axes.items():
                    row.update(axis_features(values[lo:hi], key, fs, window_s))
                    for fn in extra_features:
                        row.update(fn(values[lo:hi], key, fs, window_s))
                rows.append(row)
        start += stride_ms
    df = pd.DataFrame(rows)
    if has_events:
        return df.assign(group=run_dir.name, session=run_dir.name, unit_session=run_dir.name)
    edges = np.linspace(df["start_ms"].min(), df["start_ms"].max(), flat_blocks + 1)
    block = np.clip(np.searchsorted(edges, df["start_ms"], side="right") - 1, 0, flat_blocks - 1)
    near = np.min(np.abs(df["start_ms"].to_numpy()[:, None] - edges[1:-1]), axis=1) < window_ms
    name = [f"{run_dir.name}_b{b}" for b in block]
    return df.assign(group=name, session=run_dir.name, unit_session=name)[~near]


def build_windows(run_dirs: list[Path], window_s: float, flat_blocks: int = 5, **kwargs) -> pd.DataFrame:
    """複数のセッションの窓をまとめる。kwargs は build_run に渡す。"""
    return pd.concat([build_run(d, window_s, flat_blocks, **kwargs) for d in run_dirs], ignore_index=True)
