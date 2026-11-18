"""段差の通過ごとの、車体の傾き(上り・乗り越えた / 上り・止まった / 下り)。

傾き θ は e20261101_gyro_features.add_gyro と同じ: 時刻ごとの車体の真上の向きと、セッション全体の中央値の向き
(ふだんの真上)とのなす角[度]。前後の向きは区別しない。

通過ごとに、ボタンの区間(START〜STOP。ずらさない)の中で:
  peak      : θ の最大
  peak_rel  : θ の最大 − START の直前 1 秒の θ の中央値(ふだんの傾きを引いたもの)
  range     : θ の最大 − 最小
  over5_s   : θ − 直前の中央値 が 5 度を超えていた時間[秒]
対象: 汎用の車椅子、10.31・11.1、評価に使っている(use=yes)段差のセッション、体重 51・68・69 kg。取り消した通過は除く。

出力(data/analysis/20261108_step_tilt/): passes.csv、summary.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261105_rough_error_analysis import ROOT

OUT = ROOT / "data/analysis/20261108_step_tilt"
PRE_S = 1.0  # ふだんの傾きを測る、START の直前の時間
OVER_DEG = 5.0
SUB_NAME = {"up_climb": "上り・乗り越えた", "up_stop": "上り・止まった", "down": "下り"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    meta = load_meta(["10.31", "11.1"], "standard", [51, 68, 69])
    meta = meta[meta["kind"] == "step"]
    rows = []
    for s, d, w in zip(meta["session_id"], meta["day"], meta["weight_kg"]):
        run_dir = ROOT / "wheelchair_data" / d / s  # 読むだけ
        sess = load_session(run_dir)
        add_gyro(sess, run_dir)
        ts, tilt, dt = sess["ts"], sess["tilt"], 1.0 / sess["fs"]
        passes = load_passes(run_dir)
        for r in passes[(passes["kind"] == "dansa") & ~passes["cancelled"]].itertuples():
            m = (ts >= r.start_ms) & (ts <= r.stop_ms)
            pre = (ts >= r.start_ms - PRE_S * 1000.0) & (ts < r.start_ms)
            if not m.any():
                continue
            base = float(np.median(tilt[pre])) if pre.any() else np.nan
            th = tilt[m]
            rows.append({"session": s, "day": d, "weight_kg": w, "pass_id": r.pass_id, "sub": r.sub,
                         "dur_s": (r.stop_ms - r.start_ms) / 1000.0, "base": base,
                         "peak": float(th.max()), "peak_rel": float(th.max() - base),
                         "range": float(np.ptp(th)), "over5_s": float(((th - base) > OVER_DEG).sum() * dt)})
    p = pd.DataFrame(rows)
    p.to_csv(OUT / "passes.csv", index=False)

    def summarize(g: pd.DataFrame) -> pd.Series:
        out = {"passes": len(g)}
        for c in ("peak_rel", "peak", "range", "over5_s"):
            q = g[c].quantile([0.1, 0.5, 0.9])
            out.update({f"{c}_p10": q[0.1], f"{c}_med": q[0.5], f"{c}_p90": q[0.9]})
        out["peak_rel_max"] = g["peak_rel"].max()
        return pd.Series(out)

    summ = pd.concat([
        p.groupby("sub").apply(summarize, include_groups=False).assign(weight="all"),
        p.groupby(["sub", "weight_kg"]).apply(summarize, include_groups=False).reset_index("weight_kg")
         .rename(columns={"weight_kg": "weight"}),
    ]).reset_index()
    summ.to_csv(OUT / "summary.csv", index=False)
    print(summ.round(1).to_string(index=False))
    print("\nセッション・向きごとの peak_rel の中央値:")
    print(p.groupby(["session", "weight_kg", "sub"])["peak_rel"].agg(["size", "median", "min", "max"]).round(1))


if __name__ == "__main__":
    main()
