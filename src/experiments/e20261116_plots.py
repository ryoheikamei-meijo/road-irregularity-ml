"""11.16 のメモ(判定モデルを ONNX にして、スマホで判定する)の図。

  tilt_reference.png : 傾きの基準ごとの再現率(e20261116_tilt_reference の results.csv)
  mean_toy.png       : 直近 30 秒の平均を基準にする模式図(作った値。計測データではない)
  timeline_<s>.png   : 1 セッションの判定の時系列(plot_timeline。メモには使っていないので、既定では作らない)
出力: docs/knowledge/2026-11-16/images/
"""

from __future__ import annotations

import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261104_onset_label_eval import make_intervals
from src.experiments.e20261116_tilt_reference import passes_with_peak

plt.rcParams["font.family"] = "Hiragino Sans"
ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "docs/knowledge/2026-11-16/images"
COLOR = {"flat": "#2a78d6", "dansa": "#eb6834", "dekobo": "#1baf7a"}
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
REF_NAME = {"session": "セッション全体の中央値\n（これまで）", "window": "2 秒の窓の中の中央値",
            "ema5": "指数移動平均\n（時定数 5 秒）", "ema30": "指数移動平均\n（時定数 30 秒、v1）",
            "mean10": "直近 10 秒の平均\n（Mizell）", "mean30": "直近 30 秒の平均\n（Mizell、v2 で採用）"}


def style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK)


def plot_tilt_reference() -> None:
    res = pd.read_csv(ROOT / "data/analysis/20261116_tilt_reference/results.csv").set_index("tilt_ref")
    refs = ["session", "window", "ema5", "ema30", "mean10", "mean30"]
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.4), sharey=True)
    for ax, cls in zip(axes, ["flat", "dansa", "dekobo"]):
        vals = [res.loc[r, f"r_{NAME[cls]}"] for r in refs]
        y = np.arange(len(refs))[::-1]
        ax.hlines(y, 0.88, vals, color=GRID, lw=2)
        ax.scatter(vals, y, s=[90 if r == "mean30" else 50 for r in refs], color=COLOR[cls], zorder=3,
                   edgecolor="white", linewidth=2)
        for v, yy in zip(vals, y):
            ax.text(v + 0.002, yy, f"{v:.3f}", va="center", fontsize=9, color=INK)
        ax.axvline(res.loc["session", f"r_{NAME[cls]}"], color=MUTED, lw=1, ls=":")
        ax.set_xlim(0.88, 1.0)
        ax.set_title(f"{NAME[cls]} の再現率", fontsize=11, color=INK)
        ax.set_yticks(np.arange(len(refs))[::-1], [REF_NAME[r] for r in refs], fontsize=9)
        ax.grid(axis="x", color=GRID, lw=0.8)
        style(ax)
    fig.suptitle("傾きの基準ごとの再現率（16 セッションのうち 1 つをテスト、残りで学習する評価を 16 回。計測2-2 の #9・#11 は除く。点線はこれまで）",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(IMG / "tilt_reference.png", dpi=150)
    plt.close(fig)


def plot_timeline(session: str, day: str, t_range: tuple[float, float] | None = None) -> None:
    run_dir = ROOT / "wheelchair_data" / day / session
    sess = load_session(run_dir)
    kt = pd.read_csv(ROOT / "data/analysis/20261116_android_parity" / f"{session}.csv")
    py = pd.read_csv(ROOT / "data/analysis/20261116_export_onnx/parity" / f"{session}.csv")
    assert np.allclose(kt["start_ms"], py["start_ms"])
    t0 = sess["ts"][0]
    iv, dr = make_intervals(passes_with_peak(run_dir, sess), "peak0.5")
    truth = label_windows(py, 2.0, "dansa", iv, dr)
    rows = [("正解のラベル（前 0.5 秒）", truth),
            ("PC：scikit-learn", py["sk_pred"]),
            ("PC：ONNX Runtime", py["onnx_pred"]),
            ("アプリの実装：Kotlin\n＋ ONNX Runtime", kt["kt_pred"])]
    # 窓は 0.5 秒ずつずれて重なるので、窓の中心の前後 0.25 秒を、その窓の判定として塗る
    center = (py["start_ms"].to_numpy() + 1000.0 - t0) / 1000.0
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(11, 4.6), sharex=True,
                                   gridspec_kw={"height_ratios": [1.3, 1.6]})
    t = (sess["ts"] - t0) / 1000.0
    ax0.plot(t, sess["axes"]["z"], lw=0.5, color=MUTED)
    for a, b in iv["dansa"]:
        ax0.axvspan((a - t0) / 1000.0, (b - t0) / 1000.0, color=COLOR["dansa"], alpha=0.15, lw=0)
    ax0.set_ylabel("z [m/s²]", color=INK)
    ax0.set_title(f"段差のセッション {session}：判定の時系列（窓 2.0 秒・0.5 秒ごと、帯は段差のラベルの区間）",
                  fontsize=11, color=INK)
    style(ax0)
    for k, (name, labels) in enumerate(rows):
        y = len(rows) - 1 - k
        for c, lab in zip(center, labels):
            if isinstance(lab, str) and lab in COLOR:
                ax1.barh(y, 0.5, left=c - 0.25, height=0.7, color=COLOR[lab], lw=0)
    ax1.set_yticks(range(len(rows))[::-1], [r[0] for r in rows], fontsize=9)
    ax1.set_xlabel("時間 [s]", color=INK)
    style(ax1)
    ax1.legend(handles=[Patch(color=COLOR[c], label=NAME[c]) for c in COLOR], ncol=3, frameon=False,
               loc="upper center", bbox_to_anchor=(0.5, -0.32), fontsize=9)
    if t_range:
        ax1.set_xlim(*t_range)
    fig.tight_layout()
    fig.savefig(IMG / f"timeline_{session}.png", dpi=150)
    plt.close(fig)


def plot_mean_toy() -> None:
    """直近 N 秒の平均を基準にする模式図。平らな道 → 段差(0.8 秒だけ 7 度) → 坂(5 度が続く) → 坂の上で段差 → 平らな道。"""
    dt = 0.01
    t = np.arange(0.0, 200.0, dt)
    tilt = np.zeros_like(t)
    for start in (20.0, 130.0):  # 段差: 0.8 秒の山
        m = (t >= start) & (t < start + 0.8)
        tilt[m] += 7.0 * np.sin(np.pi * (t[m] - start) / 0.8)
    slope = np.clip((t - 60.0) / 2.0, 0, 1) * np.clip((162.0 - t) / 2.0, 0, 1) * 5.0  # 60〜160 秒は坂
    tilt += slope

    def past_mean(span: float) -> np.ndarray:
        csum = np.concatenate([[0.0], np.cumsum(tilt)])
        lo = np.searchsorted(t, t - span, side="left")
        hi = np.arange(1, len(t) + 1)
        return (csum[hi] - csum[lo]) / (hi - lo)

    ref30, ref5 = past_mean(30.0), past_mean(10.0)
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(11, 5.4), sharex=True)
    ax0.plot(t, tilt, color=MUTED, lw=1.2, label="今の傾き（センサー）")
    ax0.plot(t, ref30, color="#eb6834", lw=2, label="基準：直近 30 秒の平均（採用）")
    ax0.plot(t, ref5, color="#2a78d6", lw=1.2, ls="--", label="基準：直近 10 秒の平均")
    for x, y, txt, ha in [(22.0, 6.6, "← 段差（0.8 秒だけ 7 度）", "left"), (100, 5.6, "坂（5 度が続く）", "center"),
                          (132.0, 11.4, "← 坂の上の段差", "left")]:
        ax0.annotate(txt, (x, y), ha=ha, fontsize=9, color=INK)
    ax0.set_ylabel("角度 [度]", color=INK)
    ax0.set_ylim(-0.5, 13)
    ax0.set_title("直近 30 秒の平均を基準にする模式図（作った値。計測データではない）", fontsize=11, color=INK)
    ax0.legend(loc="upper left", frameon=False, fontsize=9)
    ax0.grid(color=GRID, lw=0.8)
    style(ax0)
    ax1.plot(t, tilt - ref30, color="#eb6834", lw=1.5, label="基準（直近 30 秒の平均）からのずれ ＝ 測る傾き")
    ax1.set_ylabel("角度 [度]", color=INK)
    ax1.set_xlabel("時間 [s]", color=INK)
    ax1.set_ylim(-5.5, 9)
    ax1.legend(loc="upper left", frameon=False, fontsize=9)
    ax1.grid(color=GRID, lw=0.8)
    style(ax1)
    fig.tight_layout()
    fig.savefig(IMG / "mean_toy.png", dpi=150)
    plt.close(fig)
    i20, i130 = np.argmax(t >= 20.4), np.argmax(t >= 130.4)
    print(f"段差(20 s)の頂上: 基準30 {ref30[i20]:.2f} 度・基準10 {ref5[i20]:.2f} 度、ずれ {tilt[i20] - ref30[i20]:.2f} 度")
    for sec in (70, 77, 92, 120, 159):
        i = np.argmax(t >= sec)
        print(f"{sec} 秒: 基準30 {ref30[i]:.2f} 度(坂 5 度の {ref30[i] / 5 * 100:.0f}%)、基準10 {ref5[i]:.2f} 度")
    print(f"坂の上の段差(130 s)の頂上: 今 {tilt[i130]:.2f}、基準30 {ref30[i130]:.2f}、ずれ {tilt[i130] - ref30[i130]:.2f} 度")
    for sec in (175, 193):
        i = np.argmax(t >= sec)
        print(f"{sec} 秒: 基準30 {ref30[i]:.2f}、ずれ {tilt[i] - ref30[i]:.2f} 度")


def main() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    plot_mean_toy()
    plot_tilt_reference()
    shutil.copy(ROOT / "data/analysis/20261116_tilt_reference/tilt_example.png", IMG / "tilt_example.png")


if __name__ == "__main__":
    main()
