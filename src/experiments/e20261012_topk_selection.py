"""上位k個に絞ったとき、各foldでどの特徴量が選ばれたかを記録する(バーストなし)。

選び方は e20261006_feature_importance.topk_logo と同じ(各foldの学習データでRF impurityの上位k)。
選択はモデルに依らないので、foldごとの順位を1回だけ求め、SVM/RFの両方で評価する。

1. 選択の記録: fold × k ごとに選ばれた特徴量(topk_selected_per_fold.csv)と、
   k ごとに「全fold中何回選ばれたか」(topk_selection_counts.csv)。
2. 固定セットの評価: k ごとに選ばれた回数の多い順にk個を固定し、全foldで同じk個を使ってLOGO評価
   (topk_fixed_eval.csv)。固定セットは全データでの選択結果から決めるので、テストの情報が少し入る。
   balanced accuracy に加えて、クラスごとの再現率と、固定セットでは step と rough だけの2クラスの
   balanced accuracy(sr_bal_acc、e20261006_related_features.evaluate と同じ)も出す。比較用に全部の特徴量の行も入れる。
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut

from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.windows import build_run
from src.roadml.evaluation import summarize
from src.roadml.features import cols
from src.roadml.evaluation import evaluate

SETS = {"xyz18": "xyz", "m6": "m"}
KS = [2, 3, 4, 5, 6, 8, 10, 12, 15]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="後ろ固定のみのセッションを並べたディレクトリ")
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0, 1.0])
    parser.add_argument("--output-dir", default="data/analysis/20261012_feature_importance_no_burst/tables")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sel_rows, count_rows, eval_rows = [], [], []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
        y = df["label"].to_numpy()
        folds = list(LeaveOneGroupOut().split(df, y, df["group"]))
        for set_name, axes in SETS.items():
            feature_cols = cols(axes, BASIC + SHAPE)
            # foldごとの順位(学習データのRF impurity)
            rankings = []
            for tr, _ in folds:
                rf = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42)
                rf.fit(df.iloc[tr][feature_cols], y[tr])
                rankings.append([feature_cols[i] for i in np.argsort(rf.feature_importances_)[::-1]])
            for k in [k for k in KS if k < len(feature_cols)]:
                counter = Counter()
                for (tr, te), rank in zip(folds, rankings):
                    top = rank[:k]
                    counter.update(top)
                    sel_rows.append({"window_s": window_s, "set": set_name, "k": k,
                                     "test_group": df.iloc[te]["group"].iloc[0],
                                     "selected": " ".join(sorted(top))})
                n_sets = len({" ".join(sorted(r[:k])) for r in rankings})
                for feat in feature_cols:
                    count_rows.append({"window_s": window_s, "set": set_name, "k": k, "feature": feat,
                                       "n_selected": counter.get(feat, 0), "n_folds": len(folds),
                                       "n_distinct_sets": n_sets})
                fixed = [f for f, _ in sorted(counter.items(), key=lambda t: (-t[1], feature_cols.index(t[0])))][:k]
                for model_name, model in models().items():
                    # 各foldで選び直す(e20261006_feature_importanceと同じ)
                    pred = np.empty(len(df), dtype=object)
                    for (tr, te), rank in zip(folds, rankings):
                        top = rank[:k]
                        pred[te] = clone(model).fit(df.iloc[tr][top], y[tr]).predict(df.iloc[te][top])
                    per_fold = summarize(y, pred)
                    eval_rows.append({"window_s": window_s, "set": set_name, "model": model_name, "k": k,
                                      "n_distinct_sets": n_sets, "fixed_set": " ".join(fixed),
                                      "bal_acc_per_fold_select": per_fold["bal_acc"],
                                      **{f"{key}_per_fold_select": per_fold[key]
                                         for key in ("r_flat", "r_step", "r_rough")},
                                      **{f"{key}_fixed": v for key, v in evaluate(df, fixed, model).items()}})
                    r = eval_rows[-1]
                    print(f"{window_s}s {set_name} {model_name:12s} k={k:2d} sets={n_sets:2d} "
                          f"per-fold={r['bal_acc_per_fold_select']:.3f} fixed={r['bal_acc_fixed']:.3f} "
                          f"flat/step/rough={r['r_flat_fixed']:.2f}/{r['r_step_fixed']:.2f}/"
                          f"{r['r_rough_fixed']:.2f} step-vs-rough={r['sr_bal_acc_fixed']:.3f} "
                          f"[{r['fixed_set']}]", flush=True)
            # 比較用に全部の特徴量
            for model_name, model in models().items():
                eval_rows.append({"window_s": window_s, "set": set_name, "model": model_name,
                                  "k": len(feature_cols), "n_distinct_sets": 1, "fixed_set": "all",
                                  **{f"{key}_fixed": v for key, v in evaluate(df, feature_cols, model).items()}})

    pd.DataFrame(sel_rows).to_csv(out / "topk_selected_per_fold.csv", index=False)
    pd.DataFrame(count_rows).to_csv(out / "topk_selection_counts.csv", index=False)
    pd.DataFrame(eval_rows).to_csv(out / "topk_fixed_eval.csv", index=False)


if __name__ == "__main__":
    main()
