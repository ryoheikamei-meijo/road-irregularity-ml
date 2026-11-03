"""体重の違う人への汎化: 68〜69 kg の人の全セッションで学習し、51 kg の人の全セッションで評価する(10.31 + 11.1)。

条件は e20261101_gyro_features と同じ(汎用の車椅子、use=yes、方針A、START を 1 秒ずらす、SVM・RF、窓 1.0・2.0 秒)。
ただし交差検証ではなく、学習 = 68・69 kg(18 セッション)、テスト = 51 kg(6 セッション)に 1 回分ける。

加えて、通過(ラベルの区間)ごと・flat のセッションごとに、揺れと傾きの大きさを出し、体重で比べる。
11.1 は、51 kg と 69 kg の人が、同じ場所を続けて測っている(同じ種類のセッションが隣り合う)。

出力(data/analysis/20261101_weight_transfer/):
  results.csv     : 条件ごとのクラス別の再現率
  confusion.csv   : 混同行列
  by_session.csv  : テストのセッションごとの再現率
  passes.csv      : 通過ごとの揺れ・傾きの大きさと、START から揺れ始めまでのラグ
  windows.csv     : 窓ごとの特徴量と予測(2.0 秒・SVM・core5)
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from src.experiments.e20261031_button_lag import add_activity
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import intervals
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import FEATURE_SETS as GYRO_FEATURE_SETS
from src.experiments.e20261101_gyro_features import SHIFT_S
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_gyro_features import gyro_window_features
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_weight_transfer"
WINDOWS_S = [1.0, 2.0]
TRAIN_KG, TEST_KG = [68, 69], [51]
FEATURE_SETS = {k: GYRO_FEATURE_SETS[k] for k in ["hz12", "m6", "hz12+tilt2+ratio2", "core5"]}


def segment_stats(sess: dict, a: float, b: float) -> dict:
    """区間 [a, b) の揺れ・傾きの大きさ。"""
    lo, hi = np.searchsorted(sess["ts"], [a, b])
    z, h, g, tilt = (sess["axes"]["z"][lo:hi], sess["axes"]["h"][lo:hi], sess["axes"]["g"][lo:hi], sess["tilt"][lo:hi])
    return {
        "z_rms": float(np.sqrt(np.mean(z**2))), "z_peak": float(np.max(np.abs(z))),
        "z_p99": float(np.percentile(np.abs(z), 99)),
        "h_rms": float(np.sqrt(np.mean(h**2))), "g_rms": float(np.sqrt(np.mean(g**2))),
        "tilt_range": float(np.ptp(tilt)),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = load_meta(["10.31", "11.1"], "standard", TRAIN_KG + TEST_KG)
    print("使うセッション:", meta.groupby(["weight_kg", "kind"]).size().to_dict())

    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    info = meta.set_index("session_id")

    # 通過ごと・flat のセッションごとの大きさ(ラグの閾値は、学習側の flat の包絡線の 99 パーセンタイル)
    train_flat = [s for s in sessions if info.loc[s, "kind"] == "flat" and info.loc[s, "weight_kg"] in TRAIN_KG]
    threshold = float(np.percentile(np.concatenate([sessions[s]["env"] for s in train_flat]), 99.0))
    seg_rows = []
    for s, sess in sessions.items():
        base = {"session": s, "day": info.loc[s, "day"], "kind": info.loc[s, "kind"],
                "weight_kg": info.loc[s, "weight_kg"]}
        if s not in passes:
            seg_rows.append({**base, "sub": "flat", **segment_stats(sess, sess["ts"][0], sess["ts"][-1])})
            continue
        p = add_activity(passes[s], sess, threshold)
        for r in p[~p["cancelled"]].itertuples():
            seg_rows.append({**base, "sub": r.sub, "pass_id": r.pass_id, "dur_s": r.dur_s,
                             "lag_start_s": r.lag_start_s, "lag_stop_s": r.lag_stop_s,
                             **segment_stats(sess, r.start_ms + SHIFT_S * 1000.0, r.stop_ms)})
    seg = pd.DataFrame(seg_rows)
    seg.to_csv(OUT / "passes.csv", index=False)
    pd.set_option("display.width", 220)
    print("\n通過・flat ごとの大きさ(中央値):")
    print(seg.groupby(["kind", "weight_kg"])[["dur_s", "lag_start_s", "z_rms", "z_p99", "h_rms", "g_rms",
                                             "tilt_range"]].median().round(2))
    print(seg.groupby(["kind", "weight_kg"]).size())

    rows, conf_rows, sess_rows = [], [], []
    for window_s in WINDOWS_S:
        frames = []
        for s, sess in sessions.items():
            win = window_features(sess, window_s)
            win = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
            iv, dr = intervals(passes[s], SHIFT_S) if s in passes else ({}, [])
            labels = label_windows(win, window_s, info.loc[s, "kind"], iv, dr)
            frames.append(win.assign(label=labels, group=s, weight_kg=info.loc[s, "weight_kg"])
                          .dropna(subset=["label"]))
        df = pd.concat(frames, ignore_index=True)
        train, test = df[df["weight_kg"].isin(TRAIN_KG)], df[df["weight_kg"].isin(TEST_KG)].copy()
        n = test["label"].value_counts()
        print(f"\n== 窓 {window_s:.1f} 秒  テストの窓数 flat {n.get('flat', 0)} / step {n.get('dansa', 0)} / "
              f"rough {n.get('dekobo', 0)}")
        for (fs_name, features), (model_name, model) in itertools.product(FEATURE_SETS.items(), models().items()):
            pred = model.fit(train[features], train["label"]).predict(test[features])
            key = {"window_s": window_s, "features": fs_name, "model": model_name}
            row = {**key, **{f"r_{DISPLAY[k]}": float((pred[test["label"] == k] == k).mean()) for k in LABELS}}
            rows.append(row)
            m = confusion_matrix(test["label"], pred, labels=LABELS)
            for i, t in enumerate(LABELS):
                for j, q in enumerate(LABELS):
                    conf_rows.append({**key, "true": DISPLAY[t], "pred": DISPLAY[q], "n": int(m[i, j])})
            t = test.assign(pred=pred)
            for g, sub in t.groupby("group"):
                lab = sub["label"].iloc[0]
                sess_rows.append({**key, "session": g, "true": DISPLAY[lab], "n": len(sub),
                                  **{f"to_{DISPLAY[q]}": int((sub["pred"] == q).sum()) for q in LABELS},
                                  "recall": float((sub["pred"] == lab).mean())})
            if window_s == 2.0 and model_name == "SVM" and fs_name == "core5":
                t.to_csv(OUT / "windows.csv", index=False)
            print(f"{fs_name:20s} {model_name:12s} flat/step/rough = {row['r_flat']:.2f}/{row['r_step']:.2f}/"
                  f"{row['r_rough']:.2f}", flush=True)

    pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(OUT / "confusion.csv", index=False)
    pd.DataFrame(sess_rows).to_csv(OUT / "by_session.csv", index=False)


if __name__ == "__main__":
    main()
