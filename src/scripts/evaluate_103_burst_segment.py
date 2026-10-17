"""方針Aの10.3+10.4で (D) 区間単位の評価 と (E) バースト特徴量の追加 を試す。

E: 窓内の短時間RMS包絡線(30ms)から、窓ごとにスケール不変なバースト特徴量を作る。
   - burst_ratio: 包絡線の最大 / 中央値 (ピークが床よりどれだけ突出しているか)
   - burst_duty : 包絡線が最大の25%を超えている時間割合 (単発なら小さく、連続振動なら大きい)
   - n_peaks    : 最大の30%を超えるピークの数 (最小間隔0.15s)
   - peak_gap   : ピーク間隔の平均[s] (ピークが1つ以下なら窓長)
   閾値は窓自身の最大値に対する相対値で、ラベル(イベント区間)や他クラスの統計は使わない。
D: 窓ごとの予測を、(a) セッション単位 (b) 8秒チャンク単位 で多数決して評価する。
   flat は5ブロックをそれぞれ1単位として扱う。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks
from scipy.stats import kurtosis
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix
from sklearn.metrics import f1_score
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.scripts.evaluate_103_baseline import LABELS
from src.scripts.evaluate_103_baseline import models
from src.scripts.plot_boxplots_103 import build_intervals
from src.scripts.plot_boxplots_103 import label_window
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

BASIC = ["std", "range", "rms", "diff_max"]
SHAPE = ["kurt", "crest"]
BURST = ["burst_ratio", "burst_duty", "n_peaks", "peak_gap"]
FEATURE_SETS = {
    "z4+kc": [f"z_{f}" for f in BASIC + SHAPE],
    "z4+kc+burst": [f"z_{f}" for f in BASIC + SHAPE + BURST],
    "xyz12+kc": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE],
    "xyz12+kc+burst": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE + BURST],
    "xyz12+kc+burst_z_only": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE]
    + [f"z_{f}" for f in BURST],
}
SMOOTH_S = 0.030
MIN_PEAK_GAP_S = 0.15
CHUNK_MS = 8000.0


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


def build_run(
    run_dir: Path, window_s: float, flat_blocks: int, pre_extension_ms: float = 500.0,
    extra_features: tuple = (),
    extra_axes=None,
) -> pd.DataFrame:
    """extra_features: axis_features と同じ引数 (values, prefix, fs, window_s) で dict を返す関数。
    窓・軸ごとに追加の特徴量を計算する (既定は空で、従来と同じ出力)。
    extra_axes: world(世界座標系の DataFrame)を受け取り、{軸名: 1次元配列} を返す関数。
    x/y/z/m に加えて、その軸の特徴量も計算する (既定は None で、従来と同じ出力)。"""
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
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


def vote(df: pd.DataFrame, unit_col: str) -> pd.DataFrame:
    """単位ごとに窓予測の多数決を取る。"""
    rows = []
    for unit, sub in df.groupby(unit_col):
        counts = sub["pred"].value_counts()
        rows.append({"unit": unit, "label": sub["label"].iloc[0], "n": len(sub),
                     "pred": counts.idxmax(), "share": counts.max() / len(sub)})
    return pd.DataFrame(rows)


def summarize(y, pred) -> dict[str, float]:
    recall = recall_score(y, pred, labels=LABELS, average=None, zero_division=0)
    return {"bal_acc": balanced_accuracy_score(y, pred),
            "macro_f1": f1_score(y, pred, labels=LABELS, average="macro", zero_division=0),
            "r_flat": recall[0], "r_step": recall[1], "r_rough": recall[2]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--windows", type=float, nargs="+", default=[1.0, 2.0])
    parser.add_argument("--output-dir", default="data/analysis/20261004_boxplot_103_104")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    rows = []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
        df["chunk"] = df["unit_session"] + "_c" + (df["t_rel_ms"] // CHUNK_MS).astype(int).astype(str)
        df.to_csv(out / f"burst_windows_{window_s}s.csv", index=False)
        print(f"\n=== 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
        for set_name, cols in FEATURE_SETS.items():
            for model_name, model in models().items():
                df["pred"] = cross_val_predict(model, df[cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
                w = summarize(df["label"], df["pred"])
                ses = vote(df, "unit_session")
                chk = vote(df[df.groupby("chunk")["chunk"].transform("size") >= 3], "chunk")
                s, c = summarize(ses["label"], ses["pred"]), summarize(chk["label"], chk["pred"])
                rows.append({"window_s": window_s, "features": set_name, "model": model_name,
                             **{f"win_{k}": v for k, v in w.items()},
                             "chunk_bal_acc": c["bal_acc"], "chunk_r_step": c["r_step"], "chunk_r_rough": c["r_rough"],
                             "chunk_n": len(chk), "sess_bal_acc": s["bal_acc"], "sess_n": len(ses)})
                print(f"  {set_name:24s}{model_name:13s} 窓={w['bal_acc']:.3f} 8s塊={c['bal_acc']:.3f} セッション={s['bal_acc']:.3f}", flush=True)
                if set_name in ("xyz12+kc", "xyz12+kc+burst") and model_name == "RandomForest":
                    print("    segment(セッション/ブロック)別 多数決:")
                    print(ses.assign(share=ses["share"].round(2)).to_string(index=False))
                    cm = confusion_matrix(df["label"], df["pred"], labels=LABELS)
                    print(pd.DataFrame(cm, index=["flat", "step", "rough"], columns=["flat", "step", "rough"]).to_string())
    result = pd.DataFrame(rows)
    result.to_csv(out / "burst_segment_sweep.csv", index=False)
    print(result.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
