"""誤分類窓の位置を、セッションの z 波形に重ねて描く(窓2.0s, xyz12+尖度+クレスト RF, セッション単位CV)。

下段の帯: 窓の中心から刻み幅(窓の1/4)ぶんを塗る。緑=正解、赤=誤り(誤り先を文字で表示)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.roadml.evaluation import models
from src.experiments.e20261004_shape_features import FEATURE_SETS
from src.experiments.e20261004_shape_features import build_run
from src.roadml.labeling import build_intervals
from src.roadml.io import load_acc_dataframe
from src.roadml.io import transform_to_world_frame
from src.roadml.io import GRAVITY_MPS2
from src.roadml.datasets import add_run_dir_args
from src.roadml.datasets import resolve_run_dirs

plt.rcParams["font.family"] = "Hiragino Sans"
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}


def main() -> None:
    parser = argparse.ArgumentParser()
    add_run_dir_args(parser, default="all_103_104")
    parser.add_argument("--sessions", nargs="+", required=True)
    parser.add_argument("--window-seconds", type=float, default=2.0)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    run_dirs = resolve_run_dirs(args)
    by_name = {d.name: d for d in run_dirs}
    df = pd.concat([build_run(d, args.window_seconds, 5) for d in run_dirs], ignore_index=True)
    cols = FEATURE_SETS["xyz12+kurt+crest"]
    df["pred"] = cross_val_predict(models()["RandomForest"], df[cols], df["label"],
                                   groups=df["group"], cv=LeaveOneGroupOut())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    window_ms = args.window_seconds * 1000.0

    for session in args.sessions:
        sub = df[df["group"] == session]
        run_dir = by_name[session]
        world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
        t0 = world["timestamp"].iloc[0]
        sec = (world["timestamp"] - t0) / 1000.0
        z = world["accWorldZ"] - GRAVITY_MPS2

        fig, (ax, strip) = plt.subplots(2, 1, figsize=(40, 7), sharex=True, gridspec_kw={"height_ratios": [5, 1]})
        ax.plot(sec, z, linewidth=0.4, color="tab:blue")
        for kind, ivs in build_intervals(run_dir, 0.0).items():
            for s, e in ivs:
                ax.axvspan((s - t0) / 1000.0, (e - t0) / 1000.0, color="gray", alpha=0.08)
        ax.axhline(0, color="gray", linewidth=0.5)
        ax.set_ylabel("world z [m/s²]"); ax.grid(alpha=0.3)
        true_name = NAME[sub["label"].iloc[0]]
        wrong = sub[sub["pred"] != sub["label"]]
        ax.set_title(f"{session}  正解={true_name}  誤り {len(wrong)}/{len(sub)} 窓 (窓{args.window_seconds}s)", loc="left")
        for row in sub.itertuples():
            center = (row.start_ms + window_ms / 2 - t0) / 1000.0
            half = args.window_seconds / 8.0
            ok = row.pred == row.label
            strip.axvspan(center - half, center + half, color="tab:green" if ok else "tab:red", alpha=0.7)
            if not ok:
                strip.text(center, 0.5, NAME[row.pred][0], ha="center", va="center", fontsize=8, color="white")
        strip.set_yticks([]); strip.set_xlabel("時間 [s]  (下段: 緑=正解, 赤=誤り[s=step, r=rough, f=flat])")
        strip.set_xlim(0, sec.iloc[-1])
        fig.tight_layout()
        fig.savefig(out / f"misclassified_{session}.png", dpi=100)
        plt.close(fig)

        # 誤り窓と正解窓で、窓内の z_std を比べる
        print(session, true_name, "z_std 正解窓 median", round(sub[sub.pred == sub.label]["z_std"].median(), 2),
              "誤り窓 median", round(wrong["z_std"].median(), 2) if len(wrong) else None)


if __name__ == "__main__":
    main()
