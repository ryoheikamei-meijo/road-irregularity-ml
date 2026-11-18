"""通過の端の窓(区間に半分だけ重なる窓)が、間違いの多い原因かを確かめる。

方針A のラベルは、ラベルの区間(START + 1 秒〜STOP)に窓の半分以上が重なる窓に付く。このため、通過の端では、窓の約半分が
区間の外(まだ揺れ始めていない・もう揺れていない走行)になる。
窓を「区間に全部入る窓」と「端の窓(半分以上 100% 未満が重なる窓)」に分け、学習はこれまでどおり(今のラベル、全部の窓)にして、
再現率を別々に出す。17 セッション(150809 を足す)と 16 セッション、core と core6、2.0・1.0 秒。

出力(data/analysis/20261105_edge_windows/): by_edge.csv、by_session.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.experiments.e20261031_button_lag import ACTIVE_PERCENTILE
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261105_core6_eval import ADDED
from src.experiments.e20261105_core6_eval import CORE6
from src.experiments.e20261105_core6_eval import load_meta_with_added
from src.experiments.e20261105_rough_error_analysis import CORE
from src.experiments.e20261105_rough_error_analysis import build
from src.experiments.e20261105_rough_error_analysis import logo
from src.roadml.evaluation import DISPLAY

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261105_edge_windows"
WINDOWS_S = [2.0, 1.0]


def add_inside(df: pd.DataFrame, meta: pd.DataFrame, window_s: float) -> pd.DataFrame:
    """窓が、同じ種類の通過の区間(START + 1 秒〜STOP)に全部入るか。flat は区間が無いので True にする。"""
    inside = pd.Series(True, index=df.index)
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        if k == "flat":
            continue
        p = load_passes(ROOT / "wheelchair_data" / d / s)
        p = p[~p["cancelled"]]
        idx = df.index[df["group"] == s]
        st = df.loc[idx, "start_ms"].to_numpy()
        en = st + window_s * 1000.0
        ok = np.zeros(len(idx), dtype=bool)
        for r in p.itertuples():
            ok |= (st >= r.start_ms + 1000.0) & (en <= r.stop_ms)
        inside[idx] = ok
    return df.assign(inside=inside)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    meta = load_meta_with_added()
    flat_env = [load_session(ROOT / "wheelchair_data" / d / s)["env"]
                for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]) if k == "flat"]
    threshold = float(np.percentile(np.concatenate(flat_env), ACTIVE_PERCENTILE))

    rows, sess_rows = [], []
    for window_s in WINDOWS_S:
        df = build(meta, threshold, window_s)
        df = add_inside(df, meta, window_s)
        h = df[df["weight"].isin([68, 69]) & df["label"].notna()].reset_index(drop=True)
        for set_name, sub in (("16", h[h["group"] != ADDED]), ("17", h)):
            sub = sub.reset_index(drop=True)
            for fname, feats in (("core", CORE), ("core6", CORE6)):
                y, p = logo(sub, feats)
                ok = pd.Series(p == y.to_numpy(), index=sub.index)
                for lab in ("dansa", "dekobo"):
                    for ins, name in ((True, "区間に全部入る"), (False, "端(半分以上が重なる)")):
                        m = (sub["label"] == lab) & (sub["inside"] == ins)
                        rows.append({"window_s": window_s, "sessions": set_name, "features": fname,
                                     "class": DISPLAY[lab], "windows": name, "n": int(m.sum()),
                                     "recall": float(ok[m].mean()) if m.any() else np.nan})
                if set_name == "17" and fname == "core6":
                    for g in (ADDED, "20261101143126"):
                        for ins, name in ((True, "区間に全部入る"), (False, "端")):
                            m = (sub["group"] == g) & (sub["label"] == "dekobo") & (sub["inside"] == ins)
                            sess_rows.append({"window_s": window_s, "session": g, "windows": name,
                                              "n": int(m.sum()), "recall": float(ok[m].mean()) if m.any() else np.nan})
    by = pd.DataFrame(rows)
    by.to_csv(OUT / "by_edge.csv", index=False)
    ss = pd.DataFrame(sess_rows)
    ss.to_csv(OUT / "by_session.csv", index=False)
    print(by.round(3).to_string(index=False))
    print(ss.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
