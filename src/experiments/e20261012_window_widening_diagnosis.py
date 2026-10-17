"""窓幅を広げたときの精度向上が、正当か・見かけかを確かめる診断。

① 段差のバースト(ラベルを使わず、zの30ms RMS包絡線のピーク>10m/s²、1秒以上離れたもの)を
   含む窓/含まない窓に分けて、クラスごとの再現率を出す。
② 短い窓の予測を長い窓の範囲で多数決したものと、長い窓のモデルの予測を、同じ長い窓の集合で比べる。
特徴量は xyz18(基本4+尖度・クレスト)、評価はLOGO。
窓特徴量は e20261012_window_widening の出力(windows_{窓幅}s.csv)を使う。

使い方: python -m src.experiments.e20261012_window_widening_diagnosis <後ろ固定のみのデータdir> [窓特徴量・出力のdir]
"""

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict

from src.roadml.evaluation import models
from src.roadml.features import BASIC, SHAPE
from src.roadml.io import load_acc_dataframe, transform_to_world_frame
from src.roadml.io import GRAVITY_MPS2

DATA = Path(sys.argv[1])
WIN_DIR = Path(sys.argv[2] if len(sys.argv) > 2 else "data/analysis/20261012_window_widening")
WIDTHS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
COLS = [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE]
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}

# セッションごとのバーストの時刻(ms)
bursts = {}
for d in sorted(p for p in DATA.iterdir() if (p / "acc.csv").exists()):
    w = transform_to_world_frame(load_acc_dataframe(d / "acc.csv"))
    ts = w["timestamp"].to_numpy(float)
    z = w["accWorldZ"].to_numpy(float) - GRAVITY_MPS2
    fs = 1000.0 / np.median(np.diff(ts))
    env = np.sqrt(uniform_filter1d(z**2, size=max(1, int(0.030 * fs)), mode="nearest"))
    peaks, _ = find_peaks(env, height=10.0, distance=int(1.0 * fs))
    bursts[d.name] = ts[peaks]

preds = {}
for width in WIDTHS:
    df = pd.read_csv(WIN_DIR / f"windows_{width}s.csv")
    df["has_burst"] = [
        bool(np.any((bursts[s] >= st) & (bursts[s] < st + width * 1000.0)))
        for s, st in zip(df["session"].astype(str), df["start_ms"])
    ]
    for model_name, model in models().items():
        df[f"pred_{model_name}"] = cross_val_predict(model, df[COLS], df["label"], groups=df["group"],
                                                     cv=LeaveOneGroupOut())
    preds[width] = df

print("=== ① バーストを含む窓/含まない窓での再現率 (xyz18) ===")
rows = []
for width, df in preds.items():
    for model_name in models():
        for lab in ["dansa", "dekobo", "flat"]:
            sub = df[df["label"] == lab]
            row = {"window_s": width, "model": model_name, "class": NAME[lab], "n": len(sub),
                   "share_burst": sub["has_burst"].mean(),
                   "recall_all": (sub[f"pred_{model_name}"] == lab).mean()}
            for flag, key in ((True, "with"), (False, "without")):
                s2 = sub[sub["has_burst"] == flag]
                row[f"n_{key}"] = len(s2)
                row[f"recall_{key}"] = (s2[f"pred_{model_name}"] == lab).mean() if len(s2) else np.nan
            rows.append(row)
r1 = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(r1.round(3).to_string(index=False))


def vote(short_w: float, long_w: float, model_name: str) -> dict:
    short, long_ = preds[short_w], preds[long_w]
    by_group = {g: sub for g, sub in short.groupby("group")}
    voted, n_used, ties = [], [], 0
    for g, st in zip(long_["group"], long_["start_ms"]):
        sub = by_group[g]
        m = sub[(sub["start_ms"] >= st - 1) & (sub["start_ms"] <= st + (long_w - short_w) * 1000.0 + 1)]
        if len(m) == 0:
            voted.append(None)
            n_used.append(0)
            continue
        c = Counter(m[f"pred_{model_name}"]).most_common()
        if len(c) > 1 and c[0][1] == c[1][1]:
            ties += 1
        voted.append(c[0][0])
        n_used.append(len(m))
    ok = np.array([v is not None for v in voted])
    y = long_["label"].to_numpy()[ok]
    v = np.array(voted, dtype=object)[ok]
    p = long_[f"pred_{model_name}"].to_numpy()[ok]
    rec = lambda yy, pp, lab: float(np.mean(pp[yy == lab] == lab))  # noqa: E731
    return {"short": short_w, "long": long_w, "model": model_name, "n_long_windows": int(ok.sum()),
            "mean_short_per_vote": float(np.mean(np.array(n_used)[ok])), "ties": ties,
            "vote_bal_acc": balanced_accuracy_score(y, v), "long_bal_acc": balanced_accuracy_score(y, p),
            **{f"vote_r_{NAME[k]}": rec(y, v, k) for k in ["flat", "dansa", "dekobo"]},
            **{f"long_r_{NAME[k]}": rec(y, p, k) for k in ["flat", "dansa", "dekobo"]}}


print("\n=== ② 短い窓の多数決 vs 長い窓 (xyz18) ===")
r2 = pd.DataFrame([vote(s, l, m) for s, l in [(1.0, 2.0), (2.0, 4.0), (2.0, 6.0), (1.0, 4.0)]
                   for m in models()])
print(r2.round(3).to_string(index=False))
r1.to_csv(WIN_DIR / "diag_burst_recall.csv", index=False)
r2.to_csv(WIN_DIR / "diag_vote_vs_long.csv", index=False)
