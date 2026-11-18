"""凸凹のセッション 20261101143126(場所 D、69 kg)を、通過ごとに確かめる。

1. 通過ごとの間違い(core・SVM・2.0 秒、セッション単位の LOGO)。間違えた窓の、通過の中の位置と tilt_range
2. 間違いの多い通過 #9・#11 を除いたときの精度(テストだけ除く / 学習・テストとも除く。2.0・1.0 秒)
3. GPS の位置(時刻順)と、ボタンの区間の対応
4. 通過ごとの速度(acc.csv の speedMps = GPS の速度)と、揺れの終わりから STOP までの時間。凸凹のセッションで比べる

条件は e20261105_rough_error_analysis と同じ(汎用・68〜69 kg の 16 セッション、方針A、START を 1 秒ずらす、core、SVM)。

出力(data/analysis/20261107_session_143126_check/):
  pass_errors.csv、wrong_windows.csv、drop_passes.csv、gps_track.csv、pass_speed.csv、session_speed.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import ACTIVE_PERCENTILE
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261105_rough_error_analysis import CORE
from src.experiments.e20261105_rough_error_analysis import D_SESSION
from src.experiments.e20261105_rough_error_analysis import ROOT
from src.experiments.e20261105_rough_error_analysis import build
from src.experiments.e20261105_rough_error_analysis import recall
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import models

OUT = ROOT / "data/analysis/20261107_session_143126_check"
DROP_PASSES = [9, 11]  # 間違いの多い通過(1 章の結果を見て選んだ)
PASSES_CSV = ROOT / "data/analysis/20261104_label_shift_check/passes.csv"  # e20261104_label_shift_check の出力


def logo_pred(d: pd.DataFrame) -> np.ndarray:
    return cross_val_predict(models()["SVM"], d[CORE], d["label"], groups=d["group"], cv=LeaveOneGroupOut())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    meta = load_meta(["10.31", "11.1"], "standard", None)
    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]) if k == "flat"]
    threshold = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))

    # 1・2. 通過ごとの間違いと、#9・#11 を除いた精度
    drop_rows = []
    for window_s in (2.0, 1.0):
        df = build(meta, threshold, window_s)
        h = df[df["weight"].isin([68, 69]) & df["label"].notna()].reset_index(drop=True)
        h["pred"] = logo_pred(h)
        drop = ((h["group"] == D_SESSION) & h["pass_id"].isin(DROP_PASSES)).to_numpy()

        if window_s == 2.0:
            d = h[h["group"] == D_SESSION].copy()
            d["pred_name"] = d["pred"].map(DISPLAY)
            per = d.groupby("pass_id").agg(
                windows=("pred", "size"),
                to_flat=("pred_name", lambda v: int((v == "flat").sum())),
                to_step=("pred_name", lambda v: int((v == "step").sum())),
                tilt_range_median=("tilt_range", "median"),
            )
            per["wrong"] = per["to_flat"] + per["to_step"]
            per.to_csv(OUT / "pass_errors.csv")
            d.loc[d["pred_name"] != "rough", ["pass_id", "rel", "pred_name", "tilt_range"]].to_csv(
                OUT / "wrong_windows.csv", index=False)
            print(per.round(1).to_string())

        h2 = h[~drop].reset_index(drop=True)
        cases = {"as_is": (h, h["pred"].to_numpy()),
                 "drop_test_only": (h[~drop], h.loc[~drop, "pred"].to_numpy()),
                 "drop_train_and_test": (h2, logo_pred(h2))}
        for name, (d, p) in cases.items():
            m = (d["group"] == D_SESSION).to_numpy()
            drop_rows.append({"window_s": window_s, "case": name, "dropped_windows": int(drop.sum()),
                              **recall(d["label"], p),
                              "d_session_recall": float((p[m] == d["label"].to_numpy()[m]).mean()),
                              "d_session_windows": int(m.sum())})
    drop_df = pd.DataFrame(drop_rows)
    drop_df.to_csv(OUT / "drop_passes.csv", index=False)
    print(drop_df.round(3).to_string(index=False))

    # 3. GPS の位置(一番よく動いた向きの軸に並べる)
    run_dir = ROOT / "wheelchair_data/11.1" / D_SESSION
    g = pd.read_csv(run_dir / "gps.csv")
    t0 = float(pd.read_csv(run_dir / "session_result.csv")["started_at_ms"].iloc[0])
    lat0, lon0 = g["latitude"].median(), g["longitude"].median()
    xy = np.c_[(g["longitude"] - lon0) * 111000 * np.cos(np.radians(lat0)), (g["latitude"] - lat0) * 111000]
    xy -= xy.mean(axis=0)
    axis = np.linalg.svd(xy, full_matrices=False)[2][0]
    passes = pd.read_csv(PASSES_CSV, dtype={"session": str, "day": str})
    p = passes[(passes["session"] == D_SESSION) & ~passes["cancelled"]]
    pass_at = [next((int(r.pass_id) for r in p.itertuples() if r.start_ms <= ts <= r.stop_ms), None)
               for ts in g["timestamp_ms"]]
    track = pd.DataFrame({"t_s": (g["timestamp_ms"] - t0) / 1000.0, "pos_m": xy @ axis,
                          "speed_mps": g["speed_mps"], "accuracy_m": g["accuracy_m"], "pass_id": pass_at})
    track.to_csv(OUT / "gps_track.csv", index=False)
    print(f"GPS の中央値: {lat0:.6f}, {lon0:.6f}  軸(東, 北) = {axis.round(2)}")

    # 4. 通過ごとの速度(凸凹のセッション)
    r_passes = passes[(passes["kind"] == "dekobo") & ~passes["cancelled"]].copy()
    cache, speed = {}, []
    for r in r_passes.itertuples():
        if r.session not in cache:
            cache[r.session] = pd.read_csv(ROOT / "wheelchair_data" / r.day / r.session / "acc.csv",
                                           usecols=["timestamp", "speedMps"])
        a = cache[r.session]
        speed.append(a.loc[(a["timestamp"] >= r.start_ms) & (a["timestamp"] <= r.stop_ms), "speedMps"].median())
    r_passes["speed_mps"] = speed
    r_passes.to_csv(OUT / "pass_speed.csv", index=False)
    sess = r_passes.groupby(["session", "day", "weight_kg"]).agg(
        passes=("pass_id", "size"), speed_median=("speed_mps", "median"),
        button_s_median=("dur_s", "median"), stop_lag_median=("lag_stop_s", "median")).reset_index()
    sess["speed_zero_frac"] = [float((cache[s]["speedMps"] == 0).mean()) for s in sess["session"]]
    sess.to_csv(OUT / "session_speed.csv", index=False)
    print(sess.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
