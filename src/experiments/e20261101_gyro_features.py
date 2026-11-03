"""ジャイロ(角速度)から特徴量を作り、加速度の特徴量(hz12・m6)に足したときの精度を調べる(10.31 + 11.1)。

ジャイロ(gyro.csv、端末の座標系)を、加速度と同じ姿勢(rotation vector、acc.csv)で世界座標系に変換し、
走る向きによらない量にする(ADR 2026-10-17・2026-11-01 と同じ考え方)。
  g : 傾きの速さ = 水平の角速度の大きさ √(ωx² + ωy²) [rad/s]。車体が前後・左右に傾く速さ
(鉛直の角速度 = 曲がる速さ(yaw6)も試したが、flat が下がったので外した。ナレッジ 20261101_gyro_features 参照)
ジャイロと姿勢は、センサーの時刻(eventTimestampNs)で加速度の行に合わせる。

特徴量:
  g6     : g × 基本4 + 尖度・クレスト
  tilt2  : 窓の中の傾き(重力の向きの、セッションの中央値からのずれ [度])の範囲と標準偏差
  ratio2 : g の低い周波数(<5 Hz)と高い周波数(>10 Hz)のパワーの比(log10)、g の rms ÷ z の rms(log10)
  core5  : 絞り込んだ 5 個。z_rms・z_kurt(揺れの大きさと形)+ tilt_range・g_low_high・g_over_z

条件は e20261101_combined_eval と同じ(10.31 汎用 + 11.1 の 68〜69 kg、use=yes、方針A、START を 1 秒ずらす、
SVM・RF、セッション単位の LOGO、窓 1.0・2.0 秒)。

出力(data/analysis/20261101_gyro_features/): results.csv、confusion.csv
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch
from scipy.spatial.transform import Rotation
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import intervals
from src.experiments.e20261101_combined_eval import load_meta
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.features import cols

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_S = [1.0, 2.0]
SHIFT_S = 1.0
LOW_HZ, HIGH_HZ = 5.0, 10.0

HZ12 = cols("hz", BASIC + SHAPE)
M6 = cols("m", BASIC + SHAPE)
G6 = cols("g", BASIC + SHAPE)
TILT2 = ["tilt_range", "tilt_std"]
RATIO2 = ["g_low_high", "g_over_z"]
CORE5 = ["z_rms", "z_kurt", "tilt_range", "g_low_high", "g_over_z"]
FEATURE_SETS = {
    "hz12": HZ12,
    "hz12+g6": HZ12 + G6,
    "hz12+g6+tilt2": HZ12 + G6 + TILT2,
    "hz12+g6+tilt2+ratio2": HZ12 + G6 + TILT2 + RATIO2,
    "hz12+tilt2+ratio2": HZ12 + TILT2 + RATIO2,
    "core5": CORE5,
    "m6": M6,
    "m6+g6+tilt2+ratio2": M6 + G6 + TILT2 + RATIO2,
}


def add_gyro(sess: dict, run_dir: Path) -> None:
    """ジャイロを世界座標系にして、加速度の行にそろえた軸(g)と、傾き(tilt)を sess に足す。"""
    acc = pd.read_csv(run_dir / "acc.csv", usecols=["eventTimestampNs", "rotX", "rotY", "rotZ", "rotW"])
    gyro = pd.read_csv(run_dir / "gyro.csv", usecols=["eventTimestampNs", "gyroX", "gyroY", "gyroZ"])
    t_acc = acc["eventTimestampNs"].to_numpy(float)
    t_gyro = gyro["eventTimestampNs"].to_numpy(float)
    rot = Rotation.from_quat(acc[["rotX", "rotY", "rotZ", "rotW"]].to_numpy(float))
    # 各ジャイロの行に、時刻が一番近い加速度の行の姿勢を使う
    idx = np.clip(np.searchsorted(t_acc, t_gyro), 0, len(t_acc) - 1)
    prev = np.clip(idx - 1, 0, len(t_acc) - 1)
    idx = np.where(np.abs(t_acc[prev] - t_gyro) < np.abs(t_acc[idx] - t_gyro), prev, idx)
    w_world = rot[idx].apply(gyro[["gyroX", "gyroY", "gyroZ"]].to_numpy(float))
    # 加速度の行の時刻に補間する(load_session の軸と同じ長さ・順番)
    wx, wy = (np.interp(t_acc, t_gyro, w_world[:, i]) for i in range(2))
    assert len(t_acc) == len(sess["ts"])
    sess["axes"]["g"] = np.hypot(wx, wy)
    # 傾き: 端末の座標系での鉛直(世界の上向き)の向きが、セッションの中央値からどれだけずれたか
    up_dev = rot.inv().apply(np.array([0.0, 0.0, 1.0]))
    ref = np.median(up_dev, axis=0)
    ref /= np.linalg.norm(ref)
    sess["tilt"] = np.degrees(np.arccos(np.clip(up_dev @ ref, -1.0, 1.0)))


def gyro_window_features(sess: dict, starts: np.ndarray, window_s: float) -> pd.DataFrame:
    ts, fs = sess["ts"], sess["fs"]
    rows = []
    for start in starts:
        lo, hi = np.searchsorted(ts, [start, start + window_s * 1000.0])
        g, z, tilt = sess["axes"]["g"][lo:hi], sess["axes"]["z"][lo:hi], sess["tilt"][lo:hi]
        f, p = welch(g - g.mean(), fs=fs, nperseg=min(256, len(g)))
        low, high = p[(f > 0) & (f < LOW_HZ)].sum(), p[f > HIGH_HZ].sum()
        rows.append({
            "start_ms": start,
            "tilt_range": float(np.ptp(tilt)),
            "tilt_std": float(np.std(tilt)),
            "g_low_high": float(np.log10((low + 1e-12) / (high + 1e-12))),
            "g_over_z": float(np.log10(np.sqrt(np.mean(g**2)) / np.sqrt(np.mean(z**2)))),
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", nargs="+", default=["10.31", "11.1"])
    parser.add_argument("--weights", nargs="*", type=float, default=[68, 69])
    parser.add_argument("--output-dir", default="data/analysis/20261101_gyro_features")
    args = parser.parse_args()

    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    meta = load_meta(args.days, "standard", args.weights)
    print("使うセッション:", meta.groupby(["day", "kind"]).size().to_dict())

    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    kind_of = dict(zip(meta["session_id"], meta["kind"]))

    rows, conf_rows = [], []
    pd.set_option("display.width", 220)
    for window_s in WINDOWS_S:
        frames = []
        for s, sess in sessions.items():
            win = window_features(sess, window_s)
            win = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
            iv, dr = intervals(passes[s], SHIFT_S) if s in passes else ({}, [])
            labels = label_windows(win, window_s, kind_of[s], iv, dr)
            frames.append(win.assign(label=labels, group=s).dropna(subset=["label"]))
        df = pd.concat(frames, ignore_index=True)
        print(f"\n== 窓 {window_s:.1f} 秒")
        print("クラスごとの中央値(参考):")
        print(df.groupby("label")[["g_rms", "g_kurt", "tilt_range", "g_low_high", "g_over_z"]].median()
              .rename(index=DISPLAY).round(3))
        for (fs_name, features), (model_name, model) in itertools.product(FEATURE_SETS.items(), models().items()):
            pred = cross_val_predict(model, df[features], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
            key = {"window_s": window_s, "features": fs_name, "n_features": len(features), "model": model_name}
            row = {**key, **{f"r_{DISPLAY[k]}": float((pred[df["label"] == k] == k).mean()) for k in LABELS}}
            m = confusion_matrix(df["label"], pred, labels=LABELS)
            for i, t in enumerate(LABELS):
                for j, q in enumerate(LABELS):
                    conf_rows.append({**key, "true": DISPLAY[t], "pred": DISPLAY[q], "n": int(m[i, j])})
            row["step_to_rough"] = int(m[1, 2])
            row["rough_to_step"] = int(m[2, 1])
            row["flat_to_rough"] = int(m[0, 2])
            rows.append(row)
            print(f"{fs_name:26s} {model_name:12s} flat/step/rough = {row['r_flat']:.2f}/{row['r_step']:.2f}/"
                  f"{row['r_rough']:.2f}  step→rough {row['step_to_rough']:3d}  rough→step {row['rough_to_step']:3d}"
                  f"  flat→rough {row['flat_to_rough']:3d}", flush=True)

    pd.DataFrame(rows).to_csv(out / "results.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(out / "confusion.csv", index=False)


if __name__ == "__main__":
    main()
