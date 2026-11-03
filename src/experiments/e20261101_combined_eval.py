"""複数の日のデータを合わせて、flat / step / rough の 3 クラスを評価する(10.31 + 11.1)。

条件は e20261031_button_lag と同じ(方針A、SVM・RF、セッション単位の LOGO、窓 1.0・2.0 秒)。
特徴量セットは --features で選ぶ: xyz18(3 軸)、m6(合成のみ)、hz12(水平の大きさ h = √(x²+y²) と z。ADR 2026-10-17)。
セッションは configs/sessions/<日>.csv から読み、use=yes のものだけを使う。--wheelchair・--weights で絞る。

ラベルの区間は、日ごとに START を後ろにずらせる(--shift 10.31=1.0 11.1=0.5 のように指定。既定は 0)。
ラグは日によって違う可能性があるので、日ごとに、START から揺れ始めまでの時間(e20261031_button_lag と同じ測り方)も出す。

出力(data/analysis/20261101_combined_eval/<--tag>/):
  passes.csv      : 通過ごとのラグ
  results.csv     : 条件ごとのクラス別の再現率と窓数
  confusion.csv   : 混同行列
  by_session.csv  : セッションごとの再現率
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

from src.experiments.e20261031_button_lag import FEATURE_SETS as BASE_FEATURE_SETS
from src.experiments.e20261031_button_lag import add_activity
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.features import cols

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_S = [1.0, 2.0]
FEATURE_SETS = {**BASE_FEATURE_SETS, "hz12": cols("hz", BASIC + SHAPE)}


def load_meta(days: list[str], wheelchair: str, weights: list[float] | None) -> pd.DataFrame:
    frames = []
    for day in days:
        m = pd.read_csv(ROOT / "configs/sessions" / f"{day}.csv", dtype={"session_id": str})
        frames.append(m.assign(day=day))
    meta = pd.concat(frames, ignore_index=True)
    meta = meta[meta["use"] == "yes"]
    if wheelchair != "all":
        meta = meta[meta["wheelchair"] == wheelchair]
    if weights:
        meta = meta[meta["weight_kg"].isin(weights)]
    return meta.reset_index(drop=True)


def intervals(passes: pd.DataFrame, shift_s: float) -> tuple[dict, list]:
    """START を shift_s 秒後ろにずらした区間と、捨てる区間(取り消した通過)。"""
    ok = passes[~passes["cancelled"]]
    a, b = ok["start_ms"] + shift_s * 1000.0, ok["stop_ms"]
    out = {"dansa": [], "dekobo": []}
    for kind, x, y in zip(ok["kind"], a, b):
        if x < y:
            out[kind].append((float(x), float(y)))
    dropped = [(float(x), float(y)) for x, y in passes.loc[passes["cancelled"], ["start_ms", "stop_ms"]].to_numpy()]
    return out, dropped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", nargs="+", default=["10.31", "11.1"])
    parser.add_argument("--wheelchair", default="standard", choices=["standard", "original", "all"])
    parser.add_argument("--weights", nargs="*", type=float, default=None, help="使う体重(kg)。省略で全員")
    parser.add_argument("--shift", nargs="*", default=[], help="日ごとのずらし量。例: 10.31=1.0 11.1=0.5")
    parser.add_argument("--features", nargs="+", default=["xyz18", "m6"], choices=list(FEATURE_SETS))
    parser.add_argument("--tag", default="default")
    parser.add_argument("--output-dir", default="data/analysis/20261101_combined_eval")
    args = parser.parse_args()

    shift = {d: 0.0 for d in args.days}
    for item in args.shift:
        day, value = item.split("=")
        shift[day] = float(value)

    out = ROOT / args.output_dir / args.tag
    out.mkdir(parents=True, exist_ok=True)
    meta = load_meta(args.days, args.wheelchair, args.weights)
    print("使うセッション:", meta.groupby(["day", "kind"]).size().to_dict())
    print("ずらし量 [s]:", shift)

    sessions = {s: load_session(ROOT / "wheelchair_data" / d / s) for s, d in zip(meta["session_id"], meta["day"])}
    if "hz12" in args.features:  # 水平の大きさ(features.horizontal_axes と同じ定義)
        for sess in sessions.values():
            sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
    kind_of = dict(zip(meta["session_id"], meta["kind"]))
    day_of = dict(zip(meta["session_id"], meta["day"]))

    # ラグ(揺れの閾値は、全部の flat セッションの包絡線の 99 パーセンタイル)
    flat_env = np.concatenate([sessions[s]["env"] for s, k in kind_of.items() if k == "flat"])
    threshold = float(np.percentile(flat_env, 99.0))
    passes = {}
    for s, k in kind_of.items():
        if k == "flat":
            continue
        passes[s] = add_activity(load_passes(ROOT / "wheelchair_data" / day_of[s] / s), sessions[s], threshold)
    allp = pd.concat([p.assign(session=s, day=day_of[s]) for s, p in passes.items()], ignore_index=True)
    allp.to_csv(out / "passes.csv", index=False)
    ok = allp[~allp["cancelled"]]
    pd.set_option("display.width", 220)
    print(f"揺れの閾値 {threshold:.2f} m/s²")
    print("START → 揺れ始め / 揺れの終わり → STOP [s](中央値):")
    print(ok.groupby(["day", "sub"])[["dur_s", "lag_start_s", "lag_stop_s"]].median().round(2))

    rows, conf_rows, sess_rows = [], [], []
    for window_s in WINDOWS_S:
        frames = []
        for s, sess in sessions.items():
            win = window_features(sess, window_s)
            if s in passes:
                iv, dr = intervals(passes[s], shift[day_of[s]])
            else:
                iv, dr = {}, []
            labels = label_windows(win, window_s, kind_of[s], iv, dr)
            frames.append(win.assign(label=labels, group=s, day=day_of[s]).dropna(subset=["label"]))
        df = pd.concat(frames, ignore_index=True)
        n = df["label"].value_counts()
        print(f"\n== 窓 {window_s:.1f} 秒  窓数 flat {n.get('flat', 0)} / step {n.get('dansa', 0)} / rough {n.get('dekobo', 0)}")
        for (fs, features), (model_name, model) in itertools.product(
                [(f, FEATURE_SETS[f]) for f in args.features], models().items()):
            pred = cross_val_predict(model, df[features], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
            d = df.assign(pred=pred)
            key = {"window_s": window_s, "features": fs, "model": model_name}
            row = {**key, **{f"n_{DISPLAY[k]}": int(n.get(k, 0)) for k in LABELS}}
            for k in LABELS:
                row[f"r_{DISPLAY[k]}"] = float((d.loc[d["label"] == k, "pred"] == k).mean())
                for day in args.days:
                    sub = d[(d["label"] == k) & (d["day"] == day)]
                    row[f"r_{DISPLAY[k]}_{day}"] = float((sub["pred"] == k).mean()) if len(sub) else np.nan
            rows.append(row)
            m = confusion_matrix(d["label"], d["pred"], labels=LABELS)
            for i, t in enumerate(LABELS):
                for j, q in enumerate(LABELS):
                    conf_rows.append({**key, "true": DISPLAY[t], "pred": DISPLAY[q], "n": int(m[i, j])})
            for (g, t), sub in d.groupby(["group", "label"]):
                sess_rows.append({**key, "session": g, "day": day_of[g], "true": DISPLAY[t], "n": len(sub),
                                  **{f"to_{DISPLAY[q]}": int((sub["pred"] == q).sum()) for q in LABELS},
                                  "recall": float((sub["pred"] == t).mean())})
            per_day = "  ".join(
                f"{day}: " + "/".join(f"{row[f'r_{DISPLAY[k]}_{day}']:.2f}" for k in LABELS) for day in args.days)
            print(f"{fs:5s} {model_name:12s} flat/step/rough = {row['r_flat']:.2f}/{row['r_step']:.2f}/"
                  f"{row['r_rough']:.2f}   （日ごと {per_day}）", flush=True)

    pd.DataFrame(rows).to_csv(out / "results.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(out / "confusion.csv", index=False)
    pd.DataFrame(sess_rows).to_csv(out / "by_session.csv", index=False)


if __name__ == "__main__":
    main()
