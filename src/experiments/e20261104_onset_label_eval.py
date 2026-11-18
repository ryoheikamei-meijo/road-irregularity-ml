"""ラベルの区間の始まりを、一律の 1 秒切り詰め(shift_1)ではなく、通過ごとの「揺れ始め」にしたときの精度。

揺れ始め = ボタンの区間(START〜STOP)の中で、z の 100 ms RMS 包絡線が閾値を初めて超えた時刻
(e20261031_button_lag・e20261104_label_shift_check と同じ定義)。
閾値 = 汎用の車椅子の flat のセッション(use=yes、8 セッション)の包絡線の 99 パーセンタイル(7.72 m/s²)。
参考に、10.31 のラグ分析の閾値 8.31 m/s² も出す。

区間の条件:
  button   : START〜STOP(切り詰めない)
  shift_1  : START + 1 秒〜STOP(今の基本)
  onset    : 揺れ始め〜STOP
  activity : 揺れ始め〜揺れの終わり(区間の中で包絡線が閾値を最後に超えた時刻)
  peak<d>  : 段差だけ、区間の中で |z| が最大の時刻の d 秒前〜STOP(START より前にはみ出してもよい)。凸凹は shift_1。
             d = 1・0.5
  peak<d>c : peak<d> と同じだが、始まりを START より前にしない
揺れ始めが無い通過は、onset・activity では区間にしない(その通過の窓は捨てる)。取り消した通過は、どの条件でも捨てる。

条件は e20261104_g_low_high_rationale と同じ(汎用・68〜69 kg の 16 セッション、方針A、core、SVM、セッション単位の LOGO、
窓 1.0・2.0 秒)。

出力(data/analysis/20261104_onset_label_eval/): results.csv、by_session.csv
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
OUT = ROOT / "data/analysis/20261104_onset_label_eval"
CORE = ["z_rms", "z_kurt", "h_std", "h_crest", "tilt_range"]  # ゼミ資料 131-017 の core(暫定)
WINDOWS_S = [2.0, 1.0]
THRESHOLDS = {"7.72": None, "8.31": 8.31}  # None = flat から計算する


def make_intervals(passes: pd.DataFrame, condition: str) -> tuple[dict, list]:
    ok = passes[~passes["cancelled"]]
    if condition == "button":
        a, b = ok["start_ms"], ok["stop_ms"]
    elif condition == "shift_1":
        a, b = ok["start_ms"] + 1000.0, ok["stop_ms"]
    elif condition == "onset":
        a, b = ok["onset_ms"], ok["stop_ms"]
    elif condition == "activity":
        a, b = ok["onset_ms"], ok["offset_ms"]
    elif condition.startswith("peak"):
        pre_ms = float(condition.removeprefix("peak").removesuffix("c")) * 1000.0
        step = ok["kind"] == "dansa"
        a = (ok["start_ms"] + 1000.0).where(~step, ok["peak_ms"] - pre_ms)
        if condition.endswith("c"):
            a = a.where(~step, np.maximum(a, ok["start_ms"]))
        b = ok["stop_ms"]
    else:
        raise ValueError(condition)
    out = {"dansa": [], "dekobo": []}
    for kind, x, y in zip(ok["kind"], a, b):
        if pd.notna(x) and pd.notna(y) and x < y:
            out[kind].append((float(x), float(y)))
    dropped = [(float(x), float(y)) for x, y in passes.loc[passes["cancelled"], ["start_ms", "stop_ms"]].to_numpy()]
    return out, dropped


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    meta_all = load_meta(["10.31", "11.1"], "standard", None)
    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta_all["session_id"], meta_all["day"], meta_all["kind"]) if k == "flat"]
    th_flat = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))
    print(f"閾値(汎用の flat {len(flat_env)} セッションの包絡線の 99 パーセンタイル): {th_flat:.2f} m/s²")

    meta = load_meta(["10.31", "11.1"], "standard", [68, 69])
    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        sessions[s] = sess
        if k != "flat":
            p = load_passes(run_dir)
            ts, az = sess["ts"], np.abs(sess["axes"]["z"])
            peak = []
            for a, b in zip(p["start_ms"], p["stop_ms"]):
                m = (ts >= a) & (ts <= b)
                peak.append(ts[m][np.argmax(az[m])] if m.any() else np.nan)
            passes[s] = p.assign(peak_ms=peak)
    kind_of = dict(zip(meta["session_id"], meta["kind"]))

    conditions = [("button", None), ("shift_1", None), ("peak1", None), ("peak1c", None),
                  ("peak0.5", None), ("peak0.5c", None)]
    conditions += [(c, th) for th in THRESHOLDS for c in ("onset", "activity")]
    rows, sess_rows = [], []
    for window_s in WINDOWS_S:
        feats = {}
        for s, sess in sessions.items():
            win = window_features(sess, window_s)
            feats[s] = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
        for cond, th_name in conditions:
            th = None if th_name is None else (THRESHOLDS[th_name] or th_flat)
            frames, n_no_onset = [], 0
            for s, win in feats.items():
                iv, dr = {}, []
                if s in passes:
                    p = passes[s] if th is None else add_activity(passes[s], sessions[s], th)
                    if th is not None:
                        n_no_onset += int(p.loc[~p["cancelled"], "onset_ms"].isna().sum())
                    iv, dr = make_intervals(p, cond)
                labels = label_windows(win, window_s, kind_of[s], iv, dr)
                frames.append(win.assign(label=labels, group=s).dropna(subset=["label"]))
            df = pd.concat(frames, ignore_index=True)
            pred = cross_val_predict(models()["SVM"], df[CORE], df["label"], groups=df["group"],
                                     cv=LeaveOneGroupOut())
            m = confusion_matrix(df["label"], pred, labels=LABELS)
            name = cond if th_name is None else f"{cond}@{th_name}"
            row = {"window_s": window_s, "condition": name,
                   **{f"r_{DISPLAY[k]}": float(m[i, i] / m[i].sum()) for i, k in enumerate(LABELS)},
                   **{f"n_{DISPLAY[k]}": int(m[i].sum()) for i, k in enumerate(LABELS)},
                   "step_to_rough": int(m[1, 2]), "rough_to_step": int(m[2, 1]),
                   "flat_to_event": int(m[0, 1] + m[0, 2]), "event_to_flat": int(m[1, 0] + m[2, 0]),
                   "passes_no_onset": n_no_onset}
            row["mean_recall"] = float(np.mean([row["r_flat"], row["r_step"], row["r_rough"]]))
            rows.append(row)
            ok = pred == df["label"].to_numpy()
            for (g, lab), idx in df.groupby(["group", "label"]).groups.items():
                sess_rows.append({"window_s": window_s, "condition": name, "session": g, "label": DISPLAY[lab],
                                  "n": len(idx), "recall": float(ok[df.index.get_indexer(idx)].mean())})
            print(f"{window_s:.1f}s {name:14s} flat/step/rough = {row['r_flat']:.3f}/{row['r_step']:.3f}/"
                  f"{row['r_rough']:.3f}  平均 {row['mean_recall']:.3f}  窓 step {row['n_step']} rough {row['n_rough']}"
                  f"  step→rough {row['step_to_rough']} rough→step {row['rough_to_step']}"
                  f"  flat→event {row['flat_to_event']} event→flat {row['event_to_flat']}", flush=True)

    pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False)
    pd.DataFrame(sess_rows).to_csv(OUT / "by_session.csv", index=False)


if __name__ == "__main__":
    main()
