"""同じ場所での 51 kg と 69 kg の人の、揺れ・傾き・通過時間の比較の図(e20261101_weight_transfer の続き)。

段差・凸凹は通過ごと(START + 1 秒 〜 STOP。passes.csv)。flat は、セッションを 4 秒ずつに区切った区間ごと
(通過と長さをそろえるため)。点 1 つが 1 区間、太い印が中央値。

入力: data/analysis/20261101_weight_transfer/passes.csv(先に e20261101_weight_transfer を実行する)
出力: data/analysis/20261101_weight_transfer/paired_compare.png(ナレッジに貼るため、docs/knowledge/2026-11-01/images/ にも保存)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_weight_transfer import segment_stats

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_weight_transfer"
DOC_IMAGES = ROOT / "docs/knowledge/2026-11-01/images"
FLAT_CHUNK_S = 4.0
# 2 人が続けて測った、同じ場所の組(51 kg, 69 kg)。flat ② は同じ場所か未確認
PAIRS = [
    ("段差 ①", "20261101140355", "20261101140700"),
    ("段差 ②", "20261101142036", "20261101142339"),
    ("凸凹 ①", "20261101141512", "20261101141730"),
    ("凸凹 ②", "20261101142926", "20261101143126"),
    ("flat ①", "20261101141139", "20261101141253"),
    ("flat ②", "20261101142633", "20261101143455"),
]
PANELS = [("z_rms", "上下の揺れの大きさ\n(z の rms, m/s²)"), ("tilt_range", "車体が傾いた角度の範囲\n(度)"),
          ("dur_s", "通過にかかった時間\n(秒, START〜STOP)")]
COLOR = {51: "#2a78d6", 69: "#eb6834"}  # 既定のパレットの 1・2 番目(青・オレンジ)
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"


def flat_chunks(session_id: str) -> pd.DataFrame:
    run_dir = ROOT / "wheelchair_data/11.1" / session_id
    sess = load_session(run_dir)
    sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
    add_gyro(sess, run_dir)
    edges = np.arange(sess["ts"][0], sess["ts"][-1] - FLAT_CHUNK_S * 1000.0, FLAT_CHUNK_S * 1000.0)
    return pd.DataFrame([segment_stats(sess, a, a + FLAT_CHUNK_S * 1000.0) for a in edges])


def main() -> None:
    passes = pd.read_csv(OUT / "passes.csv", dtype={"session": str})
    data = {}
    for name, s51, s69 in PAIRS:
        for kg, s in ((51, s51), (69, s69)):
            data[(name, kg)] = flat_chunks(s) if name.startswith("flat") else passes[passes["session"] == s]

    plt.rcParams["font.family"] = ["Hiragino Sans", "YuGothic", "sans-serif"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.2), sharey=True)
    rng = np.random.default_rng(0)
    ys = np.arange(len(PAIRS))[::-1]
    for ax, (col, title) in zip(axes, PANELS):
        for y, (name, _, _) in zip(ys, PAIRS):
            if col not in data[(name, 51)] or data[(name, 51)][col].isna().all():
                ax.text(0.5, y, "（flat は通過なし）", color=MUTED, fontsize=9, va="center",
                        transform=ax.get_yaxis_transform())
                continue
            med = {}
            for kg, dy in ((51, 0.17), (69, -0.17)):
                v = data[(name, kg)][col].dropna().to_numpy()
                ax.scatter(v, y + dy + rng.uniform(-0.06, 0.06, len(v)), s=10, color=COLOR[kg], alpha=0.28,
                           linewidths=0, zorder=2)
                med[kg] = float(np.median(v))
            ax.plot([med[69], med[51]], [y - 0.17, y + 0.17], color=MUTED, lw=1.2, zorder=3)
            for kg, dy in ((51, 0.17), (69, -0.17)):
                ax.scatter(med[kg], y + dy, s=70, color=COLOR[kg], edgecolors="white", linewidths=2, zorder=4)
            ax.text(1.0, y, f"×{med[51] / med[69]:.2f}", transform=ax.get_yaxis_transform(), ha="left",
                    va="center", fontsize=10, color=INK)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=9, length=0)
        ax.set_xlim(left=0)
        for y in (1.5, 3.5):
            ax.axhline(y, color=GRID, lw=0.8)
    axes[0].set_yticks(ys, [p[0] for p in PAIRS], fontsize=11, color=INK)
    handles = [plt.Line2D([], [], marker="o", ls="", ms=8, color=COLOR[kg], label=f"{kg} kg の人")
               for kg in (51, 69)]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 1.0), ncol=2, frameon=False, fontsize=10)
    fig.suptitle("同じ場所で比べた 51 kg と 69 kg の人（11.1、汎用の車椅子）", x=0.99, ha="right", fontsize=12,
                 color=INK)
    fig.text(0.01, 0.01, "小さい点 = 通過 1 回（flat は 4 秒の区間）、大きい点 = 中央値、右の数字 = 51 kg ÷ 69 kg（中央値）",
             fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 0.97, 0.94), w_pad=4)
    DOC_IMAGES.mkdir(parents=True, exist_ok=True)
    for path in (OUT / "paired_compare.png", DOC_IMAGES / "20261101_weight_transfer_paired_compare.png"):
        fig.savefig(path, dpi=160)
        print(path)


if __name__ == "__main__":
    main()
