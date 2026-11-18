"""rough の再現率(core・2.0 秒で 0.91)が低い原因を調べ、ラベルと特徴量の直し方を比べる。

1. 間違いの内訳: 混同行列、セッションごと、通過の中の位置、間違えた窓の特徴量
2. 間違いの多いセッション(20261101143126、凸凹の場所 D)の診断
   - ラベルの区間の中に、flat と同じくらい静かな窓がどれだけあるか(セッションごと)
   - 傾きの範囲(tilt_range)の分布。同じ場所 D を 51 kg の人が走った 20261101142926 とも比べる
   - 51 kg の人のセッション(場所 D を含む)を学習に足すと、143126 が当たるようになるか
3. ラベルの直し方: 凸凹の区間の終わりを「揺れの終わり」(区間の中で z の 100 ms RMS 包絡線が、汎用の flat の 99 パーセンタイル
   7.72 m/s² を最後に超えた時刻)にする。学習もテストも新しいラベルの場合と、学習だけ新しいラベル(テストは今のラベル)の場合
4. 特徴量: 「揺れが窓の中で続いているか、単発か」を表すバースト系の特徴量(10.5 の burst_ratio・burst_duty・n_peaks)を、
   z・h・g の 3 軸で 1 個ずつ core に足す。2.0・1.0 秒、体重のテスト、日を分けたテストで確かめる

条件は e20261104_onset_label_eval の shift_1 と同じ(汎用・68〜69 kg の 16 セッション、方針A、START を 1 秒ずらす、core、
SVM、セッション単位の LOGO)。51 kg の 6 セッションは、2 の確認と、体重のテストだけに使う。

出力(data/analysis/20261105_rough_error_analysis/):
  confusion.csv、rough_by_session.csv、calm_windows.csv、tilt_by_session.csv、label_fix.csv、features.csv、transfer.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import ACTIVE_PERCENTILE
from src.experiments.e20261031_button_lag import add_activity
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_gyro_features import gyro_window_features
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261105_rough_error_analysis"
CORE = ["z_rms", "z_kurt", "h_std", "h_crest", "tilt_range"]  # ゼミ資料 131-017 の core(暫定)
D_SESSION = "20261101143126"  # 凸凹の場所 D(69 kg)
D_SESSION_51 = "20261101142926"  # 同じ場所 D(51 kg)
CANDIDATES = [f"{a}_{f}" for f in ("burst_ratio", "burst_duty", "n_peaks") for a in ("z", "h", "g")]
WINDOWS_S = [2.0, 1.0]


def intervals(passes: pd.DataFrame, rough_end: str) -> tuple[dict, list]:
    """START を 1 秒ずらした区間。rough_end="offset" なら、凸凹の終わりを揺れの終わりにする。"""
    ok = passes[~passes["cancelled"]]
    out = {"dansa": [], "dekobo": []}
    for r in ok.itertuples():
        a, b = r.start_ms + 1000.0, r.stop_ms
        if r.kind == "dekobo" and rough_end == "offset":
            if pd.isna(r.offset_ms):
                continue
            b = min(b, r.offset_ms)
        if a < b:
            out[r.kind].append((float(a), float(b)))
    dropped = [(float(x), float(y)) for x, y in passes.loc[passes["cancelled"], ["start_ms", "stop_ms"]].to_numpy()]
    return out, dropped


def build(meta: pd.DataFrame, threshold: float, window_s: float) -> pd.DataFrame:
    """窓ごとの特徴量と、今のラベル(label)・凸凹の終わりを揺れの終わりにしたラベル(label_off)。"""
    frames = []
    for s, d, k, w in zip(meta["session_id"], meta["day"], meta["kind"], meta["weight_kg"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        win = window_features(sess, window_s)
        win = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
        if k == "flat":
            lab = lab_off = label_windows(win, window_s, k, {}, [])
            pass_id = rel = pd.Series(np.nan, index=win.index)
        else:
            passes = add_activity(load_passes(run_dir), sess, threshold)
            lab = label_windows(win, window_s, k, *intervals(passes, "stop"))
            lab_off = label_windows(win, window_s, k, *intervals(passes, "offset"))
            pass_id, rel = [], []
            ok = passes[~passes["cancelled"]]
            for st in win["start_ms"]:
                c = st + window_s * 500.0
                hit = ok[(ok["start_ms"] + 1000.0 <= c) & (c <= ok["stop_ms"])]
                if len(hit):
                    a, b = hit["start_ms"].iloc[0] + 1000.0, hit["stop_ms"].iloc[0]
                    pass_id.append(hit["pass_id"].iloc[0])
                    rel.append((c - a) / (b - a))
                else:
                    pass_id.append(np.nan)
                    rel.append(np.nan)
            pass_id, rel = pd.Series(pass_id, index=win.index), pd.Series(rel, index=win.index)
        frames.append(win.assign(label=lab, label_off=lab_off, group=s, day=d, weight=w, kind=k,
                                 pass_id=pass_id, rel=rel))
    df = pd.concat(frames, ignore_index=True)
    return df[df["label"].notna() | df["label_off"].notna()].reset_index(drop=True)


def recall(y: pd.Series, pred: np.ndarray) -> dict:
    m = confusion_matrix(y, pred, labels=LABELS)
    out = {f"r_{DISPLAY[k]}": float(m[i, i] / m[i].sum()) for i, k in enumerate(LABELS)}
    out["mean"] = float(np.mean(list(out.values())))
    out.update({"step_rough": int(m[1, 2] + m[2, 1]), "rough_to_flat": int(m[2, 0]), "rough_to_step": int(m[2, 1]),
                "flat_to_rough": int(m[0, 2])})
    return out


def logo(df: pd.DataFrame, feats: list[str], train_label: str = "label", test_label: str = "label",
         extra_train: pd.DataFrame | None = None) -> tuple[pd.Series, np.ndarray]:
    """セッション単位の LOGO。extra_train は、どの fold でも学習に足す(テストはしない)。"""
    test = df[df[test_label].notna()]
    pred = pd.Series(index=test.index, dtype=object)
    for g in test["group"].unique():
        tr = df[(df["group"] != g) & df[train_label].notna()]
        x, y = tr[feats], tr[train_label]
        if extra_train is not None:
            ex = extra_train[extra_train["label"].notna()]
            x, y = pd.concat([x, ex[feats]]), pd.concat([y, ex["label"]])
        model = models()["SVM"].fit(x, y)
        idx = test.index[test["group"] == g]
        pred[idx] = model.predict(test.loc[idx, feats])
    return test[test_label], pred.to_numpy()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    meta = load_meta(["10.31", "11.1"], "standard", None)
    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]) if k == "flat"]
    threshold = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))
    print(f"揺れの閾値: {threshold:.2f} m/s²")

    feat_rows, label_rows, transfer_rows = [], [], []
    for window_s in WINDOWS_S:
        df_all = build(meta, threshold, window_s)
        heavy = df_all["weight"].isin([68, 69])
        h = df_all[heavy & df_all["label"].notna()].reset_index(drop=True)
        light = df_all[~heavy & df_all["label"].notna()].reset_index(drop=True)

        # 1. 間違いの内訳(core)
        y, pred = h["label"], cross_val_predict(models()["SVM"], h[CORE], h["label"], groups=h["group"],
                                                cv=LeaveOneGroupOut())
        h["pred"] = pred
        if window_s == 2.0:
            conf = pd.DataFrame(confusion_matrix(y, pred, labels=LABELS),
                                index=[DISPLAY[k] for k in LABELS], columns=[DISPLAY[k] for k in LABELS])
            conf.to_csv(OUT / "confusion.csv")
            print("\n混同行列(行 = 正解、core、2.0 秒)\n", conf)
            r = h[h["label"] == "dekobo"]
            by = r.groupby("group").apply(lambda g: pd.Series({
                "n": len(g), "recall": float((g["pred"] == "dekobo").mean()),
                "to_flat": int((g["pred"] == "flat").sum()), "to_step": int((g["pred"] == "dansa").sum())}),
                include_groups=False)
            by.to_csv(OUT / "rough_by_session.csv")
            print("\n凸凹のセッションごと\n", by)
            err = r[r["pred"] != "dekobo"]
            pos = pd.cut(r["rel"], [0, 0.2, 0.8, 1.0], include_lowest=True)
            print("\n通過の中の位置(0 = START + 1 秒、1 = STOP)ごとの、凸凹の窓数と間違い")
            print(pd.DataFrame({"windows": pos.value_counts(), "errors": pos[err.index].value_counts()}).sort_index())
            kind = np.where(r["group"] == D_SESSION, "D_", "他の凸凹_") + np.where(r["pred"] == "dekobo", "正解",
                                                                               "→" + r["pred"].map(DISPLAY))
            print("\n間違えた窓の特徴量(中央値)")
            comp = pd.concat([r.assign(k=kind), h[h["label"] != "dekobo"].assign(k=h["label"].map(DISPLAY))])
            print(comp.groupby("k")[CORE + ["h_burst_ratio", "z_burst_duty"]].median().round(2).T)

            # 2. 場所 D の診断
            flat_q90 = float(h.loc[h["label"] == "flat", "z_rms"].quantile(0.9))
            rr = df_all[df_all["label"] == "dekobo"]
            calm = rr.groupby("group").apply(lambda g: pd.Series({
                "weight": g["weight"].iloc[0], "n": len(g),
                "calm": int((g["z_rms"] < flat_q90).sum()),
                "calm_ratio": float((g["z_rms"] < flat_q90).mean()),
                "calm_after_offset": int(((g["z_rms"] < flat_q90) & g["label_off"].isna()).sum())}),
                include_groups=False)
            calm.to_csv(OUT / "calm_windows.csv")
            print(f"\nflat 並みに静かな凸凹の窓(z_rms < flat の 90 パーセンタイル {flat_q90:.2f})\n", calm)
            tilt = df_all[df_all["label"].isin(["dekobo", "dansa"])].groupby(["label", "group"])["tilt_range"].describe(
                percentiles=[0.5, 0.9])[["count", "50%", "90%"]]
            tilt.to_csv(OUT / "tilt_by_session.csv")
            print("\n傾きの範囲(度)\n", tilt.round(2))
            model = models()["SVM"].fit(h[CORE], h["label"])
            for s in light.loc[light["label"] == "dekobo", "group"].unique():
                q = light[light["group"] == s]
                p = model.predict(q[CORE])
                print(f"68〜69 kg で学習 → {s}(51 kg): rough {np.mean(p == 'dekobo'):.3f}  "
                      f"→flat {int((p == 'flat').sum())}  →step {int((p == 'dansa').sum())}  / {len(q)}")
            y2, p2 = logo(h, CORE, extra_train=light)
            dm = (h.loc[y2.index, "group"] == D_SESSION).to_numpy()
            print(f"51 kg の 6 セッションを学習に足す: {recall(y2, p2)}  143126 {np.mean(p2[dm] == y2.to_numpy()[dm]):.3f}")

        # 3. ラベルの直し方(凸凹の終わり = 揺れの終わり)
        h2 = df_all[heavy].reset_index(drop=True)
        for name, tr_lab, te_lab in (("今のラベル", "label", "label"), ("揺れの終わりまで(学習・テスト)", "label_off", "label_off"),
                                     ("揺れの終わりまで(学習だけ)", "label_off", "label")):
            y3, p3 = logo(h2, CORE, tr_lab, te_lab)
            dm = (h2.loc[y3.index, "group"] == D_SESSION).to_numpy()
            row = {"window_s": window_s, "label": name, **recall(y3, p3),
                   "n_rough": int((y3 == "dekobo").sum()), "D_recall": float(np.mean(p3[dm] == y3.to_numpy()[dm]))}
            label_rows.append(row)
            print(f"{window_s:.1f}s ラベル {name}: " + " ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                                                         for k, v in row.items() if k not in ("window_s", "label")))

        # 3b. 両方のラベルで同じ窓だけをテストにする(テストが簡単になった効果を除く)。特徴量を足した場合も
        common = h2[h2["label"].notna() & (h2["label"] == h2["label_off"])].index
        for feats_name, feats in (("core", CORE), ("core+h_burst_ratio", CORE + ["h_burst_ratio"])):
            for tr_name, tr_lab in (("今のラベル", "label"), ("揺れの終わりまで", "label_off")):
                y3, p3 = logo(h2, feats, tr_lab, "label")
                keep = y3.index.isin(common)
                row = {"window_s": window_s, "label": f"共通の窓でテスト・学習は{tr_name}・{feats_name}",
                       **recall(y3[keep], p3[keep]), "n_rough": int((y3[keep] == "dekobo").sum())}
                label_rows.append(row)
                print(f"{window_s:.1f}s {row['label']}: {row['r_flat']:.3f}/{row['r_step']:.3f}/{row['r_rough']:.3f} "
                      f"s↔r {row['step_rough']} 凸凹の窓 {row['n_rough']}")
            y3, p3 = logo(h2, feats, "label_off", "label_off")
            dm = (h2.loc[y3.index, "group"] == D_SESSION).to_numpy()
            label_rows.append({"window_s": window_s, "label": f"揺れの終わりまで(学習・テスト)・{feats_name}",
                               **recall(y3, p3), "n_rough": int((y3 == "dekobo").sum()),
                               "D_recall": float(np.mean(p3[dm] == y3.to_numpy()[dm]))})
            print(f"{window_s:.1f}s 揺れの終わりまで(学習・テスト)・{feats_name}: {recall(y3, p3)}")
        if window_s == 2.0:
            print("\n順位相関(68〜69 kg のラベル付きの窓)")
            print(h[CORE + ["h_burst_ratio", "z_burst_ratio"]].corr(method="spearman")
                  .loc[["h_burst_ratio", "z_burst_ratio"]].round(2))

        # 4. 特徴量(今のラベル)
        for feats_name, feats in [("core", CORE)] + [(f"core+{c}", CORE + [c]) for c in CANDIDATES]:
            y4, p4 = logo(h, feats)
            dm = (h["group"] == D_SESSION).to_numpy()
            ok = p4 == y4.to_numpy()
            ses = pd.Series(ok).groupby(h["group"].to_numpy()).mean()
            row = {"window_s": window_s, "features": feats_name, **recall(y4, p4), "D_recall": float(ok[dm].mean())}
            feat_rows.append(row)
            if feats_name == "core":
                base_ses = ses
            else:
                diff = ses - base_ses
                row.update({"sessions_up": int((diff > 0.005).sum()), "sessions_down": int((diff < -0.005).sum())})
            print(f"{window_s:.1f}s {feats_name:18s} {row['r_flat']:.3f}/{row['r_step']:.3f}/{row['r_rough']:.3f} "
                  f"平均 {row['mean']:.3f} s↔r {row['step_rough']:3d} r→f {row['rough_to_flat']:3d} "
                  f"f→r {row['flat_to_rough']:3d} D {row['D_recall']:.3f} "
                  f"上/下 {row.get('sessions_up', '-')}/{row.get('sessions_down', '-')}", flush=True)

        # 5. 体重・日を分けたテスト(core と、候補のうち 3 個)
        both = df_all[df_all["label"].notna()].reset_index(drop=True)
        tests = {"68〜69 kg → 51 kg": (both["weight"].isin([68, 69]), ~both["weight"].isin([68, 69])),
                 "51 kg → 68〜69 kg": (~both["weight"].isin([68, 69]), both["weight"].isin([68, 69])),
                 "10.31 → 11.1(68〜69 kg)": ((both["day"] == "10.31") & both["weight"].isin([68, 69]),
                                            (both["day"] == "11.1") & both["weight"].isin([68, 69])),
                 "11.1 → 10.31(68〜69 kg)": ((both["day"] == "11.1") & both["weight"].isin([68, 69]),
                                            (both["day"] == "10.31") & both["weight"].isin([68, 69]))}
        for tname, (tr, te) in tests.items():
            for feats_name, feats in (("core", CORE), ("core+h_burst_ratio", CORE + ["h_burst_ratio"]),
                                      ("core+h_burst_duty", CORE + ["h_burst_duty"]),
                                      ("core+z_burst_ratio", CORE + ["z_burst_ratio"])):
                model = models()["SVM"].fit(both.loc[tr, feats], both.loc[tr, "label"])
                p5 = model.predict(both.loc[te, feats])
                transfer_rows.append({"window_s": window_s, "test": tname, "features": feats_name,
                                      **recall(both.loc[te, "label"], p5)})
        print(pd.DataFrame([r for r in transfer_rows if r["window_s"] == window_s])
              [["test", "features", "r_flat", "r_step", "r_rough", "step_rough"]].round(3).to_string(index=False))

        if window_s == 2.0:
            # 体重による違い: 同じ場所の組(51 kg ÷ 69 kg)のセッションの中央値
            pairs = {"凸凹 ①": ("20261101141512", "20261101141730"), "凸凹 ②(場所 D)": (D_SESSION_51, D_SESSION),
                     "段差 ①": ("20261101140355", "20261101140700"), "段差 ②": ("20261101142036", "20261101142339"),
                     "flat ①": ("20261101141139", "20261101141253"), "flat ②": ("20261101142633", "20261101143455")}
            med = both.groupby("group")[CORE + ["h_burst_ratio", "h_burst_duty", "z_burst_ratio"]].median()
            print("\n同じ場所の 51 kg ÷ 69 kg(セッションの中央値)")
            print(pd.DataFrame({k: med.loc[a] / med.loc[b] for k, (a, b) in pairs.items()}).T.round(2))
            print("クラスごとの中央値(68〜69 kg)")
            print(h.groupby("label")[["h_burst_ratio", "h_burst_duty", "z_burst_ratio"]].median().round(2))

    pd.DataFrame(label_rows).to_csv(OUT / "label_fix.csv", index=False)
    pd.DataFrame(feat_rows).to_csv(OUT / "features.csv", index=False)
    pd.DataFrame(transfer_rows).to_csv(OUT / "transfer.csv", index=False)


if __name__ == "__main__":
    main()
