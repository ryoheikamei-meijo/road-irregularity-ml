"""段差の上り(up)と下り(down)を別のクラスとして学習し、評価のときに step にまとめる(10.31)。

e20261031_button_lag と同じ条件(汎用の車椅子の 9 セッション、方針A、窓 1.0・2.0 秒、xyz18・m6、
SVM・RF、セッション単位の LOGO)で、次の 2 つを比べる。
  3class : flat / step / rough で学習(今まで)。step の再現率を、上りの窓と下りの窓に分けて集計する
  4class : flat / step_up / step_down / rough で学習し、予測の step_up・step_down を step にまとめる
段差の窓は、上りの通過の区間に半分以上重なれば上り、下りの通過の区間に半分以上重なれば下りとする。
(上り・下りどちらの区間とも半分に届かない段差の窓は、3class・4class とも使わない。)

出力(data/analysis/20261031_step_direction/):
  results.csv : 条件ごとの、flat / step / rough の再現率(まとめた後)と、上り・下りの窓の再現率
  confusion_4class.csv : 4class の混同行列(まとめる前)
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import FEATURE_SETS
from src.experiments.e20261031_button_lag import WINDOWS_S
from src.experiments.e20261031_button_lag import intervals_for
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.roadml.evaluation import models
from src.roadml.labeling import compute_overlap_ratio

ROOT = Path(__file__).resolve().parents[2]
CONDITIONS = ["button", "shift_1"]
LABELS_4 = ["flat", "step_up", "step_down", "rough"]
TO_3 = {"flat": "flat", "dansa": "step", "dekobo": "rough",
        "step_up": "step", "step_down": "step", "rough": "rough"}


def direction_of(win: pd.DataFrame, window_s: float, passes: pd.DataFrame, condition: str) -> list:
    """段差の窓が、上り・下りどちらの区間に半分以上重なるか(どちらでもなければ None)。"""
    result = []
    by_dir = {}
    for direction in ("up", "down"):
        sub = passes[passes["sub"].str.startswith(direction)]
        by_dir[direction] = intervals_for(sub, condition)[0]["dansa"] if len(sub) else []
    for start in win["start_ms"]:
        end = start + window_s * 1000.0
        hit = None
        for direction, intervals in by_dir.items():
            if compute_overlap_ratio(window_start_ms=start, window_end_ms=end, intervals=intervals) >= 0.5:
                hit = direction
                break
        result.append(hit)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", default="configs/sessions/10.31.csv")
    parser.add_argument("--data-dir", default="wheelchair_data/10.31")
    parser.add_argument("--output-dir", default="data/analysis/20261031_step_direction")
    args = parser.parse_args()

    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(ROOT / args.sessions, dtype={"session_id": str})
    meta = meta[meta["wheelchair"] == "standard"]  # e20261031_button_lag と同じく汎用だけ
    kind_of = dict(zip(meta["session_id"], meta["kind"]))
    sessions = {s: load_session(ROOT / args.data_dir / s) for s in meta["session_id"]}
    passes = pd.concat([load_passes(ROOT / args.data_dir / s).assign(session=s)
                        for s, k in kind_of.items() if k != "flat"], ignore_index=True)

    rows, conf_rows = [], []
    for window_s in WINDOWS_S:
        feats = {s: window_features(sess, window_s) for s, sess in sessions.items()}
        for condition in CONDITIONS:
            frames = []
            for s, win in feats.items():
                p = passes[passes["session"] == s]
                intervals, dropped = intervals_for(p, condition) if len(p) else ({}, [])
                label = label_windows(win, window_s, kind_of[s], intervals, dropped)
                direction = direction_of(win, window_s, p, condition) if len(p) else [None] * len(win)
                frames.append(win.assign(label=label, direction=direction, group=s))
            df = pd.concat(frames, ignore_index=True).dropna(subset=["label"])
            # 上り・下りが決まらない段差の窓は使わない
            df = df[(df["label"] != "dansa") | df["direction"].notna()].reset_index(drop=True)
            label4 = np.where(df["label"] == "dansa", "step_" + df["direction"].fillna(""),
                              df["label"].map({"flat": "flat", "dekobo": "rough"}))
            label3 = df["label"].map(TO_3).to_numpy()
            n = pd.Series(label4).value_counts().to_dict()
            print(f"\n== {window_s:.1f}s {condition}  窓数 {n}", flush=True)
            for (feature_set, features), (model_name, model) in itertools.product(
                    FEATURE_SETS.items(), models().items()):
                for scheme, y in [("3class", df["label"].to_numpy()), ("4class", label4)]:
                    pred = cross_val_predict(model, df[features], y, groups=df["group"], cv=LeaveOneGroupOut())
                    pred3 = pd.Series(pred).map(TO_3).to_numpy()
                    row = {"window_s": window_s, "condition": condition, "features": feature_set,
                           "model": model_name, "scheme": scheme}
                    for k in ("flat", "step", "rough"):
                        row[f"r_{k}"] = float((pred3[label3 == k] == k).mean())
                    for d in ("up", "down"):
                        mask = (label4 == f"step_{d}")
                        row[f"r_step_{d}"] = float((pred3[mask] == "step").mean())  # step と当てた割合
                        if scheme == "4class":  # 上り・下りまで当てた割合
                            row[f"r_step_{d}_exact"] = float((pred[mask] == f"step_{d}").mean())
                    rows.append(row)
                    if scheme == "4class":
                        m = confusion_matrix(y, pred, labels=LABELS_4)
                        for i, t in enumerate(LABELS_4):
                            for j, q in enumerate(LABELS_4):
                                conf_rows.append({**{k: row[k] for k in ("window_s", "condition", "features",
                                                                         "model")},
                                                  "true": t, "pred": q, "n": int(m[i, j])})
                    print(f"{feature_set:5s} {model_name:12s} {scheme}  flat/step/rough="
                          f"{row['r_flat']:.2f}/{row['r_step']:.2f}/{row['r_rough']:.2f}  "
                          f"step の内訳 up/down={row['r_step_up']:.2f}/{row['r_step_down']:.2f}"
                          + (f"  上り・下りまで当てた up/down={row['r_step_up_exact']:.2f}/"
                             f"{row['r_step_down_exact']:.2f}" if scheme == "4class" else ""), flush=True)

    pd.DataFrame(rows).to_csv(out / "results.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(out / "confusion_4class.csv", index=False)


if __name__ == "__main__":
    main()
