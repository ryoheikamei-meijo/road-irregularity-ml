"""補正(A・Am)の前後で、z_rms がどう変わるかの図(e20261101_correction_eval の続き。2.0 秒窓)。

左: 同じ場所の組の比(51 kg ÷ 69 kg、従来 ÷ 汎用)。補正がうまくいけば 1 に近づく。
右: セッションごとの z_rms の中央値(ラベル付きの窓)を、条件・クラスごとに並べたもの。
    補正がうまくいけば、同じクラスは条件によらずそろい、違うクラスは離れたまま。
右の図は値の尺度が補正の前後で違う(補正なし = m/s²、補正後 = 基準の何倍か)ので、列を分けて描く。

入力: 生データ(wheelchair_data/、読むだけ)、data/analysis/20261101_correction_eval/pair_ratio.csv
出力: data/analysis/20261101_correction_eval/correction_compare.png
      (ナレッジに貼るため、docs/knowledge/2026-11-01/images/ にも保存)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_correction_eval import build
from src.experiments.e20261101_correction_eval import corrected
from src.experiments.e20261101_gyro_features import add_gyro

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_correction_eval"
DOC_IMAGES = ROOT / "docs/knowledge/2026-11-01/images"
METHODS = [("none", "補正なし"), ("A", "A：直前の静かな窓との比"), ("Am", "Am：A で止まっている窓を除く")]
CONDS = [("68-69kg", "汎用・68〜69 kg"), ("51kg", "汎用・51 kg"), ("original", "従来・68 kg")]
COND_COLOR = {"68-69kg": "#2a78d6", "51kg": "#eb6834", "original": "#1baf7a"}  # 既定のパレットの 1〜3 番目
KINDS = [("flat", "flat"), ("dansa", "段差"), ("dekobo", "凸凹")]
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"


def style(ax) -> None:
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


def main() -> None:
    meta = pd.concat([load_meta(["10.31", "11.1"], "standard", [68, 69, 51]),
                      load_meta(["10.31"], "original", [68])], ignore_index=True)
    meta["cond"] = np.where(meta["wheelchair"] == "original", "original",
                            np.where(meta["weight_kg"] == 51, "51kg", "68-69kg"))
    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s  # 読むだけ
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    tables = build(sessions, passes, dict(zip(meta["session_id"], meta["kind"])), 2.0)
    cond_of = dict(zip(meta["session_id"], meta["cond"]))
    med = pd.DataFrame([{"session": s, "cond": cond_of[s], "label": lab, "method": m,
                         "z_rms": float(sub["z_rms"].median())}
                        for s, tab in tables.items() for m, _ in METHODS
                        for lab, sub in corrected(tab, m).groupby("label")])

    pairs = pd.read_csv(OUT / "pair_ratio.csv")
    pairs = pairs[pairs["window_s"] == 2.0]

    plt.rcParams["font.family"] = ["Hiragino Sans", "YuGothic", "sans-serif"]
    fig = plt.figure(figsize=(15, 6.2))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.3, 1, 1, 1], wspace=0.35)

    # 左: 同じ場所の組の比
    ax = fig.add_subplot(gs[0])
    ys = np.arange(len(pairs))[::-1]
    labels = [("51÷69 kg " if w == "weight" else "従来÷汎用 ") + p for w, p in zip(pairs["which"], pairs["place"])]
    # 右の図の色(条件)と混ざらないよう、補正の方法は色に加えて形でも区別する
    method_style = {"none": ("#6b6a63", "o"), "A": ("#e87ba4", "s"), "Am": ("#c98500", "D")}
    for (m, name), dy in zip(METHODS, (0.22, 0.0, -0.22)):
        color, marker = method_style[m]
        ax.scatter(pairs[f"z_rms_{m}_ratio"], ys + dy, s=46, color=color, marker=marker, edgecolors="white",
                   linewidths=1.2, zorder=3, label=name)
    ax.axvline(1.0, color=INK, lw=1.0, zorder=2)
    ax.text(1.0, 1.01, "1 ＝ 同じになる", transform=ax.get_xaxis_transform(), ha="center", va="bottom",
            fontsize=9, color=INK)
    ax.set_yticks(ys, labels, fontsize=9, color=INK)
    ax.axhline(ys[5] - 0.5, color=GRID, lw=0.8)
    ax.set_xscale("log")
    ax.set_xticks([0.5, 0.7, 1.0, 1.5, 2.0], ["0.5", "0.7", "1", "1.5", "2"])
    ax.xaxis.set_minor_formatter(plt.NullFormatter())
    ax.set_xlim(0.45, 2.3)
    ax.set_title("同じ場所の z_rms の比（中央値）", fontsize=11, color=INK, loc="left", pad=22)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, -0.06), frameon=False, fontsize=9, ncol=1)
    style(ax)

    # 右: 条件・クラスごとのセッションの中央値
    rng = np.random.default_rng(0)
    for i, (m, name) in enumerate(METHODS):
        ax = fig.add_subplot(gs[i + 1])
        for yk, (lab, lab_name) in enumerate(KINDS[::-1]):
            for (c, _), dy in zip(CONDS, (0.22, 0.0, -0.22)):
                v = med[(med["method"] == m) & (med["label"] == lab) & (med["cond"] == c)]["z_rms"].to_numpy()
                if len(v):
                    ax.scatter(v, yk + dy + rng.uniform(-0.04, 0.04, len(v)), s=40, color=COND_COLOR[c],
                               edgecolors="white", linewidths=1.2, zorder=3)
        ax.set_yticks(range(len(KINDS)), [k[1] for k in KINDS[::-1]], fontsize=11, color=INK)
        for y in (0.5, 1.5):
            ax.axhline(y, color=GRID, lw=0.8)
        ax.set_xlim(left=0)
        unit = "z_rms（m/s²）" if m == "none" else "z_rms（基準の何倍か）"
        ax.set_title(f"{name}\n{unit}", fontsize=10, color=INK, loc="left")
        style(ax)
    handles = [plt.Line2D([], [], marker="o", ls="", ms=7, color=COND_COLOR[c], label=n) for c, n in CONDS]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.99, 1.0), ncol=3, frameon=False, fontsize=9)
    fig.suptitle("補正の前後での上下の揺れの大きさ（2.0 秒窓）", x=0.01, ha="left", fontsize=12, color=INK)
    fig.text(0.01, 0.005, "右 3 つ：点 1 つ = 1 セッションの、ラベル付きの窓の中央値。従来の車椅子には flat のセッションが無い。",
             fontsize=9, color=MUTED)
    fig.subplots_adjust(left=0.13, right=0.98, top=0.84, bottom=0.2)
    DOC_IMAGES.mkdir(parents=True, exist_ok=True)
    for path in (OUT / "correction_compare.png", DOC_IMAGES / "20261101_correction_compare.png"):
        fig.savefig(path, dpi=160)
        print(path)


if __name__ == "__main__":
    main()
