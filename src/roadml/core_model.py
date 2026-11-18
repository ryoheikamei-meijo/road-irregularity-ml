"""アプリで判定するための、core の特徴量の基準の実装(Android の Kotlin 版と同じ手順)。

入力は acc.csv の 1 行ずつの値だけ(時刻・加速度 accX/Y/Z・姿勢 rotX/Y/Z/W)。ジャイロ(gyro.csv)は使わない。

- 世界座標系の加速度 = 姿勢(rotation vector の四元数)で端末座標の加速度を回したもの(io.transform_to_world_frame と同じ)
- z = 世界の鉛直 − 重力、h = √(x² + y²)(ADR 2026-10-17)
- 傾き tilt = 端末の座標系で見た世界の上向きが、基準の向きから何度ずれたか(e20261101_gyro_features.add_gyro と同じ)
- 窓: 長さ 2.0 秒、0.5 秒ずつずらす。窓の中のサンプルが想定の 8 割に満たない窓は使わない(windows と同じ)

傾きの基準(tilt_ref)
  session : セッション全体の中央値(これまでの解析)。走り終わらないと決まらないので、アプリでは計算できない
  window  : 窓の中の中央値。窓の中だけで決まり、前の状態を持たない
  ema<s>  : それまでの上向きの指数移動平均(時定数 s 秒)。過去のデータだけで決まる
  mean<s> : 直近 s 秒の上向きの平均(Mizell 2003 の窓の平均を、過去だけで計算する形。Hemminki ら 2013 が比べた方法)。
            サンプルごとに取り直すので、2 秒の窓の中でも基準が動く
  startmean<s> : 窓の最初のサンプルの時点での mean<s> を、その窓の基準にする。窓の中では基準を固定する。
            tilt_range を「窓の中で、1 つの基準から見た傾きの幅」として式 1 つで書けるようにするため(第19回ゼミのメモ。
            docs/knowledge/2026-11-18/20261118_window_fixed_tilt_reference.md)

特徴量(CORE): z_rms・z_kurt・h_std・h_crest・tilt_range(ゼミ資料 131-017 の core(暫定))
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
from scipy.stats import kurtosis

from src.roadml.io import GRAVITY_MPS2

CORE = ["z_rms", "z_kurt", "h_std", "h_crest", "tilt_range"]
WINDOW_S = 2.0
STRIDE_S = 0.5
MIN_FILL = 0.8


def load_raw(run_dir: Path, name: str = "acc.csv") -> dict[str, np.ndarray]:
    """acc.csv(計測用アプリ)または input.csv(判定アプリ。同じ列名)から、アプリで手に入る値だけを読む。"""
    a = pd.read_csv(run_dir / name, usecols=["timestamp", "accX", "accY", "accZ", "rotX", "rotY", "rotZ", "rotW"])
    return {"ts": a["timestamp"].to_numpy(float),
            "acc": a[["accX", "accY", "accZ"]].to_numpy(float),
            "quat": a[["rotX", "rotY", "rotZ", "rotW"]].to_numpy(float)}


def signals(raw: dict[str, np.ndarray], tilt_ref: str = "window") -> dict[str, np.ndarray]:
    """サンプルごとの z・h と、端末の座標系での世界の上向き(up)。
    tilt_ref が session・ema・mean なら tilt も。startmean なら基準(ref)を返し、tilt は窓ごとに core_features で求める。"""
    rot = Rotation.from_quat(raw["quat"])
    world = rot.apply(raw["acc"])
    up = rot.inv().apply(np.array([0.0, 0.0, 1.0]))
    out = {"ts": raw["ts"], "z": world[:, 2] - GRAVITY_MPS2, "h": np.hypot(world[:, 0], world[:, 1]), "up": up}
    if tilt_ref == "session":
        ref = np.median(up, axis=0)
        out["tilt"] = _angle(up, ref / np.linalg.norm(ref))
    elif tilt_ref.startswith("ema"):
        tau_ms = float(tilt_ref.removeprefix("ema")) * 1000.0
        ref = _ema(up, raw["ts"], tau_ms)
        out["tilt"] = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", up, ref), -1.0, 1.0)))
    elif tilt_ref.startswith("startmean"):
        out["ref"] = _past_mean(up, raw["ts"], float(tilt_ref.removeprefix("startmean")) * 1000.0)
    elif tilt_ref.startswith("mean"):
        ref = _past_mean(up, raw["ts"], float(tilt_ref.removeprefix("mean")) * 1000.0)
        out["tilt"] = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", up, ref), -1.0, 1.0)))
    elif tilt_ref != "window":
        raise ValueError(tilt_ref)
    return out


def _angle(up: np.ndarray, ref: np.ndarray) -> np.ndarray:
    return np.degrees(np.arccos(np.clip(up @ ref, -1.0, 1.0)))


def _ema(up: np.ndarray, ts: np.ndarray, tau_ms: float) -> np.ndarray:
    """時刻 i までの上向きの指数移動平均(長さ 1 にそろえる)。i 番目の値は i 番目までのサンプルだけで決まる。"""
    ref = np.empty_like(up)
    cur = up[0].copy()
    for i in range(len(up)):
        if i > 0:
            alpha = 1.0 - np.exp(-(ts[i] - ts[i - 1]) / tau_ms)
            cur += alpha * (up[i] - cur)
            cur /= np.linalg.norm(cur)
        ref[i] = cur
    return ref


def _past_mean(up: np.ndarray, ts: np.ndarray, span_ms: float) -> np.ndarray:
    """時刻 i までの直近 span_ms の上向きの平均(長さ 1 にそろえる)。Mizell(2003)の「一定時間の窓の平均」を、過去だけで計算する形。"""
    csum = np.vstack([np.zeros(3), np.cumsum(up, axis=0)])
    lo = np.searchsorted(ts, ts - span_ms, side="left")
    hi = np.arange(1, len(ts) + 1)
    ref = (csum[hi] - csum[lo]) / (hi - lo)[:, None]
    return ref / np.linalg.norm(ref, axis=1, keepdims=True)


def window_core(z: np.ndarray, h: np.ndarray, tilt: np.ndarray) -> dict[str, float]:
    z_rms = float(np.sqrt(np.mean(z**2)))
    h_rms = float(np.sqrt(np.mean(h**2)))
    return {"z_rms": z_rms,
            "z_kurt": float(kurtosis(z)),  # 超過尖度(Fisher)、偏りの補正なし
            "h_std": float(np.std(h)),
            "h_crest": float(np.max(np.abs(h)) / h_rms) if h_rms > 0 else 0.0,
            "tilt_range": float(np.ptp(tilt))}


def window_starts(ts: np.ndarray, window_s: float = WINDOW_S, stride_s: float = STRIDE_S):
    """窓の始まり(ms)と、サンプルの範囲 [lo, hi)。e20261031_button_lag.window_features と同じ切り方。"""
    window_ms = window_s * 1000.0
    expected = window_ms / np.median(np.diff(ts))
    start = ts[0]
    while start + window_ms <= ts[-1]:
        lo, hi = np.searchsorted(ts, [start, start + window_ms])
        if hi - lo >= MIN_FILL * expected:
            yield start, lo, hi
        start += stride_s * 1000.0


def core_features(sig: dict[str, np.ndarray], window_s: float = WINDOW_S, tilt_ref: str = "window") -> pd.DataFrame:
    rows = []
    for start, lo, hi in window_starts(sig["ts"], window_s):
        if tilt_ref == "window":
            up = sig["up"][lo:hi]
            ref = np.median(up, axis=0)
            tilt = _angle(up, ref / np.linalg.norm(ref))
        elif tilt_ref.startswith("startmean"):
            tilt = _angle(sig["up"][lo:hi], sig["ref"][lo])  # 窓の最初のサンプルの時点の基準で固定
        else:
            tilt = sig["tilt"][lo:hi]
        rows.append({"start_ms": start, **window_core(sig["z"][lo:hi], sig["h"][lo:hi], tilt)})
    return pd.DataFrame(rows)
