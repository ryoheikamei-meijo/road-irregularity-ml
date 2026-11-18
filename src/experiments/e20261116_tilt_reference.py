"""傾き(tilt_range)の基準を、アプリで計算できるものに変えても精度が保たれるか。

これまでの tilt は「セッション全体の中央値」からのずれで、走り終わらないと決まらない。
アプリで走りながら判定するため、次の基準と比べる(定義は src/roadml/core_model.py)。
  session : セッション全体の中央値(これまで)
  window  : 窓の中の中央値(前の状態を持たない)
  ema5・ema30 : それまでの上向きの指数移動平均(時定数 5・30 秒)
  mean10・mean30 : 直近 10・30 秒の上向きの平均(Mizell 2003 の方法。Hemminki ら 2013 は窓 1・10・30 秒を比べた)
  startmean10・startmean30 : 窓の最初のサンプルの時点の mean10・mean30 を、窓の中で固定して使う(2026-11-18 に追加)

条件は第18回ゼミ(131-018)の「前0.5秒」と同じ: 汎用・68〜69 kg の 16 セッション、方針A、
STOP が遅れた凸凹の通過(configs/sessions/excluded_passes.csv。計測2-2 の #9・#11)は、取り消した通過と同じく
学習・評価の両方から除く(--keep-all で除かない)。
段差は一番大きな衝撃の 0.5 秒前〜STOP、凸凹は START + 1 秒〜STOP、core・SVM・セッション単位の LOGO、窓 2.0 秒。
session の特徴量が、これまでのパイプライン(window_features + gyro_window_features)と一致することも確かめる。

出力(data/analysis/20261116_tilt_reference/): results.csv、features_<tilt_ref>.csv、tilt_example.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_gyro_features import gyro_window_features
from src.experiments.e20261104_onset_label_eval import make_intervals
from src.roadml.core_model import CORE
from src.roadml.core_model import WINDOW_S
from src.roadml.core_model import core_features
from src.roadml.core_model import load_raw
from src.roadml.core_model import signals
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

plt.rcParams["font.family"] = "Hiragino Sans"

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261116_tilt_reference"
TILT_REFS = ["session", "window", "ema5", "ema30", "mean10", "mean30", "startmean10", "startmean30"]
LABEL_CONDITION = "peak0.5"
EXCLUDED_PASSES = ROOT / "configs/sessions/excluded_passes.csv"


def excluded_passes() -> pd.DataFrame:
    """学習・評価から除く通過(session_id・kind・pass_id・理由)。"""
    return pd.read_csv(EXCLUDED_PASSES, dtype={"session_id": str})


def session_list() -> pd.DataFrame:
    return load_meta(["10.31", "11.1"], "standard", [68, 69])


def passes_with_peak(run_dir: Path, sess: dict) -> pd.DataFrame:
    """通過の一覧に、区間の中で |z| が最大の時刻(peak_ms)を足す(e20261104_onset_label_eval と同じ)。"""
    p = load_passes(run_dir)
    ts, az = sess["ts"], np.abs(sess["axes"]["z"])
    peak = []
    for a, b in zip(p["start_ms"], p["stop_ms"]):
        m = (ts >= a) & (ts <= b)
        peak.append(ts[m][np.argmax(az[m])] if m.any() else np.nan)
    return p.assign(peak_ms=peak)


def labeled_windows(meta: pd.DataFrame, tilt_ref: str, exclude: bool = True) -> pd.DataFrame:
    """セッションごとに core の特徴量を計算し、前0.5秒のラベルを付ける(ラベルの無い窓は捨てる)。
    exclude=True なら、excluded_passes.csv の通過を取り消した通過と同じ扱いにする(重なる窓を捨てる)。"""
    ex = excluded_passes() if exclude else excluded_passes().iloc[0:0]
    frames = []
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        win = core_features(signals(load_raw(run_dir), tilt_ref), WINDOW_S, tilt_ref)
        iv, dr = {}, []
        if k != "flat":
            p = passes_with_peak(run_dir, load_session(run_dir))
            drop = ex[ex["session_id"] == s]
            for kind, pid in zip(drop["kind"], drop["pass_id"]):
                hit = (p["kind"] == kind) & (p["pass_id"] == pid)
                assert hit.sum() == 1, (s, kind, pid)
                p.loc[hit, "cancelled"] = True
            iv, dr = make_intervals(p, LABEL_CONDITION)
        labels = label_windows(win, WINDOW_S, k, iv, dr)
        frames.append(win.assign(label=labels, group=s, session=s))
    return pd.concat(frames, ignore_index=True)


def check_same_as_pipeline(meta: pd.DataFrame, df: pd.DataFrame) -> float:
    """tilt_ref=session の特徴量が、これまでのパイプラインと同じかを確かめ、最大の相対誤差を返す。"""
    worst = 0.0
    for s, d in zip(meta["session_id"], meta["day"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        old = window_features(sess, WINDOW_S)
        old = old.merge(gyro_window_features(sess, old["start_ms"].to_numpy(), WINDOW_S), on="start_ms")
        new = df[df["session"] == s].drop(columns=["label", "group", "session"])
        both = new.merge(old[["start_ms", *CORE]], on="start_ms", suffixes=("", "_old"))
        assert len(both) == len(new), s
        for c in CORE:
            rel = np.abs(both[c] - both[f"{c}_old"]) / np.maximum(np.abs(both[f"{c}_old"]), 1e-9)
            worst = max(worst, float(rel.max()))
    return worst


def plot_example(meta: pd.DataFrame, path: Path) -> None:
    """段差のセッションの一部で、基準ごとの tilt を重ねる。"""
    s, d = "20261101142339", "11.1"
    raw = load_raw(ROOT / "wheelchair_data" / d / s)
    t = (raw["ts"] - raw["ts"][0]) / 1000.0
    fig, ax = plt.subplots(figsize=(11, 3.6))
    names = {"session": "セッション全体の中央値（これまで）", "mean30": "直近 30 秒の平均（採用）"}
    for ref, color in [("session", "#52514e"), ("mean30", "#eb6834")]:
        ax.plot(t, signals(raw, ref)["tilt"], lw=0.8, color=color, label=names[ref])
    ax.set_xlim(20, 60)
    ax.set_xlabel("時間 [s]")
    ax.set_ylabel("傾き [度]")
    ax.set_title(f"基準の取り方ごとの傾き（段差のセッション {s} の 20〜60 秒）")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-all", action="store_true", help="excluded_passes.csv の通過も使う(第18回の「そのまま」)")
    args = parser.parse_args()
    out = OUT / "keep_all" if args.keep_all else OUT
    out.mkdir(parents=True, exist_ok=True)
    meta = session_list()
    rows = []
    for ref in TILT_REFS:
        df = labeled_windows(meta, ref, exclude=not args.keep_all).dropna(subset=["label"]).reset_index(drop=True)
        df.to_csv(out / f"features_{ref}.csv", index=False)
        if ref == "session":
            print(f"これまでのパイプラインとの最大の相対誤差: {check_same_as_pipeline(meta, df):.2e}")
        pred = cross_val_predict(models()["SVM"], df[CORE], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
        m = confusion_matrix(df["label"], pred, labels=LABELS)
        row = {"tilt_ref": ref, **{f"r_{DISPLAY[k]}": float(m[i, i] / m[i].sum()) for i, k in enumerate(LABELS)},
               "step_to_rough": int(m[1, 2]), "rough_to_step": int(m[2, 1]),
               "flat_to_event": int(m[0, 1] + m[0, 2]), "event_to_flat": int(m[1, 0] + m[2, 0]),
               "n": len(df), "tilt_range_step_median": float(df.loc[df["label"] == "dansa", "tilt_range"].median()),
               "tilt_range_rough_median": float(df.loc[df["label"] == "dekobo", "tilt_range"].median()),
               "tilt_range_flat_median": float(df.loc[df["label"] == "flat", "tilt_range"].median())}
        rows.append(row)
        print(f"{ref:8s} flat/step/rough = {row['r_flat']:.3f}/{row['r_step']:.3f}/{row['r_rough']:.3f}"
              f"  step↔rough {row['step_to_rough']}+{row['rough_to_step']}"
              f"  flat→event {row['flat_to_event']} event→flat {row['event_to_flat']}  窓 {row['n']}"
              f"  tilt_range 中央値 flat/step/rough = {row['tilt_range_flat_median']:.2f}/"
              f"{row['tilt_range_step_median']:.2f}/{row['tilt_range_rough_median']:.2f}", flush=True)
    pd.DataFrame(rows).to_csv(out / "results.csv", index=False)
    plot_example(meta, out / "tilt_example.png")


if __name__ == "__main__":
    main()
