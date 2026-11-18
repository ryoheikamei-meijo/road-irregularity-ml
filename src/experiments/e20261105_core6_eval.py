"""core に h_burst_ratio を足した core6(暫定)と、除いていた凸凹のセッション 20261031150809 を入れ直した評価。

core6 = core(z_rms・z_kurt・h_std・h_crest・tilt_range)+ h_burst_ratio(水平の揺れの 30 ms RMS 包絡線の最大 ÷ 中央値)。
足す理由は docs/knowledge/2026-11-05/20261105_rough_error_analysis.md の 4.3 節。

20261031150809 は configs/sessions/10.31.csv で use=no(測る人の判断で「凸凹がゆるく、単発の衝撃が混ざる」として除いた)。
設定ファイルは変えず、このスクリプトの中でだけ足す。

比べるもの: セッション 16(今)と 17(150809 を足す)× 特徴量 core と core6 × 窓 2.0・1.0 秒。
条件は e20261105_rough_error_analysis と同じ(汎用・68〜69 kg、方針A、START を 1 秒ずらす、SVM、セッション単位の LOGO)。
体重のテスト(51 kg の 6 セッションとの入れ替え)と、150809 の性質(ほかの凸凹との比較)、窓ごとの予測の図も出す。

出力(data/analysis/20261105_core6_eval/): results.csv、rough_by_session.csv、transfer.csv、rough_sessions.csv、
  pred_20261031150809.png(docs/knowledge/2026-11-05/images/ にも保存)
"""

from __future__ import annotations

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
from src.experiments.e20261105_rough_error_analysis import CORE
from src.experiments.e20261105_rough_error_analysis import build
from src.experiments.e20261105_rough_error_analysis import logo
from src.experiments.e20261105_rough_error_analysis import recall
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261105_core6_eval"
DOC_IMAGES = ROOT / "docs/knowledge/2026-11-05/images"
CORE6 = CORE + ["h_burst_ratio"]
FEATURE_SETS = {"core": CORE, "core6": CORE6}
ADDED = "20261031150809"
WINDOWS_S = [2.0, 1.0]
PRED_COLOR = {"flat": "#1baf7a", "dansa": "#2a78d6", "dekobo": "#eb6834"}


def load_meta_with_added() -> pd.DataFrame:
    meta = load_meta(["10.31", "11.1"], "standard", None)
    conf = pd.read_csv(ROOT / "configs/sessions/10.31.csv", dtype={"session_id": str})
    row = conf[conf["session_id"] == ADDED].assign(day="10.31")
    return pd.concat([meta, row], ignore_index=True)


def plot_predictions(df: pd.DataFrame, pred: pd.Series, threshold: float, path: Path) -> None:
    """150809 の通過ごとの z と、窓ごとの予測(窓の中心に印)。"""
    run_dir = ROOT / "wheelchair_data/10.31" / ADDED
    sess = load_session(run_dir)
    passes = add_activity(load_passes(run_dir), sess, threshold)
    passes = passes[~passes["cancelled"]].reset_index(drop=True)
    ts, z = sess["ts"], sess["axes"]["z"]
    w = df[(df["group"] == ADDED) & df["label"].notna()].assign(pred=pred)
    n, ncols = len(passes), 6
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(18, 1.9 * nrows), squeeze=False)
    for i, r in enumerate(passes.itertuples()):
        ax = axes[i // ncols, i % ncols]
        m = (ts >= r.start_ms - 1500) & (ts <= r.stop_ms + 1500)
        ax.plot((ts[m] - r.start_ms) / 1000.0, z[m], lw=0.3, color="#555")
        ax.axvspan(1.0, (r.stop_ms - r.start_ms) / 1000.0, color="#eb6834", alpha=0.10, lw=0)
        ax.axvline(0, color="k", lw=0.6)
        ax.axvline((r.stop_ms - r.start_ms) / 1000.0, color="k", lw=0.6)
        if pd.notna(r.offset_ms):
            ax.axvline((r.offset_ms - r.start_ms) / 1000.0, color="#7b3fa0", lw=0.9, ls="--")
        q = w[(w["start_ms"] + 1000.0 >= r.start_ms) & (w["start_ms"] + 1000.0 <= r.stop_ms)]
        for c, p in zip((q["start_ms"] + 1000.0 - r.start_ms) / 1000.0, q["pred"]):
            ax.plot([c], [25], "s", ms=4, color=PRED_COLOR[p], mec="k" if p != "dekobo" else "none", mew=0.5)
        wrong = int((q["pred"] != "dekobo").sum())
        ax.set_title(f"#{r.pass_id}  間違い {wrong}/{len(q)}", fontsize=8, loc="left",
                     color="#c0392b" if wrong else "#1f1f1e")
        ax.set_ylim(-30, 30)
        ax.tick_params(labelsize=7)
    for ax in axes.flat[n:]:
        ax.set_visible(False)
    fig.suptitle(f"{ADDED}（10.31・凸凹・68 kg・汎用）core6・2.0 秒の窓ごとの予測。■ 緑 = flat、青 = step、橙 = rough（窓の中心）。"
                 "橙の帯 = ラベルの区間（START + 1 秒〜STOP）、紫の点線 = 揺れの終わり。横軸は START からの秒", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DOC_IMAGES.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = ["Hiragino Sans", "YuGothic", "sans-serif"]
    pd.set_option("display.width", 220)
    meta = load_meta_with_added()
    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]) if k == "flat"]
    threshold = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))

    rows, sess_rows, transfer_rows = [], [], []
    for window_s in WINDOWS_S:
        df = build(meta, threshold, window_s)
        heavy = df["weight"].isin([68, 69]) & df["label"].notna()
        sets = {"16": heavy & (df["group"] != ADDED), "17(150809 を足す)": heavy}
        for set_name, mask in sets.items():
            h = df[mask].reset_index(drop=True)
            for fname, feats in FEATURE_SETS.items():
                y, p = logo(h, feats)
                row = {"window_s": window_s, "sessions": set_name, "label": "今のラベル", "features": fname,
                       **recall(y, p), "n_rough": int((y == "dekobo").sum()),
                       "added_recall": float(np.mean((p == y.to_numpy())[(h["group"] == ADDED).to_numpy()]))
                       if (h["group"] == ADDED).any() else np.nan}
                rows.append(row)
                ok = pd.Series(p == y.to_numpy(), index=y.index)
                for (g, lab), idx in h.groupby(["group", "label"]).groups.items():
                    pr = pd.Series(p, index=y.index)[idx]
                    sess_rows.append({"window_s": window_s, "sessions": set_name, "features": fname, "session": g,
                                      "label": DISPLAY[lab], "n": len(idx), "recall": float(ok[idx].mean()),
                                      "to_flat": int((pr == "flat").sum()), "to_step": int((pr == "dansa").sum()),
                                      "to_rough": int((pr == "dekobo").sum())})
                print(f"{window_s:.1f}s {set_name:16s} {fname:5s} flat/step/rough = {row['r_flat']:.3f}/"
                      f"{row['r_step']:.3f}/{row['r_rough']:.3f}  平均 {row['mean']:.3f}  s↔r {row['step_rough']:3d} "
                      f"r→f {row['rough_to_flat']:3d} r→s {row['rough_to_step']:3d} f→r {row['flat_to_rough']:3d} "
                      f"凸凹の窓 {row['n_rough']}", flush=True)
                if window_s == 2.0 and set_name.startswith("17") and fname == "core6":
                    hp = h.assign(pred=p)
                    for g in (ADDED, "20261101143126"):
                        r = hp[(hp["group"] == g) & (hp["label"] == "dekobo")]
                        pos = pd.cut(r["rel"], [0, 0.2, 0.8, 1.0], include_lowest=True,
                                     labels=["始め 20%", "中 60%", "終わり 20%"])
                        err = r["pred"] != "dekobo"
                        after = r["label_off"].isna()
                        print(f"{g}: 間違い {int(err.sum())}、うち揺れの終わりより後 {int((err & after).sum())}"
                              f"(揺れの終わりより後の窓 {int(after.sum())})")
                        print(pd.DataFrame({"窓": pos.value_counts(), "間違い": pos[err].value_counts()}).T)
                    plot_predictions(h, pd.Series(p, index=y.index)[h["group"] == ADDED], threshold,
                                     OUT / f"pred_{ADDED}.png")
                    plot_predictions(h, pd.Series(p, index=y.index)[h["group"] == ADDED], threshold,
                                     DOC_IMAGES / f"pred_{ADDED}.png")

        # 凸凹の区間の終わりを揺れの終わりにしたラベル(学習・テスト)と、どちらのラベルでも同じ窓だけのテスト(17 セッション)
        h17 = df[df["weight"].isin([68, 69])].reset_index(drop=True)
        common = h17[h17["label"].notna() & (h17["label"] == h17["label_off"])].index
        for fname, feats in FEATURE_SETS.items():
            for lname, tr_lab, te_lab, keep in (("揺れの終わりまで", "label_off", "label_off", None),
                                                ("共通の窓", "label", "label", common)):
                y, p = logo(h17, feats, tr_lab, te_lab)
                if keep is not None:
                    k = y.index.isin(keep)
                    y, p = y[k], p[k]
                added = (h17.loc[y.index, "group"] == ADDED).to_numpy()
                row = {"window_s": window_s, "sessions": "17(150809 を足す)", "label": lname, "features": fname,
                       **recall(y, p), "n_rough": int((y == "dekobo").sum()),
                       "added_recall": float(np.mean(p[added] == y.to_numpy()[added]))}
                rows.append(row)
                print(f"{window_s:.1f}s 17 {lname:8s} {fname:5s} flat/step/rough = {row['r_flat']:.3f}/"
                      f"{row['r_step']:.3f}/{row['r_rough']:.3f}  s↔r {row['step_rough']} 150809 "
                      f"{row['added_recall']:.3f} 凸凹の窓 {row['n_rough']}", flush=True)

        # 体重のテスト(17 セッション ⇄ 51 kg の 6 セッション)
        both = df[df["label"].notna()].reset_index(drop=True)
        hv = both["weight"].isin([68, 69]).to_numpy()
        for tname, tr in (("68〜69 kg(17)→ 51 kg", hv), ("51 kg → 68〜69 kg(17)", ~hv)):
            for fname, feats in FEATURE_SETS.items():
                model = models()["SVM"].fit(both.loc[tr, feats], both.loc[tr, "label"])
                p = model.predict(both.loc[~tr, feats])
                y = both.loc[~tr, "label"]
                r = recall(y, p)
                added = (both.loc[~tr, "group"] == ADDED).to_numpy()
                transfer_rows.append({"window_s": window_s, "test": tname, "features": fname, **r,
                                      "added_recall": float(np.mean(p[added] == y.to_numpy()[added]))
                                      if added.any() else np.nan})

        if window_s == 2.0:
            # 150809 の性質: ほかの凸凹のセッションと比べる
            rough = df[df["label"] == "dekobo"]
            q90 = float(df.loc[heavy & (df["label"] == "flat"), "z_rms"].quantile(0.9))
            info = rough.groupby("group").agg(
                weight=("weight", "first"), n=("z_rms", "size"), z_rms=("z_rms", "median"),
                z_kurt=("z_kurt", "median"), tilt_p50=("tilt_range", "median"),
                tilt_p90=("tilt_range", lambda v: v.quantile(0.9)), h_burst_ratio=("h_burst_ratio", "median"),
                calm_after_end=("z_rms", lambda v: int(((v < q90) & rough.loc[v.index, "label_off"].isna()).sum())))
            lags = []
            for s, d in zip(meta["session_id"], meta["day"]):
                if s not in info.index:
                    continue
                run_dir = ROOT / "wheelchair_data" / d / s
                p = add_activity(load_passes(run_dir), load_session(run_dir), threshold)
                p = p[~p["cancelled"]]
                lags.append({"group": s, "passes": len(p), "end_to_stop_s": float(p["lag_stop_s"].median()),
                             "no_onset": int(p["onset_ms"].isna().sum())})
            info = info.join(pd.DataFrame(lags).set_index("group"))
            info.to_csv(OUT / "rough_sessions.csv")
            print("\n凸凹のセッションの性質(2.0 秒、中央値)\n", info.round(2))

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "results.csv", index=False)
    by = pd.DataFrame(sess_rows)
    by.to_csv(OUT / "rough_by_session.csv", index=False)
    tr = pd.DataFrame(transfer_rows)
    tr.to_csv(OUT / "transfer.csv", index=False)
    print("\n凸凹のセッションごと(core → core6)")
    for window_s in WINDOWS_S:
        q = by[(by["window_s"] == window_s) & by["sessions"].str.startswith("17") & (by["label"] == "rough")]
        print(f"{window_s:.1f}s\n", q.pivot_table(index="session", columns="features",
                                                values=["recall", "to_flat", "to_step"]).round(3))
    print("\n体重のテスト\n", tr[["window_s", "test", "features", "r_flat", "r_step", "r_rough", "step_rough",
                              "added_recall"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
