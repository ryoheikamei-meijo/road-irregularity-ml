"""方針Aの10.3+10.4で (D) 区間単位の評価 と (E) バースト特徴量の追加 を試す。

E: 窓内の短時間RMS包絡線(30ms)から、窓ごとにスケール不変なバースト特徴量を作る。
   - burst_ratio: 包絡線の最大 / 中央値 (ピークが床よりどれだけ突出しているか)
   - burst_duty : 包絡線が最大の25%を超えている時間割合 (単発なら小さく、連続振動なら大きい)
   - n_peaks    : 最大の30%を超えるピークの数 (最小間隔0.15s)
   - peak_gap   : ピーク間隔の平均[s] (ピークが1つ以下なら窓長)
   閾値は窓自身の最大値に対する相対値で、ラベル(イベント区間)や他クラスの統計は使わない。
D: 窓ごとの予測を、(a) セッション単位 (b) 8秒チャンク単位 で多数決して評価する。
   flat は5ブロックをそれぞれ1単位として扱う。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.evaluation import summarize
from src.roadml.evaluation import vote
from src.roadml.features import BASIC
from src.roadml.features import BURST
from src.roadml.features import SHAPE
from src.roadml.windows import build_run

FEATURE_SETS = {
    "z4+kc": [f"z_{f}" for f in BASIC + SHAPE],
    "z4+kc+burst": [f"z_{f}" for f in BASIC + SHAPE + BURST],
    "xyz12+kc": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE],
    "xyz12+kc+burst": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE + BURST],
    "xyz12+kc+burst_z_only": [f"{a}_{f}" for a in "xyz" for f in BASIC + SHAPE]
    + [f"z_{f}" for f in BURST],
}
CHUNK_MS = 8000.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--windows", type=float, nargs="+", default=[1.0, 2.0])
    parser.add_argument("--output-dir", default="data/analysis/20261004_boxplot_103_104")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    rows = []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
        df["chunk"] = df["unit_session"] + "_c" + (df["t_rel_ms"] // CHUNK_MS).astype(int).astype(str)
        df.to_csv(out / f"burst_windows_{window_s}s.csv", index=False)
        print(f"\n=== 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
        for set_name, cols in FEATURE_SETS.items():
            for model_name, model in models().items():
                df["pred"] = cross_val_predict(model, df[cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
                w = summarize(df["label"], df["pred"])
                ses = vote(df, "unit_session")
                chk = vote(df[df.groupby("chunk")["chunk"].transform("size") >= 3], "chunk")
                s, c = summarize(ses["label"], ses["pred"]), summarize(chk["label"], chk["pred"])
                rows.append({"window_s": window_s, "features": set_name, "model": model_name,
                             **{f"win_{k}": v for k, v in w.items()},
                             "chunk_bal_acc": c["bal_acc"], "chunk_r_step": c["r_step"], "chunk_r_rough": c["r_rough"],
                             "chunk_n": len(chk), "sess_bal_acc": s["bal_acc"], "sess_n": len(ses)})
                print(f"  {set_name:24s}{model_name:13s} 窓={w['bal_acc']:.3f} 8s塊={c['bal_acc']:.3f} セッション={s['bal_acc']:.3f}", flush=True)
                if set_name in ("xyz12+kc", "xyz12+kc+burst") and model_name == "RandomForest":
                    print("    segment(セッション/ブロック)別 多数決:")
                    print(ses.assign(share=ses["share"].round(2)).to_string(index=False))
                    cm = confusion_matrix(df["label"], df["pred"], labels=LABELS)
                    print(pd.DataFrame(cm, index=["flat", "step", "rough"], columns=["flat", "step", "rough"]).to_string())
    result = pd.DataFrame(rows)
    result.to_csv(out / "burst_segment_sweep.csv", index=False)
    print(result.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
