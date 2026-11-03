"""周波数帯ごとの、体重・車椅子による振幅の比と、クラスの振幅の図(e20261101_band_features の続き)。

左: 同じ場所の組の、z の振幅の比(51 kg ÷ 69 kg、従来 ÷ 汎用)を帯域ごとに。1 に近い帯域は、体重・車椅子によらない。
右: クラスごとの z の振幅(汎用・68〜69 kg のセッションの中央値)を帯域ごとに。その帯域でクラスを区別できるか。

入力: data/analysis/20261101_band_features/band_ratio.csv、band_class.csv(先に e20261101_band_features を実行する)
出力: data/analysis/20261101_band_features/band_ratio.png(docs/knowledge/2026-11-01/images/ にも保存)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_band_features"
DOC_IMAGES = ROOT / "docs/knowledge/2026-11-01/images"
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"
KIND_COLOR = {"段差": "#2a78d6", "凸凹": "#eb6834", "flat": "#1baf7a"}  # 既定のパレットの 1〜3 番目
CLASS_COLOR = {"flat": "#1baf7a", "step": "#2a78d6", "rough": "#eb6834"}
CLASS_NAME = {"flat": "flat", "step": "段差", "rough": "凸凹"}


def centers(cols: list[str]) -> np.ndarray:
    return np.array([np.sqrt(float(c.split("-")[0]) * float(c.split("-")[1])) for c in cols])


def style(ax) -> None:
    ax.set_xscale("log")
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64, 128], ["1", "2", "4", "8", "16", "32", "64", "128"])
    ax.xaxis.set_minor_formatter(plt.NullFormatter())
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_xlabel("周波数 [Hz]", color=MUTED, fontsize=9)


def main() -> None:
    ratio = pd.read_csv(OUT / "band_ratio.csv")
    cls = pd.read_csv(OUT / "band_class.csv").set_index("kind")
    bands = [c for c in ratio.columns if "-" in c]
    x = centers(bands)

    plt.rcParams["font.family"] = ["Hiragino Sans", "YuGothic", "sans-serif"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), gridspec_kw={"width_ratios": [1, 1, 1]})
    for ax, (which, title, resonance) in zip(axes[:2], [
            ("weight", "体重：51 kg ÷ 69 kg（同じ場所）", (16, 32)),
            ("chair", "車椅子：従来 ÷ 汎用（同じ場所）", (30, 60))]):
        ax.axvspan(8, 16, color="#cde2fb", alpha=0.7, lw=0, zorder=0)
        ax.axvspan(*resonance, color="#f4d9cc", alpha=0.7, lw=0, zorder=0)
        ax.axhline(1.0, color=INK, lw=1.0)
        for _, r in ratio[ratio["which"] == which].iterrows():
            kind = next(k for k in KIND_COLOR if r["place"].startswith(k))
            ax.plot(x, r[bands].to_numpy(float), color=KIND_COLOR[kind], lw=1.6, marker="o", ms=4, alpha=0.9)
        ax.set_yscale("log")
        ax.set_yticks([0.5, 0.7, 1, 1.5, 2, 3, 4], ["0.5", "0.7", "1", "1.5", "2", "3", "4"])
        ax.yaxis.set_minor_formatter(plt.NullFormatter())
        ax.set_ylim(0.4, 4.5)
        style(ax)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        ax.text(np.sqrt(8 * 16), 0.42, "8〜16 Hz", ha="center", va="bottom", fontsize=9, color="#184f95")
        ax.text(np.sqrt(resonance[0] * resonance[1]), 4.2, "固有振動数\nの帯域", ha="center", va="top", fontsize=9,
                color="#a3401c")
    axes[0].set_ylabel("振幅の比（1 = 同じ）", color=MUTED, fontsize=9)
    handles = [plt.Line2D([], [], color=c, lw=1.6, marker="o", ms=4, label=k) for k, c in KIND_COLOR.items()]
    axes[1].legend(handles=handles, loc="lower right", frameon=False, fontsize=9)

    ax = axes[2]
    ax.axvspan(8, 16, color="#cde2fb", alpha=0.7, lw=0, zorder=0)
    for k in ["flat", "step", "rough"]:
        ax.plot(x, cls.loc[k, bands].to_numpy(float), color=CLASS_COLOR[k], lw=1.8, marker="o", ms=4,
                label=CLASS_NAME[k])
    ax.set_yscale("log")
    ax.set_yticks([0.03, 0.1, 0.3, 1, 3], ["0.03", "0.1", "0.3", "1", "3"])
    ax.yaxis.set_minor_formatter(plt.NullFormatter())
    style(ax)
    ax.set_title("クラスごとの振幅（汎用・68〜69 kg）", fontsize=11, color=INK, loc="left")
    ax.set_ylabel("帯域の振幅 [m/s²]", color=MUTED, fontsize=9)
    ax.legend(loc="upper left", frameon=False, fontsize=9)

    fig.suptitle("上下の揺れの、周波数帯ごとの比（2.0 秒窓、ラベル付きの窓のパワースペクトルの中央値）", x=0.01, ha="left",
                 fontsize=12, color=INK)
    fig.text(0.01, 0.01, "青い帯 = 8〜16 Hz（体重・車椅子の比が 1 に近く、クラスの差は大きい）。オレンジの帯 = その車椅子の固有振動数の帯域（汎用 15〜30 Hz、従来 30〜60 Hz）。",
             fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94), w_pad=3)
    DOC_IMAGES.mkdir(parents=True, exist_ok=True)
    for path in (OUT / "band_ratio.png", DOC_IMAGES / "20261101_band_ratio.png"):
        fig.savefig(path, dpi=160)
        print(path)


if __name__ == "__main__":
    main()
