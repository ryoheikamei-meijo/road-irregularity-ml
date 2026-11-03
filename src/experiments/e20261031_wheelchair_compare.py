"""10.31 の 2 台の車椅子(original: 元々使っていた車椅子、standard: 新しく買った汎用の車椅子)で、
加速度に差があるかを調べる。混ぜて学習してよいかの判断に使う。

続けて測ったセッションは同じ路面なので(測定者に確認)、そのペアで直接比べる。

1. 通過ごとの揺れ(e20261031_button_lag と同じ「揺れている区間」= 揺れ始め〜揺れの終わり)
   z・水平の大きさ h の rms とピーク(100ms RMS 包絡線の最大)、z の尖度。
2. 車椅子自体の振動: START から揺れ始めまで(段差・凸凹に着く前の平坦な走行)の z・h の rms。
3. モデル: xyz18・2.0 秒窓・方針A(ボタンの区間のまま)で、
   - standard のセッション(+ flat)だけで学習し、original のセッションを予測した再現率
   - standard のセッションを LOGO で予測した再現率(同じ車椅子の中での基準)
   の差を見る。

出力(data/analysis/20261031_wheelchair_compare/):
  pass_stats.csv / pair_summary.csv / pair_boxplots.png / cross_chair.csv / pair_waveforms.png
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
from scipy.stats import kurtosis
from scipy.stats import mannwhitneyu
from sklearn.base import clone
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import FEATURES
from src.experiments.e20261031_button_lag import add_activity
from src.experiments.e20261031_button_lag import intervals_for
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import models

plt.rcParams["font.family"] = "Hiragino Sans"

ROOT = Path(__file__).resolve().parents[2]
# 同じ路面で続けて測ったペア(名前, 種類, standard のセッション, original のセッション)
PAIRS = [
    ("段差①", "dansa", ["20261031142102"], ["20261031142344", "20261031142508"]),
    ("凸凹①", "dekobo", ["20261031143004"], ["20261031142814"]),
    ("段差②", "dansa", ["20261031144423"], ["20261031144130"]),
    ("凸凹②", "dekobo", ["20261031145017"], ["20261031145240"]),
]
STATS = ["z_rms", "z_peak", "h_rms", "h_peak", "z_kurt", "approach_z_rms", "approach_h_rms"]
STAT_LABEL = {
    "z_rms": "z の rms", "z_peak": "z のピーク", "h_rms": "水平の rms", "h_peak": "水平のピーク",
    "z_kurt": "z の尖度", "approach_z_rms": "着く前の走行 z の rms", "approach_h_rms": "着く前の走行 水平の rms",
}
WINDOW_S = 2.0


def pass_stats(sess: dict, passes: pd.DataFrame) -> pd.DataFrame:
    ts, fs = sess["ts"], sess["fs"]
    z = sess["axes"]["z"]
    h = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
    h = h - np.median(h)  # 水平の大きさの下駄(姿勢の誤差で残る重力分など)を引く
    env_h = np.sqrt(uniform_filter1d(h**2, size=max(1, int(0.1 * fs)), mode="nearest"))
    rows = []
    for r in passes[~passes["cancelled"] & passes["onset_ms"].notna()].itertuples():
        act = (ts >= r.onset_ms) & (ts <= r.offset_ms)
        app = (ts >= r.start_ms) & (ts < r.onset_ms)
        if act.sum() < 10:
            continue
        rows.append({
            "kind": r.kind, "pass_id": r.pass_id, "sub": r.sub,
            "z_rms": float(np.sqrt(np.mean(z[act] ** 2))), "z_peak": float(sess["env"][act].max()),
            "h_rms": float(np.sqrt(np.mean(h[act] ** 2))), "h_peak": float(env_h[act].max()),
            "z_kurt": float(kurtosis(z[act])),
            # 着く前の走行は 0.3 秒以上あるときだけ
            "approach_z_rms": float(np.sqrt(np.mean(z[app] ** 2))) if app.sum() > 0.3 * fs else np.nan,
            "approach_h_rms": float(np.sqrt(np.mean(h[app] ** 2))) if app.sum() > 0.3 * fs else np.nan,
        })
    return pd.DataFrame(rows)


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """original(a) が standard(b) より大きい確率 − 小さい確率。|δ| ≥ 0.47 で大きい差とされる。"""
    diff = a[:, None] - b[None, :]
    return float((np.sum(diff > 0) - np.sum(diff < 0)) / diff.size)


def plot_pairs(stats: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(len(STATS), len(PAIRS), figsize=(3.2 * len(PAIRS), 2.3 * len(STATS)))
    for j, (name, *_rest) in enumerate(PAIRS):
        for i, stat in enumerate(STATS):
            ax = axes[i, j]
            d = stats[stats["pair"] == name]
            data = [d.loc[d["wheelchair"] == c, stat].dropna() for c in ("standard", "original")]
            ax.boxplot(data, tick_labels=[f"汎用\n(n={len(data[0])})", f"従来\n(n={len(data[1])})"])
            if i == 0:
                ax.set_title(name)
            if j == 0:
                ax.set_ylabel(STAT_LABEL[stat], fontsize=8)
            ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_pair_waveforms(sessions: dict, passes: pd.DataFrame, path: Path) -> None:
    """ペアごとに、各車椅子の通過を 3 つずつ、揺れ始めを 0 にそろえて並べる。"""
    fig, axes = plt.subplots(len(PAIRS), 2, figsize=(14, 2.6 * len(PAIRS)), sharey=True)
    for i, (name, _kind, std, orig) in enumerate(PAIRS):
        for j, (chair, ids) in enumerate([("汎用", std), ("従来", orig)]):
            ax = axes[i, j]
            p = passes[passes["session"].isin(ids) & ~passes["cancelled"] & passes["onset_ms"].notna()].head(3)
            for k, r in enumerate(p.itertuples()):
                sess = sessions[r.session]
                m = (sess["ts"] >= r.onset_ms - 1000) & (sess["ts"] <= r.onset_ms + 4000)
                t = (sess["ts"][m] - r.onset_ms) / 1000.0 + k * 5.5
                ax.plot(t, sess["axes"]["z"][m], lw=0.4, color="black")
            ax.set_title(f"{name} {chair}（z、通過 3 回）", fontsize=9)
            ax.set_ylim(-45, 45)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def cross_chair(sessions: dict, passes: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    kind_of = dict(zip(meta["session_id"], meta["kind"]))
    chair_of = dict(zip(meta["session_id"], meta["wheelchair"]))
    frames = []
    for s, sess in sessions.items():
        win = window_features(sess, WINDOW_S)
        p = passes[passes["session"] == s]
        intervals, dropped = intervals_for(p, "button") if len(p) else ({}, [])
        labels = label_windows(win, WINDOW_S, kind_of[s], intervals, dropped)
        frames.append(win.assign(label=labels, group=s, wheelchair=chair_of[s]).dropna(subset=["label"]))
    df = pd.concat(frames, ignore_index=True)
    std, orig = df[df["wheelchair"] == "standard"], df[df["wheelchair"] == "original"]
    rows = []
    for model_name, model in models().items():
        # 基準: standard の中での LOGO
        pred = cross_val_predict(model, std[FEATURES], std["label"], groups=std["group"], cv=LeaveOneGroupOut())
        base = std.assign(pred=pred)
        # standard だけで学習して original を予測
        fitted = clone(model).fit(std[FEATURES], std["label"])
        cross = orig.assign(pred=fitted.predict(orig[FEATURES]))
        for setting, d in [("standard 内の LOGO", base), ("standard で学習 → original を予測", cross)]:
            for t in ("dansa", "dekobo"):
                sub = d[d["label"] == t]
                rows.append({"model": model_name, "setting": setting, "true": DISPLAY[t], "n": len(sub),
                             **{f"to_{DISPLAY[q]}": float((sub["pred"] == q).mean())
                                for q in ("flat", "dansa", "dekobo")}})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", default="configs/sessions/10.31.csv")
    parser.add_argument("--data-dir", default="wheelchair_data/10.31")
    parser.add_argument("--output-dir", default="data/analysis/20261031_wheelchair_compare")
    args = parser.parse_args()

    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(ROOT / args.sessions, dtype={"session_id": str})
    chair_of = dict(zip(meta["session_id"], meta["wheelchair"]))
    sessions = {s: load_session(ROOT / args.data_dir / s) for s in meta["session_id"]}
    flat_env = np.concatenate([sessions[s]["env"] for s in meta.loc[meta["kind"] == "flat", "session_id"]])
    threshold = float(np.percentile(flat_env, 99.0))
    passes = pd.concat(
        [add_activity(load_passes(ROOT / args.data_dir / s), sessions[s], threshold).assign(session=s)
         for s in meta.loc[meta["kind"] != "flat", "session_id"]],
        ignore_index=True,
    )

    # 1・2. ペアごとの通過の統計
    stat_frames = []
    for name, kind, std, orig in PAIRS:
        for s in std + orig:
            assert chair_of[s] == ("standard" if s in std else "original"), s
            st = pass_stats(sessions[s], passes[(passes["session"] == s) & (passes["kind"] == kind)])
            stat_frames.append(st.assign(pair=name, session=s, wheelchair=chair_of[s]))
    stats = pd.concat(stat_frames, ignore_index=True)
    stats.to_csv(out / "pass_stats.csv", index=False)

    summary = []
    for name, *_rest in PAIRS:
        d = stats[stats["pair"] == name]
        for stat in STATS:
            a = d.loc[d["wheelchair"] == "original", stat].dropna().to_numpy()
            b = d.loc[d["wheelchair"] == "standard", stat].dropna().to_numpy()
            summary.append({"pair": name, "stat": stat, "n_original": len(a), "n_standard": len(b),
                            "median_original": np.median(a), "median_standard": np.median(b),
                            "ratio": np.median(a) / np.median(b), "cliffs_delta": cliffs_delta(a, b),
                            "p_mannwhitney": mannwhitneyu(a, b).pvalue})
    summary = pd.DataFrame(summary)
    summary.to_csv(out / "pair_summary.csv", index=False)
    pd.set_option("display.width", 220)
    print(summary.round(3).to_string(index=False))
    plot_pairs(stats, out / "pair_boxplots.png")
    plot_pair_waveforms(sessions, passes, out / "pair_waveforms.png")

    # 3. モデルで見た違い
    cc = cross_chair(sessions, passes, meta)
    cc.to_csv(out / "cross_chair.csv", index=False)
    print(cc.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
