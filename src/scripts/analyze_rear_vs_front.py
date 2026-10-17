"""スマホ固定位置(後ろ/前)の違いを、波形以外の切り口で比べる図を作る(event 区間内のみ)。

図:
- window_stats_{kind}.png : 1秒窓の std と窓内最大|a| の分布(軸別の箱ひげ図)
- psd.png                 : 周波数スペクトル(Welch)。どの周波数帯の振動が違うか
- step_bursts.png         : 段差のバーストごとのピーク値と持続時間(z軸)
- abs_ecdf.png            : |加速度| の累積分布(軸別)
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
from scipy.signal import welch

from src.scripts.plot_boxplots_103 import build_intervals
from src.scripts.plot_rear_vs_front import PAIRS
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"

POSITIONS = ("後ろ固定", "前固定")
COLORS = {"後ろ固定": "tab:blue", "前固定": "tab:orange"}
AXES = ("x", "y", "z")
WINDOW_S, STRIDE_S = 1.0, 0.25


def load_event_samples(run_dir: Path) -> tuple[np.ndarray, dict[str, np.ndarray], float]:
    """event 区間内のサンプルだけを返す(ts, 軸別の値, fs)。"""
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    ts = world["timestamp"].to_numpy(float)
    fs = 1000.0 / np.median(np.diff(ts))
    mask = np.zeros(len(ts), dtype=bool)
    for intervals in build_intervals(run_dir, 0.0).values():
        for start, end in intervals:
            mask |= (ts >= start) & (ts <= end)
    values = {
        "x": world["accWorldX"].to_numpy(float),
        "y": world["accWorldY"].to_numpy(float),
        "z": world["accWorldZ"].to_numpy(float) - GRAVITY_MPS2,
    }
    return ts, {k: v for k, v in values.items()}, fs, mask


def window_stats(ts, values, mask, fs) -> pd.DataFrame:
    rows, start = [], ts[0]
    size = WINDOW_S * 1000.0
    while start + size <= ts[-1]:
        lo, hi = np.searchsorted(ts, [start, start + size])
        if hi - lo > 0.8 * WINDOW_S * fs and mask[lo:hi].mean() >= 0.5:
            rows.append({f"{a}_{s}": f(values[a][lo:hi]) for a in AXES
                         for s, f in (("std", np.std), ("max", lambda v: np.max(np.abs(v))))})
        start += STRIDE_S * 1000.0
    return pd.DataFrame(rows)


def burst_stats(ts, z, mask, fs) -> pd.DataFrame:
    """z の短時間 RMS 包絡線から、event 区間内のバーストごとにピーク値と持続時間を取る。"""
    env = np.sqrt(uniform_filter1d(z**2, size=max(1, int(0.030 * fs)), mode="nearest"))
    slow = np.sqrt(uniform_filter1d(z**2, size=max(1, int(0.100 * fs)), mode="nearest"))
    peaks, _ = find_peaks(env, height=10.0, distance=int(1.0 * fs))
    rows = []
    for p in peaks:
        if not mask[p]:
            continue
        peak = float(np.max(np.abs(z[max(0, p - int(0.05 * fs)):p + int(0.05 * fs)])))
        lo, hi = max(0, p - int(1.5 * fs)), min(len(z), p + int(1.5 * fs))
        above = slow[lo:hi] > 0.2 * slow[p]
        center = p - lo
        left = right = center
        while left > 0 and above[left - 1]:
            left -= 1
        while right < len(above) - 1 and above[right + 1]:
            right += 1
        rows.append({"peak_abs": peak, "duration_s": (right - left) / fs, "after_s": (right - center) / fs})
    return pd.DataFrame(rows)


def boxes(ax, data: dict[str, np.ndarray], title: str, ylabel: str) -> None:
    box = ax.boxplot([data[p] for p in POSITIONS], tick_labels=POSITIONS, showfliers=False, patch_artist=True)
    for patch, pos in zip(box["boxes"], POSITIONS, strict=True):
        patch.set_facecolor(COLORS[pos])
        patch.set_alpha(0.5)
    for i, pos in enumerate(POSITIONS, start=1):
        ax.text(i, ax.get_ylim()[1], f"n={len(data[pos])}\n中央値{np.median(data[pos]):.1f}", ha="center", va="top", fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="10.4 のディレクトリ")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    loaded = {}
    for kind, sessions in PAIRS.items():
        for pos, name in zip(POSITIONS, sessions, strict=True):
            ts, values, fs, mask = load_event_samples(Path(args.data_dir) / name)
            loaded[(kind, pos)] = (ts, values, fs, mask)

    # 1. 窓ごとの std / 最大|a|
    for kind in PAIRS:
        wins = {pos: window_stats(*loaded[(kind, pos)][:2], loaded[(kind, pos)][3], loaded[(kind, pos)][2]) for pos in POSITIONS}
        fig, axs = plt.subplots(2, 3, figsize=(12, 7))
        for col, a in enumerate(AXES):
            boxes(axs[0, col], {p: wins[p][f"{a}_std"].to_numpy() for p in POSITIONS}, f"{a} 軸: 窓内 std", "[m/s²]")
            boxes(axs[1, col], {p: wins[p][f"{a}_max"].to_numpy() for p in POSITIONS}, f"{a} 軸: 窓内 最大|a|", "[m/s²]")
        fig.suptitle(f"{kind}: 1秒窓(刻み0.25秒、event 区間内)の分布 後ろ vs 前")
        fig.tight_layout()
        fig.savefig(out / f"window_stats_{kind}.png", dpi=110)
        plt.close(fig)

    # 2. PSD
    fig, axs = plt.subplots(2, 3, figsize=(14, 7), sharex=True)
    for row, kind in enumerate(PAIRS):
        for col, a in enumerate(AXES):
            for pos in POSITIONS:
                ts, values, fs, mask = loaded[(kind, pos)]
                f, p = welch(values[a][mask], fs=fs, nperseg=512)
                axs[row, col].semilogy(f, p, color=COLORS[pos], label=pos, linewidth=1)
            axs[row, col].set_title(f"{kind} / {a} 軸", fontsize=10)
            axs[row, col].grid(alpha=0.3)
            axs[row, col].set_xlim(0, 100)
    axs[1, 1].set_xlabel("周波数 [Hz]")
    axs[0, 0].set_ylabel("PSD [(m/s²)²/Hz]")
    axs[1, 0].set_ylabel("PSD [(m/s²)²/Hz]")
    axs[0, 0].legend()
    fig.suptitle("event 区間内の周波数スペクトル(Welch、0〜100Hz) 後ろ vs 前")
    fig.tight_layout()
    fig.savefig(out / "psd.png", dpi=110)
    plt.close(fig)

    # 3. 段差のバースト
    bursts = {pos: burst_stats(loaded[("step", pos)][0], loaded[("step", pos)][1]["z"],
                               loaded[("step", pos)][3], loaded[("step", pos)][2]) for pos in POSITIONS}
    fig, axs = plt.subplots(1, 3, figsize=(13, 5))
    boxes(axs[0], {p: bursts[p]["peak_abs"].to_numpy() for p in POSITIONS}, "バーストのピーク |z|", "[m/s²]")
    boxes(axs[1], {p: bursts[p]["duration_s"].to_numpy() for p in POSITIONS}, "バーストの持続時間(ピークの20%超)", "[s]")
    boxes(axs[2], {p: bursts[p]["after_s"].to_numpy() for p in POSITIONS}, "ピーク後の余韻の長さ", "[s]")
    fig.suptitle("段差(z 軸): バーストごとの比較(1秒以上離れた包絡線ピーク、閾値10m/s²)")
    fig.tight_layout()
    fig.savefig(out / "step_bursts.png", dpi=110)
    plt.close(fig)
    pd.concat({p: bursts[p] for p in POSITIONS}, names=["position"]).to_csv(out / "step_bursts.csv")

    # 4. |a| の累積分布
    fig, axs = plt.subplots(2, 3, figsize=(14, 7), sharey=True)
    for row, kind in enumerate(PAIRS):
        for col, a in enumerate(AXES):
            for pos in POSITIONS:
                ts, values, fs, mask = loaded[(kind, pos)]
                v = np.sort(np.abs(values[a][mask]))
                axs[row, col].plot(v, np.arange(1, len(v) + 1) / len(v), color=COLORS[pos], label=pos)
            axs[row, col].set_title(f"{kind} / {a} 軸", fontsize=10)
            axs[row, col].grid(alpha=0.3)
    axs[1, 1].set_xlabel("|加速度| [m/s²]")
    axs[0, 0].set_ylabel("累積割合")
    axs[1, 0].set_ylabel("累積割合")
    axs[0, 0].legend()
    fig.suptitle("event 区間内の |加速度| の累積分布 後ろ vs 前")
    fig.tight_layout()
    fig.savefig(out / "abs_ecdf.png", dpi=110)
    plt.close(fig)

    print(pd.concat({p: bursts[p].describe().loc[["count", "50%", "mean", "std"]] for p in POSITIONS}).round(2))


if __name__ == "__main__":
    main()
