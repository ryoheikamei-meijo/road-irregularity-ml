"""窓 2.0 秒のほうが 1.0 秒より精度が高い理由を、評価の作り方の違いと分けて確かめる。

1. テストする窓をそろえる: 中心の時刻が同じで、1.0 秒・2.0 秒の両方で同じラベルになる窓だけで再現率を比べる
2. 1.0 秒の判断を 2 つ合わせる: 2.0 秒の窓を前半・後半の 1.0 秒の窓に分け、SVM のスコア(decision_function)を平均する。
   2.0 秒に追いつけば、効いているのは「1 回の判断に使うデータの量」。追いつかなければ、2.0 秒の窓でしか見えない特徴が効いている
3. 特徴量ごとの AUC(flat ↔ rough、step ↔ rough、flat ↔ step)。2 でそろえた窓で比べる
4. ラベルのノイズ: 段差・凸凹のラベルなのに、窓の中の z の包絡線が一度も揺れの閾値を超えない(flat と同じくらい静かな)窓の割合

条件は e20261105_rough_error_analysis と同じ(汎用・68〜69 kg の 16 セッション、方針A、START を 1 秒ずらす、core、SVM、
セッション単位の LOGO)。1 の窓は 1.0 秒の窓の 1/4(0.25 秒)ずつずれているので、2.0 秒の窓の中心と一致するものがある。

出力(data/analysis/20261107_window_length_check/):
  recall.csv、auc.csv、calm.csv、passes_covered.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from src.experiments.e20261031_button_lag import ACTIVE_PERCENTILE
from src.experiments.e20261031_button_lag import add_activity
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_gyro_features import gyro_window_features
from src.experiments.e20261105_rough_error_analysis import CORE
from src.experiments.e20261105_rough_error_analysis import ROOT
from src.experiments.e20261105_rough_error_analysis import intervals
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

OUT = ROOT / "data/analysis/20261107_window_length_check"
WINDOWS_S = [1.0, 2.0]
PAIRS = [("flat", "dekobo"), ("dansa", "dekobo"), ("flat", "dansa")]


def build_all(meta: pd.DataFrame, threshold: float, window_s: float) -> pd.DataFrame:
    """ラベルの無い窓も含めて、全部の窓の特徴量・ラベル・窓の中の包絡線の最大・通過の番号を返す。"""
    frames = []
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        win = window_features(sess, window_s)
        win = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
        pass_id = pd.Series(np.nan, index=win.index)
        if k == "flat":
            lab = label_windows(win, window_s, k, {}, [])
        else:
            passes = add_activity(load_passes(run_dir), sess, threshold)
            lab = label_windows(win, window_s, k, *intervals(passes, "stop"))
            ok = passes[~passes["cancelled"]]
            for i, st in win["start_ms"].items():
                c = st + window_s * 500.0
                hit = ok[(ok["start_ms"] <= c) & (c <= ok["stop_ms"])]
                if len(hit):
                    pass_id[i] = hit["pass_id"].iloc[0]
        ts, env = sess["ts"], sess["env"]
        lo = np.searchsorted(ts, win["start_ms"].to_numpy())
        hi = np.searchsorted(ts, win["start_ms"].to_numpy() + window_s * 1000.0)
        env_max = [float(env[a:b].max()) if b > a else np.nan for a, b in zip(lo, hi)]
        frames.append(win.assign(label=lab, group=s, env_max=env_max, pass_id=pass_id,
                                 center_ms=win["start_ms"] + window_s * 500.0))
    return pd.concat(frames, ignore_index=True)


def logo_scores(df: pd.DataFrame) -> pd.DataFrame:
    """セッション単位の LOGO。ラベルのある窓で学習し、テストのセッションは全部の窓(ラベルの無い窓も)を予測する。"""
    scores = np.full((len(df), len(LABELS)), np.nan)
    pred = np.empty(len(df), dtype=object)
    labeled = df["label"].notna().to_numpy()
    for g in df["group"].unique():
        test = (df["group"] == g).to_numpy()
        tr = labeled & ~test
        model = models()["SVM"].fit(df.loc[tr, CORE], df.loc[tr, "label"])
        order = [list(model.classes_).index(c) for c in LABELS]
        scores[test] = model.decision_function(df.loc[test, CORE])[:, order]
        pred[test] = model.predict(df.loc[test, CORE])
    out = pd.DataFrame(scores, columns=[f"s_{c}" for c in LABELS], index=df.index)
    out["pred"] = pred
    return out


def recall_row(y: pd.Series, pred: pd.Series) -> dict:
    row = {}
    for c in LABELS:
        m = (y == c).to_numpy()
        row[f"r_{DISPLAY[c]}"] = float((pred.to_numpy()[m] == c).mean())
        row[f"n_{DISPLAY[c]}"] = int(m.sum())
    sr = ((y == "dansa") & (pred == "dekobo")) | ((y == "dekobo") & (pred == "dansa"))
    row["step_rough"] = int(sr.sum())
    return row


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    meta = load_meta(["10.31", "11.1"], "standard", None)
    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]) if k == "flat"]
    threshold = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))
    heavy = meta[meta["weight_kg"].isin([68, 69])]

    w = {}
    for window_s in WINDOWS_S:
        df = build_all(heavy, threshold, window_s)
        df = df.join(logo_scores(df))
        w[window_s] = df
        print(f"{window_s} 秒: 窓 {len(df)}、ラベルあり {int(df['label'].notna().sum())}", flush=True)
    one, two = w[1.0], w[2.0]
    s_cols = [f"s_{c}" for c in LABELS]

    # predict と decision_function の argmax がどれだけ一致するか(2 で argmax を使うため)
    for window_s, df in w.items():
        argmax = np.array(LABELS)[np.nanargmax(df[s_cols].to_numpy(), axis=1)]
        print(f"{window_s} 秒: predict と argmax の一致 {float((argmax == df['pred']).mean()):.4f}")

    rows = []

    # 0. ふだんの評価(それぞれのラベルのある窓すべて)
    for window_s, df in w.items():
        lab = df[df["label"].notna()]
        rows.append({"test_set": "each_own", "method": f"{window_s:g}s", **recall_row(lab["label"], lab["pred"])})

    # 1. 中心の時刻が同じで、両方で同じラベルになる窓
    key = ["group", "center_ms"]
    m = two[two["label"].notna()].merge(
        one[one["label"].notna()][key + ["label", "pred"]].rename(columns={"label": "label_1", "pred": "pred_1"}),
        on=key, how="inner")
    m = m[m["label"] == m["label_1"]]
    rows.append({"test_set": "same_center", "method": "2s", **recall_row(m["label"], m["pred"])})
    rows.append({"test_set": "same_center", "method": "1s", **recall_row(m["label"], m["pred_1"])})

    # 2. 2.0 秒の窓 = 前半の 1.0 秒 + 後半の 1.0 秒。スコアを平均する
    a = one[["group", "start_ms"] + s_cols + ["pred", "label"]]
    first = a.rename(columns={c: f"{c}_a" for c in s_cols + ["pred", "label"]})
    second = a.assign(start_ms=a["start_ms"] - 1000.0).rename(columns={c: f"{c}_b" for c in s_cols + ["pred", "label"]})
    t = two[two["label"].notna()].merge(first, on=["group", "start_ms"]).merge(second, on=["group", "start_ms"])
    sa, sb = t[[f"{c}_a" for c in s_cols]].to_numpy(), t[[f"{c}_b" for c in s_cols]].to_numpy()
    t["pred_avg"] = np.array(LABELS)[np.argmax((sa + sb) / 2.0, axis=1)]
    t["pred_2s_argmax"] = np.array(LABELS)[np.argmax(t[s_cols].to_numpy(), axis=1)]
    t["pred_1a"] = np.array(LABELS)[np.argmax(sa, axis=1)]
    t["pred_1b"] = np.array(LABELS)[np.argmax(sb, axis=1)]
    print(f"2 の窓: 2.0 秒の窓 {int(two['label'].notna().sum())} のうち {len(t)}")
    for name, col in [("2s", "pred_2s_argmax"), ("1s_avg_of_2", "pred_avg"),
                      ("1s_first_half", "pred_1a"), ("1s_second_half", "pred_1b")]:
        rows.append({"test_set": "2s_windows_split", "method": name, **recall_row(t["label"], t[col])})
    rec = pd.DataFrame(rows)
    rec.to_csv(OUT / "recall.csv", index=False)
    print(rec.round(3).to_string(index=False))

    # 3. 特徴量ごとの AUC(1 の窓。0.5 から離れているほど分かれる。向きは問わない)
    m1 =m.merge(one[key + CORE].rename(columns={f: f"{f}_1" for f in CORE}), on=key)
    auc_rows = []
    for f in CORE:
        for p, q in PAIRS:
            sub = m1[m1["label"].isin([p, q])]
            y = (sub["label"] == q).astype(int)
            r = {"feature": f, "pair": f"{DISPLAY[p]}-{DISPLAY[q]}"}
            for name, col in [("1s", f"{f}_1"), ("2s", f)]:
                v = roc_auc_score(y, sub[col])
                r[f"auc_{name}"] = float(max(v, 1.0 - v))
            auc_rows.append(r)
    auc = pd.DataFrame(auc_rows)
    auc.to_csv(OUT / "auc.csv", index=False)
    print(auc.round(3).to_string(index=False))

    # 4. ラベルのノイズ(静かな窓)と、静かな窓・揺れている窓ごとの再現率
    calm_rows = []
    for window_s, df in w.items():
        lab = df[df["label"].isin(["dansa", "dekobo"])]
        for c in ("dansa", "dekobo"):
            sub = lab[lab["label"] == c]
            calm = sub["env_max"] < threshold
            calm_rows.append({"window_s": window_s, "class": DISPLAY[c], "windows": len(sub),
                              "calm_frac": float(calm.mean()),
                              "recall_calm": float((sub.loc[calm, "pred"] == c).mean()) if calm.any() else np.nan,
                              "recall_active": float((sub.loc[~calm, "pred"] == c).mean())})
    calm_df = pd.DataFrame(calm_rows)
    calm_df.to_csv(OUT / "calm.csv", index=False)
    print(calm_df.round(3).to_string(index=False))

    # 通過ごとに、ラベルのある窓が 1 つでもあるか
    cov = []
    for window_s, df in w.items():
        ev = df[df["pass_id"].notna()]
        g = ev.groupby(["group", "pass_id"])["label"].apply(lambda v: v.notna().any())
        cov.append({"window_s": window_s, "passes": int(len(g)), "passes_without_window": int((~g).sum())})
    cov_df = pd.DataFrame(cov)
    cov_df.to_csv(OUT / "passes_covered.csv", index=False)
    print(cov_df.to_string(index=False))

    # 2.0 秒で窓が 1 つも無い通過(短い通過)の、1.0 秒の窓の成績
    ev2 = two[two["pass_id"].notna()].groupby(["group", "pass_id"])["label"].apply(lambda v: v.notna().any())
    missing = ev2[~ev2].reset_index()[["group", "pass_id"]]
    sub = one[one["label"].notna()].merge(missing, on=["group", "pass_id"])
    print(f"2.0 秒で窓の無い通過 {len(missing)} 回の、1.0 秒の窓 {len(sub)}:")
    print(sub.groupby("label").apply(lambda d: pd.Series({"windows": len(d), "recall": (d["pred"] == d.name).mean()}),
                                     include_groups=False).round(3).to_string())


if __name__ == "__main__":
    main()
