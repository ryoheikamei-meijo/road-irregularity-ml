"""発表資料(131-015)の評価条件で、混同行列と誤分類の内訳を調べる(後ろ固定のみ、バーストなし)。

対象:
  ① 3軸・基本4+尖度・クレスト(xyz18)、SVM/RF、2.0秒(発表の最良)
  ② 合成・基本4+尖度・クレスト(m6)、SVM/RF、2.0秒
  ③ 3軸・基本4のみ(xyz12)、SVM/RF、2.0秒(①と比べて、尖度・クレストでどの誤りが減ったか)
  ④ ①の1.0秒版
  ⑤ 参考: ①にバースト特徴量を足した xyz30(発表では未使用。どの誤りが減るかを見る)
評価の枠組み(方針A、窓幅の1/4刻み、LOGO、モデル)は e20261005_burst_segment と同じ。

出力:
  confusion_counts.csv / confusion_figure.png : 混同行列(窓数と行ごとの割合)
  errors_by_session.csv : 正解クラス×予測クラスの誤りが、どのグループ(セッション/flatブロック)から来ているか
  errors_by_position.csv : step/rough の窓を、区間の端からの距離と、強いバーストの有無で分けた再現率と誤りの行き先
  windows_pred.csv : 窓ごとの予測(後から集計し直す用)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import BURST
from src.roadml.features import SHAPE
from src.roadml.windows import build_run
from src.roadml.features import cols
from src.roadml.labeling import build_intervals
from src.roadml.io import load_acc_dataframe
from src.roadml.io import transform_to_world_frame
from src.roadml.io import GRAVITY_MPS2
from src.roadml.datasets import add_run_dir_args
from src.roadml.datasets import resolve_run_dirs

plt.rcParams["font.family"] = "Hiragino Sans"

NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}
# (名前, 窓幅, 特徴量列)
CASES = [
    ("①xyz18_2.0s", 2.0, cols("xyz", BASIC + SHAPE)),
    ("②m6_2.0s", 2.0, cols("m", BASIC + SHAPE)),
    ("③xyz12_2.0s", 2.0, cols("xyz", BASIC)),
    ("④xyz18_1.0s", 1.0, cols("xyz", BASIC + SHAPE)),
    ("⑤xyz30_2.0s", 2.0, cols("xyz", BASIC + SHAPE + BURST)),  # 参考: バーストを足すとどの誤りが減るか
]
PRE_EXTENSION_MS = 500.0  # build_run の既定と同じ
BURST_HEIGHT = 10.0  # 2.6節の診断と同じ(zの30ms RMS包絡線のピーク)
EDGE_BINS = [0.0, 1.0, 2.0, 4.0, np.inf]  # 窓の中心から区間の端までの距離[秒]


def session_info(run_dir: Path) -> tuple[np.ndarray, dict]:
    """強いバーストの時刻(ms)と、dansa/dekobo の区間。"""
    w = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    ts = w["timestamp"].to_numpy(float)
    z = w["accWorldZ"].to_numpy(float) - GRAVITY_MPS2
    fs = 1000.0 / np.median(np.diff(ts))
    env = np.sqrt(uniform_filter1d(z**2, size=max(1, int(0.030 * fs)), mode="nearest"))
    peaks, _ = find_peaks(env, height=BURST_HEIGHT, distance=int(1.0 * fs))
    return ts[peaks], build_intervals(run_dir, PRE_EXTENSION_MS)


def add_position(df: pd.DataFrame, window_s: float, info: dict) -> pd.DataFrame:
    """窓の中心から、その窓のラベルの区間の端までの距離と、強いバーストの有無。"""
    w_ms = window_s * 1000.0
    edge, burst = [], []
    for s, st, lab in zip(df["session"].astype(str), df["start_ms"], df["label"]):
        bursts, intervals = info[s]
        burst.append(bool(np.any((bursts >= st) & (bursts < st + w_ms))))
        center = st + w_ms / 2
        d = [min(center - a, b - center) for a, b in intervals.get(lab, []) if a <= center <= b]
        edge.append(max(d) / 1000.0 if d else np.nan)
    return df.assign(edge_s=edge, has_burst=burst)


def plot_confusions(mats: dict, path: Path) -> None:
    n = len(mats)
    fig, axes = plt.subplots(2, (n + 1) // 2, figsize=(4.2 * ((n + 1) // 2), 8.4))
    names = [NAME[k] for k in LABELS]
    for ax, (title, m) in zip(axes.ravel(), mats.items()):
        ratio = m / m.sum(axis=1, keepdims=True)
        ax.imshow(ratio, cmap="Blues", vmin=0, vmax=1)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{m[i, j]}\n({ratio[i, j]:.2f})", ha="center", va="center",
                        color="white" if ratio[i, j] > 0.6 else "black", fontsize=10)
        ax.set_xticks(range(3), names)
        ax.set_yticks(range(3), names)
        ax.set_xlabel("予測")
        ax.set_ylabel("正解")
        ax.set_title(title, fontsize=10)
    for ax in axes.ravel()[len(mats):]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    add_run_dir_args(parser)
    parser.add_argument("--output-dir", default="data/analysis/20261013_confusion_presented")
    args = parser.parse_args()

    run_dirs = resolve_run_dirs(args)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    info = {d.name: session_info(d) for d in run_dirs}

    windows: dict[float, pd.DataFrame] = {}
    count_rows, sess_rows, pos_rows, preds, mats = [], [], [], [], {}
    for case, window_s, feature_cols in CASES:
        if window_s not in windows:
            df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
            windows[window_s] = add_position(df, window_s, info)
        df = windows[window_s]
        y = df["label"].to_numpy()
        for model_name, model in models().items():
            title = f"{case} {model_name}"
            pred = cross_val_predict(model, df[feature_cols], y, groups=df["group"], cv=LeaveOneGroupOut())
            m = confusion_matrix(y, pred, labels=LABELS)
            mats[title] = m
            print(f"\n== {title}  (行=正解 flat/step/rough, 列=予測)\n{m}", flush=True)
            for i, t in enumerate(LABELS):
                for j, p in enumerate(LABELS):
                    count_rows.append({"case": case, "model": model_name, "true": NAME[t], "pred": NAME[p],
                                       "n": int(m[i, j]), "ratio": m[i, j] / m[i].sum()})
            d = df.assign(pred=pred, case=case, model=model_name)
            preds.append(d[["case", "model", "group", "session", "start_ms", "t_rel_ms", "label", "pred",
                            "edge_s", "has_burst"]])
            # セッション(グループ)ごとの内訳
            for (g, t), sub in d.groupby(["group", "label"]):
                row = {"case": case, "model": model_name, "group": g, "true": NAME[t], "n": len(sub)}
                for p in LABELS:
                    row[f"to_{NAME[p]}"] = int((sub["pred"] == p).sum())
                row["recall"] = row[f"to_{NAME[t]}"] / len(sub)
                sess_rows.append(row)
            # 区間の端からの距離 × バーストの有無
            ev = d[d["label"] != "flat"].copy()
            ev["edge_bin"] = pd.cut(ev["edge_s"], EDGE_BINS, right=False,
                                    labels=["<1s", "1-2s", "2-4s", ">=4s"])
            for key in ("edge_bin", "has_burst"):
                for (t, b), sub in ev.groupby(["label", key], observed=True):
                    row = {"case": case, "model": model_name, "true": NAME[t], "by": key, "bin": str(b),
                           "n": len(sub)}
                    for p in LABELS:
                        row[f"to_{NAME[p]}"] = int((sub["pred"] == p).sum())
                    row["recall"] = row[f"to_{NAME[t]}"] / len(sub)
                    pos_rows.append(row)

    pd.DataFrame(count_rows).to_csv(out / "confusion_counts.csv", index=False)
    pd.DataFrame(sess_rows).to_csv(out / "errors_by_session.csv", index=False)
    pd.DataFrame(pos_rows).to_csv(out / "errors_by_position.csv", index=False)
    pd.concat(preds, ignore_index=True).to_csv(out / "windows_pred.csv", index=False)
    plot_confusions(mats, out / "confusion_figure.png")

    pd.set_option("display.width", 250)
    print("\n[セッション別]\n", pd.DataFrame(sess_rows).round(2).to_string(index=False))
    print("\n[区間の端からの距離・バースト]\n", pd.DataFrame(pos_rows).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
