"""強く正則化した LightGBM と、ロジスティック回帰を評価する(後ろ固定のみ、10.3+10.4、バーストなし)。

e20261021_lightgbm の続き。評価の枠組み・特徴量セット(xyz18・z6・zh12)・窓幅は同じ。
- LightGBM: min_child_samples を大きく(20・50・100・200)、木を浅く(max_depth 2・3)。n_estimators=100。シード 42 のみ
- ロジスティック回帰: StandardScaler + LogisticRegression(class_weight=balanced)。C = 0.01・0.1・1・10
どの設定も、LOGO の外側で選んでいないので、最良の値を「性能」として読まない(設定への依存を見るだけ)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.experiments.e20261021_lightgbm import SETS
from src.roadml.datasets import add_run_dir_args
from src.roadml.datasets import resolve_run_dirs
from src.roadml.evaluation import evaluate
from src.roadml.features import horizontal_axes
from src.roadml.windows import build_windows

OUT = Path("data/analysis/20261021_regularized")
MIN_CHILD = [20, 50, 100, 200]
DEPTHS = [2, 3]
C_VALUES = [0.01, 0.1, 1, 10]


def lgbm(min_child: int, depth: int) -> LGBMClassifier:
    return LGBMClassifier(
        n_estimators=100, learning_rate=0.05, num_leaves=2**depth, max_depth=depth,
        min_child_samples=min_child, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        class_weight="balanced", random_state=42, n_jobs=4, verbose=-1,
    )


def logreg(c: float):
    return make_pipeline(StandardScaler(), LogisticRegression(C=c, class_weight="balanced", max_iter=2000))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_run_dir_args(parser)
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0, 1.0])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_dirs = resolve_run_dirs(args)

    rows = []
    for window_s in args.windows:
        df = build_windows(run_dirs, window_s, extra_axes=horizontal_axes)
        for set_name, feats in SETS.items():
            for c in C_VALUES:
                rows.append({"window_s": window_s, "features": set_name, "model": "LogReg", "setting": f"C={c}",
                             **evaluate(df, feats, logreg(c))})
            for depth in DEPTHS:
                for mc in MIN_CHILD:
                    rows.append({"window_s": window_s, "features": set_name, "model": "LightGBM",
                                 "setting": f"depth={depth},min_child={mc}", **evaluate(df, feats, lgbm(mc, depth))})
            print(f"窓{window_s}s {set_name} 完了", flush=True)
    res = pd.DataFrame(rows).round(3)
    res.to_csv(OUT / "regularized_eval.csv", index=False)
    cols = ["window_s", "features", "model", "setting", "bal_acc", "sr_bal_acc", "r_flat", "r_step", "r_rough"]
    print(res[cols].to_string(index=False))


if __name__ == "__main__":
    main()
