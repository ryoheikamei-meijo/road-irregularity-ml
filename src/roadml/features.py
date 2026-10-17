"""窓ごとの特徴量。

- BASIC(基本4): std・range・rms・diff_max。揺れの大きさ
- SHAPE: kurt(尖度、超過尖度)・crest(クレストファクター)。窓の中の波形の形
- BURST: 30ms の RMS 包絡線から作る、スケール不変な特徴量(10.5)
    - burst_ratio: 包絡線の最大 / 中央値 (ピークが床よりどれだけ突出しているか)
    - burst_duty : 包絡線が最大の25%を超えている時間割合 (単発なら小さく、連続振動なら大きい)
    - n_peaks    : 最大の30%を超えるピークの数 (最小間隔0.15s)
    - peak_gap   : ピーク間隔の平均[s] (ピークが1つ以下なら窓長)
  閾値は窓自身の最大値に対する相対値で、ラベル(イベント区間)や他クラスの統計は使わない。

軸の名前は x・y(世界座標系の東・北)、z(鉛直 − 重力)、m(合成 |a| − 重力)、
h(水平の大きさ √(x²+y²)。horizontal_axes で足す。ADR 2026-10-17)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks
from scipy.stats import kurtosis

BASIC = ["std", "range", "rms", "diff_max"]
SHAPE = ["kurt", "crest"]
BURST = ["burst_ratio", "burst_duty", "n_peaks", "peak_gap"]
SMOOTH_S = 0.030
MIN_PEAK_GAP_S = 0.15


def axis_features(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    rms = float(np.sqrt(np.mean(values**2)))
    env = np.sqrt(uniform_filter1d(values**2, size=max(1, int(SMOOTH_S * fs)), mode="nearest"))
    mx, med = float(env.max()), float(np.median(env))
    peaks, _ = find_peaks(env, height=0.3 * mx, distance=max(1, int(MIN_PEAK_GAP_S * fs)))
    gap = float(np.mean(np.diff(peaks)) / fs) if len(peaks) >= 2 else window_s
    return {
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_range": float(np.ptp(values)),
        f"{prefix}_rms": rms,
        f"{prefix}_diff_max": float(np.max(np.diff(values))),
        f"{prefix}_kurt": float(kurtosis(values)),
        f"{prefix}_crest": float(np.max(np.abs(values)) / rms) if rms > 0 else 0.0,
        f"{prefix}_burst_ratio": mx / med if med > 0 else 0.0,
        f"{prefix}_burst_duty": float(np.mean(env > 0.25 * mx)),
        f"{prefix}_n_peaks": float(len(peaks)),
        f"{prefix}_peak_gap": gap,
    }


def cols(axes: str, feats: list[str]) -> list[str]:
    """軸(1文字ずつ)と特徴量の名前から、列名の一覧を作る。例: cols("zh", BASIC)"""
    return [f"{a}_{f}" for a in axes for f in feats]


def horizontal_axes(world: pd.DataFrame) -> dict[str, np.ndarray]:
    """windows.build_run の extra_axes 用。水平の大きさ h = √(x²+y²)(走る向きに依存しない)。"""
    return {"h": np.hypot(world["accWorldX"].to_numpy(float), world["accWorldY"].to_numpy(float))}
