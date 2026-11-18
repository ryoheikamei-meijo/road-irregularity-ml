"""ボタンの区間(START〜STOP)と、START を 1 秒切り詰めた区間を、波形の上で確かめる図を作る。

汎用の車椅子(standard)の、評価に使っている(use=yes)段差・凸凹のセッションすべて(10.31・11.1、体重 51・68・69 kg)。
flat のセッションはボタンの区間が無いので対象外。

セッションごとに 1 枚:
  上段     : セッション全体の上下の加速度 z と、ボタンの区間(切り詰めた 1 秒 = 灰色の斜線、残した区間 = 色)
  下段     : 通過ごとの拡大(START = 0 秒にそろえる)。z(灰)、100 ms RMS 包絡線(橙)、揺れの閾値(赤点線)、
             揺れ始め(緑の線。ボタンの区間の中で包絡線が閾値を初めて超えた時刻。e20261031_button_lag と同じ定義)
             揺れ始めが START から 1 秒より前の通過は、題を赤にする(切り詰めで、揺れの始まりが区間から外れている)
揺れの閾値は、汎用の車椅子の flat のセッション(use=yes)の包絡線の 99 パーセンタイル(e20261031_button_lag と同じ考え方)。

出力(data/analysis/20261104_label_shift_check/):
  <session_id>.png : セッションごとの図
  passes.csv       : 通過ごとの揺れ始め・揺れの終わりと、START・STOP からの時間
  summary.csv      : セッションごとのまとめ
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.experiments.e20261031_button_lag import ACTIVE_PERCENTILE
from src.experiments.e20261031_button_lag import add_activity
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_combined_eval import load_meta

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261104_label_shift_check"
SHIFT_S = 1.0
PRE_S, POST_S = 1.5, 1.0  # 拡大の範囲: START の 1.5 秒前 〜 STOP の 1 秒後
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"
KIND_COLOR = {"dansa": "#2a78d6", "dekobo": "#eb6834"}
KIND_NAME = {"dansa": "段差", "dekobo": "凸凹"}
TRIM_COLOR = "#9a9890"
ALERT = "#c0392b"


def style(ax) -> None:
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=7)


def shade(ax, start_s: float, stop_s: float, kind: str, cancelled: bool) -> None:
    """ボタンの区間を塗る。切り詰めた 1 秒は灰色の斜線、残した区間は種類の色。取り消した通過は灰色だけ。"""
    if cancelled:
        ax.axvspan(start_s, stop_s, color=TRIM_COLOR, alpha=0.25, lw=0)
        return
    cut = min(start_s + SHIFT_S, stop_s)
    ax.axvspan(start_s, cut, facecolor="none", edgecolor=TRIM_COLOR, hatch="////", lw=0)
    ax.axvspan(start_s, cut, color=TRIM_COLOR, alpha=0.12, lw=0)
    if cut < stop_s:
        ax.axvspan(cut, stop_s, color=KIND_COLOR[kind], alpha=0.18, lw=0)


def plot_session(s: str, meta_row: pd.Series, sess: dict, passes: pd.DataFrame, threshold: float, path: Path) -> None:
    ts, z, env = sess["ts"], sess["axes"]["z"], sess["env"]
    t = (ts - ts[0]) / 1000.0
    ok = passes.reset_index(drop=True)
    n = len(ok)
    ncols = 6
    nrows = math.ceil(n / ncols)
    dur_max = float(((ok["stop_ms"] - ok["start_ms"]) / 1000.0).max())
    ylim = float(np.ceil(np.percentile(np.abs(z), 99.9) / 5.0) * 5.0)

    fig = plt.figure(figsize=(18, 2.6 + 1.9 * nrows))
    gs = fig.add_gridspec(nrows + 1, ncols, height_ratios=[1.3] + [1.0] * nrows, hspace=0.75, wspace=0.18)

    # 上段: セッション全体
    ax = fig.add_subplot(gs[0, :])
    ax.plot(t, z, color="#4a4a46", lw=0.25)
    for r in ok.itertuples():
        shade(ax, (r.start_ms - ts[0]) / 1000.0, (r.stop_ms - ts[0]) / 1000.0, r.kind, r.cancelled)
    ax.set_xlim(t[0], t[-1])
    ax.set_ylim(-ylim, ylim)
    ax.set_ylabel("z [m/s²]", color=MUTED, fontsize=8)
    ax.set_xlabel("セッションの始めからの時間 [秒]", color=MUTED, fontsize=8)
    style(ax)
    kind = meta_row["kind"]
    ax.set_title(f"{s}（{meta_row['day']}・{KIND_NAME['dansa' if kind == 'step' else 'dekobo']}・"
                 f"{meta_row['weight_kg']:g} kg・汎用）  通過 {n} 回", fontsize=11, color=INK, loc="left")

    # 下段: 通過ごと(START = 0)
    for i, r in enumerate(ok.itertuples()):
        a = fig.add_subplot(gs[1 + i // ncols, i % ncols])
        lo, hi = r.start_ms - PRE_S * 1000.0, r.start_ms + (dur_max + POST_S) * 1000.0
        m = (ts >= lo) & (ts <= hi)
        x = (ts[m] - r.start_ms) / 1000.0
        a.plot(x, z[m], color="#8a8a84", lw=0.35)
        a.plot(x, env[m], color="#e08a2c", lw=0.9)
        a.axhline(threshold, color=ALERT, ls=":", lw=0.7)
        dur = (r.stop_ms - r.start_ms) / 1000.0
        shade(a, 0.0, dur, r.kind, r.cancelled)
        a.axvline(0.0, color=INK, lw=0.7)
        a.axvline(dur, color=INK, lw=0.7)
        title_color = INK
        if r.cancelled:
            label = f"#{r.pass_id} 取り消し"
            title_color = MUTED
        elif np.isnan(r.lag_start_s):
            label = f"#{r.pass_id} {r.sub}  揺れ始めなし"
            title_color = MUTED
        else:
            a.axvline(r.lag_start_s, color="#1baf7a", lw=1.3)
            label = f"#{r.pass_id} {r.sub}  揺れ始め +{r.lag_start_s:.2f} s"
            if r.lag_start_s < SHIFT_S:
                title_color = ALERT
        a.set_title(label, fontsize=7.5, color=title_color, loc="left")
        a.set_xlim(-PRE_S, dur_max + POST_S)
        a.set_ylim(-ylim, ylim)
        style(a)

    fig.text(0.01, 0.003,
             "灰色の斜線 = START から切り詰めた 1 秒、色の帯 = 残した区間（ラベルに使う）、黒の縦線 = START・STOP、"
             f"緑 = 揺れ始め、橙 = z の 100 ms RMS 包絡線、赤点線 = 揺れの閾値 {threshold:.2f} m/s²。"
             "題が赤 = 揺れ始めが START から 1 秒より前（切り詰めで揺れの始まりが外れる）。下段の横軸は START からの秒",
             fontsize=8, color=MUTED)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = ["Hiragino Sans", "YuGothic", "sans-serif"]
    meta = load_meta(["10.31", "11.1"], "standard", None)

    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]) if k == "flat"]
    threshold = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))
    print(f"揺れの閾値: {threshold:.2f} m/s²（汎用の flat {len(flat_env)} セッションの包絡線の {ACTIVE_PERCENTILE:g} パーセンタイル）")

    rows = []
    for _, row in meta[meta["kind"] != "flat"].iterrows():
        s, d = row["session_id"], row["day"]
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        passes = add_activity(load_passes(run_dir), sess, threshold)
        passes = passes.sort_values("start_ms").reset_index(drop=True)
        plot_session(s, row, sess, passes, threshold, OUT / f"{s}.png")
        rows.append(passes.assign(session=s, day=d, weight_kg=row["weight_kg"]))
        print(f"{s} 通過 {len(passes)}", flush=True)

    allp = pd.concat(rows, ignore_index=True)
    allp.to_csv(OUT / "passes.csv", index=False)
    ok = allp[~allp["cancelled"]]
    summary = ok.groupby(["session", "day", "weight_kg", "kind"]).agg(
        passes=("pass_id", "size"),
        no_onset=("lag_start_s", lambda v: int(v.isna().sum())),
        lag_median=("lag_start_s", "median"),
        lag_min=("lag_start_s", "min"),
        lag_max=("lag_start_s", "max"),
        onset_before_1s=("lag_start_s", lambda v: int((v < SHIFT_S).sum())),
        onset_after_2s=("lag_start_s", lambda v: int((v > 2.0).sum())),
        stop_lag_median=("lag_stop_s", "median"),
    ).reset_index()
    summary.to_csv(OUT / "summary.csv", index=False)
    pd.set_option("display.width", 220)
    print(summary.round(2).to_string(index=False))
    print("\n全体:", f"通過 {len(ok)}、揺れ始め < 1 秒 {int((ok['lag_start_s'] < SHIFT_S).sum())}、"
          f"> 2 秒 {int((ok['lag_start_s'] > 2.0).sum())}、揺れ始めなし {int(ok['lag_start_s'].isna().sum())}")
    print(ok.groupby("sub")["lag_start_s"].describe(percentiles=[0.1, 0.5, 0.9]).round(2))


if __name__ == "__main__":
    main()
