"""LightGBM を、SVM・RF と同じ条件で評価する(後ろ固定のみ、10.3+10.4、バーストなし)。

評価の枠組み(方針A、窓の1/4刻み、LOGO、class_weight=balanced)は e20261017_heading_dependence と同じ。
特徴量セットは xyz18・z6・zh12(基本4 + 尖度・クレスト)。窓幅は 2.0 秒(主)と 1.0 秒。

- main    : SVM・RF(既存の models())と LightGBM(既定寄りの設定、シード 42〜46)を並べる
- 感度確認: xyz18・2.0 秒で、num_leaves と n_estimators を変える(チューニングではなく、設定への依存を見る)
- 混同行列: xyz18・2.0 秒・LightGBM(既定設定、シード 42)
LOGO の外側で設定を選ぶとテストの情報が漏れるので、本命は既定寄りの設定の 1 通り。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import confusion_matrix

from src.roadml.datasets import add_run_dir_args
from src.roadml.datasets import resolve_run_dirs
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import evaluate
from src.roadml.evaluation import logo_predict
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.features import cols
from src.roadml.features import horizontal_axes
from src.roadml.windows import build_windows

FEATS = BASIC + SHAPE
SEEDS = [42, 43, 44, 45, 46]
SETS = {"xyz18": cols("xyz", FEATS), "z6": cols("z", FEATS), "zh12": cols("zh", FEATS)}
OUT = Path("data/analysis/20261021_lightgbm")


def lgbm(seed: int = 42, num_leaves: int = 15, n_estimators: int = 200) -> LGBMClassifier:
    return LGBMClassifier(
        n_estimators=n_estimators, learning_rate=0.05, num_leaves=num_leaves,
        min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        class_weight="balanced", random_state=seed, n_jobs=4, verbose=-1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_run_dir_args(parser)
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0, 1.0])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_dirs = resolve_run_dirs(args)

    rows, sens, conf = [], [], None
    for window_s in args.windows:
        df = build_windows(run_dirs, window_s, extra_axes=horizontal_axes)
        print(f"\n=== 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
        for set_name, feats in SETS.items():
            for name, model in models().items():
                rows.append({"window_s": window_s, "features": set_name, "model": name, "seed": "", **evaluate(df, feats, model)})
            for seed in SEEDS:
                r = evaluate(df, feats, lgbm(seed))
                rows.append({"window_s": window_s, "features": set_name, "model": "LightGBM", "seed": seed, **r})
            print(pd.DataFrame(rows).query("window_s == @window_s and features == @set_name")
                  .groupby("model")[["bal_acc", "sr_bal_acc"]].mean().round(3).to_string(), flush=True)
        if window_s == 2.0:
            for leaves in [7, 15, 31]:
                for n_est in [100, 200, 300]:
                    r = evaluate(df, SETS["xyz18"], lgbm(42, leaves, n_est))
                    sens.append({"num_leaves": leaves, "n_estimators": n_est, **r})
            pred = logo_predict(df, SETS["xyz18"], lgbm(42))
            conf = pd.DataFrame(confusion_matrix(df["label"], pred, labels=LABELS),
                                index=[f"正解 {DISPLAY[k]}" for k in LABELS], columns=[f"予測 {DISPLAY[k]}" for k in LABELS])

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "lightgbm_eval.csv", index=False)
    summary = (res.groupby(["window_s", "features", "model"])
               .agg(bal_acc=("bal_acc", "mean"), bal_acc_sd=("bal_acc", "std"), sr_bal_acc=("sr_bal_acc", "mean"),
                    r_flat=("r_flat", "mean"), r_step=("r_step", "mean"), r_rough=("r_rough", "mean")).round(3))
    summary.to_csv(OUT / "lightgbm_summary.csv")
    print("\n" + summary.to_string())
    pd.DataFrame(sens).round(3).to_csv(OUT / "lightgbm_sensitivity.csv", index=False)
    print("\n感度確認(xyz18・2.0秒・seed42)\n" + pd.DataFrame(sens).round(3).to_string(index=False))
    conf.to_csv(OUT / "confusion_xyz18_2.0s.csv")
    print("\n混同行列(xyz18・2.0秒・LightGBM)\n" + conf.to_string())


if __name__ == "__main__":
    main()
