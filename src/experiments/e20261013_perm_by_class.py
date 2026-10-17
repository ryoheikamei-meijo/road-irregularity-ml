"""permutation importance を、balanced accuracy ではなくクラスごとの再現率(flat/step/rough)の低下量で出す。

ゼミ(第16回)で「balanced accuracy で見ているので、step・rough で寄与度を確認した方がよい」と指摘されたため。
手順は e20261006_feature_importance.permutation_cv と同じ(LOGOの各foldで、テストグループの特徴量1個だけを
シャッフルして予測し直し、全foldの予測をまとめて評価。10回の平均)。指標だけを、クラスごとの再現率にしている。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import recall_score
from sklearn.model_selection import LeaveOneGroupOut

from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.windows import build_run
from src.roadml.features import cols
from src.roadml.datasets import add_run_dir_args
from src.roadml.datasets import resolve_run_dirs

plt.rcParams["font.family"] = "Hiragino Sans"
plt.rcParams["pdf.fonttype"] = 42  # 日本語フォントをPDFに埋め込むため(Type 3 だとフォント名で失敗する)

SETS = {"m6": "m", "xyz18": "xyz"}
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}
COLORS = {"SVM": "#2a6fb0", "RandomForest": "#d98a2b"}
RNG_SEED = 0


def recalls(y, pred) -> np.ndarray:
    return recall_score(y, pred, labels=LABELS, average=None, zero_division=0)


def permutation_by_class(df, feature_cols, model, repeats, rng) -> tuple[np.ndarray, dict]:
    """特徴量ごとに、クラスごとの再現率の低下量(repeats回分)を返す。"""
    y = df["label"].to_numpy()
    folds = list(LeaveOneGroupOut().split(df, y, df["group"]))
    fitted = []
    base_pred = np.empty(len(df), dtype=object)
    for tr, te in folds:
        m = clone(model).fit(df.iloc[tr][feature_cols], y[tr])
        fitted.append(m)
        base_pred[te] = m.predict(df.iloc[te][feature_cols])
    base = recalls(y, base_pred)
    drops = {}
    for c in feature_cols:
        vals = []
        for _ in range(repeats):
            pred = np.empty(len(df), dtype=object)
            for (tr, te), m in zip(folds, fitted):
                x = df.iloc[te][feature_cols].copy()
                x[c] = x[c].to_numpy()[rng.permutation(len(te))]
                pred[te] = m.predict(x)
            vals.append(base - recalls(y, pred))
        drops[c] = np.array(vals)  # (repeats, 3クラス)
    return base, drops


def plot(table: pd.DataFrame, title: str, path: Path) -> None:
    feats = list(dict.fromkeys(table["feature"]))
    model_names = [m for m in models() if m in set(table["model"])]  # SVM, RF の順(図1と同じ)
    fig, axes = plt.subplots(1, 3, figsize=(13, 0.45 * len(feats) * len(model_names) / 1.4 + 1.8), sharey=True)
    h = 0.38
    lim = table["mean"].abs().max() * 1.1
    for ax, cls in zip(axes, ["flat", "step", "rough"]):
        sub = table[table["class"] == cls]
        for j, m in enumerate(model_names):
            s = sub[sub["model"] == m].set_index("feature").reindex(feats)
            ypos = np.arange(len(feats)) + (j - (len(model_names) - 1) / 2) * h
            ax.barh(ypos, s["mean"], height=h, color=COLORS.get(m, "gray"), label=m)
        base = sub.groupby("model")["base"].first()
        ax.set_title(f"{cls} の再現率\n(元の値: " + ", ".join(f"{m} {base[m]:.2f}" for m in model_names) + ")",
                     fontsize=10)
        ax.axvline(0, color="k", lw=0.8)
        ax.set_xlim(-lim, lim)
        ax.set_xlabel("再現率の低下量(シャッフル時, 10回の平均)")
    axes[0].set_yticks(range(len(feats)))
    axes[0].set_yticklabels(feats)
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower right", fontsize=8)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    fig.savefig(path.with_suffix(".pdf"))  # 発表資料(LaTeX)用
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    add_run_dir_args(parser)
    parser.add_argument("--sets", nargs="+", default=["m6"], choices=list(SETS))
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0])
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output-dir", default="data/analysis/20261013_perm_by_class")
    args = parser.parse_args()

    run_dirs = resolve_run_dirs(args)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
        for set_name in args.sets:
            feature_cols = cols(SETS[set_name], BASIC + SHAPE)
            part = []
            for model_name, model in models().items():
                rng = np.random.default_rng(RNG_SEED)
                base, drops = permutation_by_class(df, feature_cols, model, args.repeats, rng)
                for c, vals in drops.items():
                    for k, lab in enumerate(LABELS):
                        part.append({"window_s": window_s, "set": set_name, "model": model_name, "feature": c,
                                     "class": NAME[lab], "mean": vals[:, k].mean(), "std": vals[:, k].std(),
                                     "base": base[k]})
            t = pd.DataFrame(part)
            # 並び順: 3クラスの低下量の合計(両モデルの平均)が大きい順
            order = t.groupby("feature")["mean"].sum().sort_values(ascending=False).index
            t["feature"] = pd.Categorical(t["feature"], categories=order, ordered=True)
            t = t.sort_values(["feature", "model", "class"])
            t["feature"] = t["feature"].astype(str)
            rows.append(t)
            plot(t, f"クラスごとの permutation importance ({set_name}, 窓{window_s}s)",
                 out / f"perm_by_class_{set_name}_{window_s}s.png")
            print(t.pivot_table(index="feature", columns=["model", "class"], values="mean", sort=False)
                  .round(3).to_string(), flush=True)
    pd.concat(rows, ignore_index=True).to_csv(out / "perm_by_class.csv", index=False)


if __name__ == "__main__":
    main()
