"""窓幅を広げたときの精度を、基本4+尖度・クレスト(バーストなし)で評価する。

発表資料(131-015)と同じ特徴量: xyz18(3軸の基本4+尖度・クレスト、18個) と m6(合成のみ、6個)。
評価の枠組み(方針A、窓幅の1/4刻み、LOGO、モデル)は e20261005_burst_segment と同じ。

窓幅を広げると、短い区間のセッション(stepの4.2秒・4.9秒)やflatのブロックが
窓に入らなくなり、評価に残るグループが減る。そのため2通りで比べる。
- all   : 各窓幅で使えるグループを全部使う(グループ数・窓数は窓幅ごとに変わる)
- common: 全窓幅(--common-widths)で窓が取れるグループだけに揃える
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.windows import build_run
from src.roadml.features import cols
from src.roadml.evaluation import evaluate

SETS = {"xyz18": "xyz", "m6": "m"}


def counts(df: pd.DataFrame, window_s: float, subset: str) -> dict:
    by = df["label"].value_counts()
    return {"window_s": window_s, "subset": subset, "n_groups": df["group"].nunique(),
            "n_flat": int(by.get("flat", 0)), "n_step": int(by.get("dansa", 0)),
            "n_rough": int(by.get("dekobo", 0)),
            "g_flat": df.loc[df["label"] == "flat", "group"].nunique(),
            "g_step": df.loc[df["label"] == "dansa", "group"].nunique(),
            "g_rough": df.loc[df["label"] == "dekobo", "group"].nunique()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="後ろ固定のみのセッションを並べたディレクトリ")
    parser.add_argument("--windows", type=float, nargs="+", default=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0])
    parser.add_argument("--common-widths", type=float, nargs="+", default=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                        help="common では、これらの窓幅の全てで窓が取れるグループだけを使う")
    parser.add_argument("--output-dir", default="data/analysis/20261012_window_widening")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    windows = {}
    for w in args.windows:
        df = pd.concat([build_run(d, w, 5) for d in run_dirs], ignore_index=True)
        windows[w] = df
        df.to_csv(out / f"windows_{w}s.csv", index=False)
        print(f"窓{w}s: {dict(df['label'].value_counts())} groups={df['group'].nunique()}", flush=True)

    common = set.intersection(*[set(windows[w]["group"]) for w in args.common_widths])
    print(f"\ncommon groups ({len(common)}): {sorted(common)}", flush=True)

    count_rows, rows = [], []
    for subset in ("all", "common"):
        for w, df in windows.items():
            sub = df if subset == "all" else df[df["group"].isin(common)]
            count_rows.append(counts(sub, w, subset))
            for set_name, axes in SETS.items():
                feature_cols = cols(axes, BASIC + SHAPE)
                for model_name, model in models().items():
                    r = evaluate(sub, feature_cols, model)
                    rows.append({"subset": subset, "window_s": w, "set": set_name, "model": model_name,
                                 "n_features": len(feature_cols), **r})
                    print(f"{subset:7s}{w:4.1f}s {set_name:6s}{model_name:13s} "
                          f"bal_acc={r['bal_acc']:.3f} flat/step/rough="
                          f"{r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f} "
                          f"step-vs-rough={r['sr_bal_acc']:.3f}", flush=True)
            pd.DataFrame(rows).to_csv(out / "window_sweep.csv", index=False)
            pd.DataFrame(count_rows).to_csv(out / "window_counts.csv", index=False)


if __name__ == "__main__":
    main()
