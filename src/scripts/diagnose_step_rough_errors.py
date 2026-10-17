"""step と rough の取り違えの原因を、波形から調べる(後ろ固定のみ、10.3+10.4、xyz18・SVM・2.0秒)。

10.12 の 3 章で、間違いが 3 セッション(step の 20261003172637・20261004172046、rough の 20261003170139)に
集中していることが分かった。その原因を、波形と窓の特徴量から確かめる。

予測は analyze_confusion_presented の windows_pred.csv(①xyz18_2.0s、SVM)を使う。

出力:
  session_overview.png : 全イベントセッションの z と水平の大きさ(√(x²+y²))の波形と、窓ごとの予測
  zoom_<session>.png   : 間違えた窓と、正しく判定された窓の波形の拡大
  feature_scatter.png  : 窓の特徴量の散布図(セッションごとに色分け)
  session_stats.csv    : セッションごとの、揺れの大きさ・衝撃の回数・正解率
  pass_stats.csv       : 段差の通過(強い衝撃)ごとの大きさと、そのあとの揺れ
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

from src.scripts.evaluate_103_burst_segment import build_run
from src.scripts.plot_boxplots_103 import build_intervals
from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"

BAD = {"20261003172637": "dansa", "20261004172046": "dansa", "20261003170139": "dekobo"}
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}
COLOR = {"flat": "#9e9e9e", "dansa": "#1f77b4", "dekobo": "#d62728"}
WINDOW_S = 2.0
BURST_HEIGHT = 10.0  # 10.12 の 2.6 節と同じ(z の 30ms RMS 包絡線のピーク)
SMOOTH_S = 0.030


def load_session(run_dir: Path) -> dict:
    w = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    ts = w["timestamp"].to_numpy(float)
    z = w["accWorldZ"].to_numpy(float) - GRAVITY_MPS2
    h = np.hypot(w["accWorldX"].to_numpy(float), w["accWorldY"].to_numpy(float))
    fs = 1000.0 / np.median(np.diff(ts))
    env = np.sqrt(uniform_filter1d(z**2, size=max(1, int(SMOOTH_S * fs)), mode="nearest"))
    peaks, props = find_peaks(env, height=BURST_HEIGHT, distance=int(0.5 * fs))
    return {"ts": ts, "t": (ts - ts[0]) / 1000.0, "z": z, "h": h, "fs": fs, "env": env,
            "peaks": peaks, "peak_h": props["peak_heights"], "intervals": build_intervals(run_dir, 500.0)}


def plot_overview(sessions: dict, preds: pd.DataFrame, path: Path) -> None:
    names = [s for s in sessions if preds["session"].eq(s).any() and preds.loc[preds["session"] == s, "label"].iloc[0] != "flat"]
    names.sort(key=lambda s: (preds.loc[preds["session"] == s, "label"].iloc[0], s not in BAD, s))
    fig, axes = plt.subplots(len(names), 1, figsize=(18, 2.3 * len(names)), sharex=True)
    for ax, s in zip(axes, names):
        d, p = sessions[s], preds[preds["session"] == s]
        label = p["label"].iloc[0]
        ax.plot(d["t"], d["h"], color="#ff7f0e", lw=0.4, alpha=0.7, label="水平 √(x²+y²)")
        ax.plot(d["t"], d["z"], color="black", lw=0.4, label="z")
        ax.plot(d["t"][d["peaks"]], d["z"][d["peaks"]] * 0 + 45, "v", color="purple", ms=4)
        for a, b in d["intervals"].get(label, []):
            ax.axvspan((a - d["ts"][0]) / 1000, (b - d["ts"][0]) / 1000, color=COLOR[label], alpha=0.06)
        # 窓ごとの予測を下に帯で描く(窓の中央の 1/4 幅。窓は 1/4 ずつずれるので隙間なく並ぶ)
        for st, pr in zip(p["t_rel_ms"] / 1000.0, p["pred"]):
            c = st + WINDOW_S / 2
            ax.axvspan(c - WINDOW_S / 8, c + WINDOW_S / 8, ymin=0, ymax=0.08, color=COLOR[pr])
        recall = (p["label"] == p["pred"]).mean()
        mark = "【間違いが多い】" if s in BAD else ""
        ax.set_title(f"{mark}{s}（正解 {NAME[label]}、再現率 {recall:.2f}、強い衝撃 {len(d['peaks'])} 回）",
                     fontsize=10, loc="left")
        ax.set_ylim(-40, 50)
        ax.set_ylabel("m/s²")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("時間 [s]（下の帯：窓ごとの予測。灰=flat、青=step、赤=rough。▼：強い衝撃）")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_zoom(sessions: dict, preds: pd.DataFrame, s: str, ref: str, path: Path, n: int = 4) -> None:
    """間違えた窓(上段)、同じセッションの正しい窓(中段)、相手のクラスの代表セッションの窓(下段)。"""
    p = preds[preds["session"] == s]
    label = p["label"].iloc[0]
    wrong = p[(p["pred"] != label) & (p["pred"] != "flat")]
    right = p[p["pred"] == label]
    other = preds[(preds["session"] == ref) & (preds["pred"] == preds["label"])]
    rng = np.random.default_rng(0)
    rows = [(f"{s}：{NAME[label]} を {NAME[wrong['pred'].iloc[0]] if len(wrong) else '-'} と間違えた窓", s, wrong),
            (f"{s}：正しく {NAME[label]} と判定された窓", s, right),
            (f"参考 {ref}：正しく {NAME[other['label'].iloc[0]]} と判定された窓", ref, other)]
    fig, axes = plt.subplots(3, n, figsize=(4.2 * n, 8.5), sharey=True)
    for r, (title, sess, sub) in enumerate(rows):
        idx = rng.choice(len(sub), size=min(n, len(sub)), replace=False) if len(sub) else []
        for k, ax in enumerate(axes[r]):
            if k >= len(idx):
                ax.axis("off")
                continue
            st = sub["t_rel_ms"].iloc[sorted(idx)[k]] / 1000.0
            d = sessions[sess]
            m = (d["t"] >= st) & (d["t"] < st + WINDOW_S)
            ax.plot(d["t"][m] - st, d["h"][m], color="#ff7f0e", lw=0.5, alpha=0.8)
            ax.plot(d["t"][m] - st, d["z"][m], color="black", lw=0.5)
            ax.set_title(f"t={st:.1f}s", fontsize=9)
            ax.set_ylim(-40, 50)
        axes[r][0].set_ylabel(title, fontsize=8)
    fig.suptitle("黒=z、橙=水平 √(x²+y²)（m/s²）。横軸は窓の中の時間 [s]", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def pass_stats(sessions: dict, labels: dict) -> pd.DataFrame:
    """強い衝撃ごとの大きさ、そのあとの 0.3〜1.0 秒の揺れ(衝撃後の静かさ)、次の衝撃までの間隔。"""
    rows = []
    for s, d in sessions.items():
        fs, z, h = d["fs"], d["z"], d["h"]
        for i, (k, ph) in enumerate(zip(d["peaks"], d["peak_h"])):
            lo, hi = k + int(0.3 * fs), k + int(1.0 * fs)
            if hi >= len(z):
                continue
            nxt = (d["peaks"][i + 1] - k) / fs if i + 1 < len(d["peaks"]) else np.nan
            rows.append({"session": s, "label": labels[s], "t": d["t"][k], "peak": ph,
                         "after_z_rms": float(np.sqrt(np.mean(z[lo:hi] ** 2))),
                         "after_h_rms": float(np.sqrt(np.mean(h[lo:hi] ** 2))), "gap_next_s": nxt})
    return pd.DataFrame(rows)


def plot_scatter(feats: pd.DataFrame, path: Path) -> None:
    pairs = [("z_rms", "z_kurt"), ("y_range", "x_kurt"), ("x_rms", "y_rms")]
    ev = feats[feats["label"] != "flat"]
    fig, axes = plt.subplots(1, len(pairs), figsize=(6 * len(pairs), 5.2))
    for ax, (fx, fy) in zip(axes, pairs):
        for (s, lab), sub in ev.groupby(["session", "label"]):
            bad = s in BAD
            ax.scatter(sub[fx], sub[fy], s=14 if bad else 7, alpha=0.8 if bad else 0.25,
                       color=COLOR[lab], marker="x" if bad else "o",
                       label=f"{NAME[lab]} {s}" if bad else None)
        ax.set_xlabel(fx)
        ax.set_ylabel(fy)
        ax.set_xscale("log")
    axes[0].scatter([], [], color=COLOR["dansa"], s=7, label="step（その他）")
    axes[0].scatter([], [], color=COLOR["dekobo"], s=7, label="rough（その他）")
    axes[0].legend(fontsize=8)
    fig.suptitle("窓の特徴量（2.0 秒窓）。×：間違いが多い 3 セッション、●：その他", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="後ろ固定のみのセッションを並べたディレクトリ")
    parser.add_argument("--pred", default="data/analysis/20261013_confusion_presented/windows_pred.csv")
    parser.add_argument("--output-dir", default="data/analysis/20261017_step_rough_errors")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    preds = pd.read_csv(args.pred)
    preds = preds[(preds["case"] == "①xyz18_2.0s") & (preds["model"] == "SVM")].copy()
    preds["session"] = preds["session"].astype(str)
    sessions = {d.name: load_session(d) for d in run_dirs}
    labels = preds.groupby("session")["label"].first().to_dict()

    plot_overview(sessions, preds, out / "session_overview.png")
    refs = {"dansa": "20261003172331", "dekobo": "20261004170739"}  # 相手のクラスで再現率の高いセッション
    for s, lab in BAD.items():
        plot_zoom(sessions, preds, s, refs[lab], out / f"zoom_{s}.png")

    feats = pd.concat([build_run(d, WINDOW_S, 5) for d in run_dirs], ignore_index=True)
    feats["session"] = feats["session"].astype(str)
    plot_scatter(feats, out / "feature_scatter.png")

    ps = pass_stats(sessions, labels)
    ps.to_csv(out / "pass_stats.csv", index=False)
    rows = []
    for s, d in sessions.items():
        p = preds[preds["session"] == s]
        f = feats[feats["session"] == s]
        q = ps[ps["session"] == s]
        rows.append({"session": s, "label": NAME[labels[s]], "bad": s in BAD, "n_win": len(p),
                     "recall": (p["label"] == p["pred"]).mean(),
                     **{f"to_{NAME[c]}": int((p["pred"] == c).sum()) for c in NAME},
                     "z_rms_med": f["z_rms"].median(), "h_rms_med": np.sqrt(f["x_rms"] ** 2 + f["y_rms"] ** 2).median(),
                     "z_kurt_med": f["z_kurt"].median(), "x_kurt_med": f["x_kurt"].median(),
                     "n_bursts": len(q), "burst_peak_med": q["peak"].median(),
                     "after_z_rms_med": q["after_z_rms"].median(), "after_h_rms_med": q["after_h_rms"].median(),
                     "gap_next_med": q["gap_next_s"].median()})
    stats = pd.DataFrame(rows).sort_values(["label", "recall"])
    stats.to_csv(out / "session_stats.csv", index=False)
    pd.set_option("display.width", 250)
    print(stats.round(2).to_string(index=False))

    preds = add_activity(preds, sessions)
    preds.to_csv(out / "windows_activity.csv", index=False)
    print("\n[揺れている時間の割合ごとの再現率]\n", activity_table(preds).round(2).to_string(index=False))
    feats = feats.merge(preds[["session", "t_rel_ms", "act", "imp"]], on=["session", "t_rel_ms"], how="left")
    clean = run_cleaning(feats)
    clean.to_csv(out / "label_cleaning.csv", index=False)
    print("\n[ラベルを付け直したとき]\n", clean.round(3).to_string(index=False))


def add_activity(preds: pd.DataFrame, sessions: dict) -> pd.DataFrame:
    """窓の中で揺れている時間の割合(act)と、強い衝撃を含むか(imp)。

    揺れ: z の 100ms RMS 包絡線が、flat セッションの包絡線の 99 パーセンタイルを超えている時間。
    ラベルは使わない(閾値は flat の波形だけから決める)。
    """
    env = {s: np.sqrt(uniform_filter1d(d["z"] ** 2, size=max(1, int(0.1 * d["fs"])), mode="nearest"))
           for s, d in sessions.items()}
    flat = preds.loc[preds["label"] == "flat", "session"].iloc[0]
    thr = float(np.percentile(env[flat], 99))
    act, imp = [], []
    for s, st in zip(preds["session"], preds["t_rel_ms"] / 1000.0):
        d = sessions[s]
        m = (d["t"] >= st) & (d["t"] < st + WINDOW_S)
        act.append(float(np.mean(env[s][m] > thr)))
        imp.append(bool(d["env"][m].max() > BURST_HEIGHT))
    print(f"揺れの閾値 {thr:.2f} m/s²")
    return preds.assign(act=act, imp=imp)


def activity_table(preds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ev = preds[preds["label"] != "flat"].assign(
        act_bin=lambda d: pd.cut(d["act"], [-0.01, 0.1, 0.3, 0.5, 1.0], labels=["≦10%", "10-30%", "30-50%", ">50%"]))
    for (lab, b), sub in ev.groupby(["label", "act_bin"], observed=True):
        bad = sub["session"].isin(BAD)
        rows.append({"true": NAME[lab], "act": b, "n": len(sub), "recall": (sub["pred"] == lab).mean(),
                     **{f"to_{NAME[c]}": int((sub["pred"] == c).sum()) for c in NAME if c != lab},
                     "n_bad_sessions": int(bad.sum())})
    return pd.DataFrame(rows)


def run_cleaning(feats: pd.DataFrame) -> pd.DataFrame:
    """ラベルの粗さの影響の見積もり。中身の無い窓を除いて、学習・評価をやり直す(xyz18)。"""
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.metrics import confusion_matrix
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.model_selection import cross_val_predict

    from src.scripts.evaluate_103_baseline import LABELS
    from src.scripts.evaluate_103_baseline import models
    from src.scripts.evaluate_103_burst_segment import BASIC
    from src.scripts.evaluate_103_burst_segment import SHAPE
    from src.scripts.evaluate_103_burst_segment import summarize
    from src.scripts.evaluate_related_features import cols

    feature_cols = cols("xyz", BASIC + SHAPE)
    rough_ok = ~((feats["label"] == "dekobo") & (feats["act"] <= 0.1))
    step_ok = ~((feats["label"] == "dansa") & ~feats["imp"].astype(bool))
    good = ~feats["session"].isin(BAD)
    cases = {
        "そのまま": rough_ok | True,
        "rough: 揺れ≦10%の窓を除く": rough_ok,
        "step: 強い衝撃なしの窓を除く": step_ok,
        "両方除く": rough_ok & step_ok,
        "間違いの多い3セッションを除く": good,
        "両方除く + 3セッションを除く": rough_ok & step_ok & good,
    }
    rows = []
    for case, mask in cases.items():
        d = feats[mask]
        sr = d[d["label"] != "flat"]
        for model_name, model in models().items():
            pred = cross_val_predict(model, d[feature_cols], d["label"], groups=d["group"], cv=LeaveOneGroupOut())
            sr_pred = cross_val_predict(model, sr[feature_cols], sr["label"], groups=sr["group"], cv=LeaveOneGroupOut())
            cm = confusion_matrix(d["label"], pred, labels=LABELS)
            rows.append({"case": case, "model": model_name, "n": len(d), **summarize(d["label"], pred),
                         "sr_bal_acc": balanced_accuracy_score(sr["label"], sr_pred),
                         "n_step_to_flat": cm[1, 0], "n_step_to_rough": cm[1, 2], "n_rough_to_step": cm[2, 1]})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
