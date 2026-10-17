"""後ろ固定のみの10.3+10.4で、特徴量の寄与度を調べる(10.5の評価設定と同じ)。

評価の枠組みは e20261005_burst_segment と同じ(方針A、窓の1/4刻み、LOGO)。対象は
xyz30(3軸の基本4+尖度・クレスト+バースト) と m10(合成のみ)、モデルは SVM / RandomForest。
`--no-burst` ではバーストを外し、xyz18(3軸の基本4+尖度・クレスト) と m6(合成のみ)を対象にする。

1. permutation importance: LOGOの各foldで、テストグループの特徴量だけをシャッフルして予測し直し、
   全foldの予測をまとめたbalanced accuracyの低下量を重要度とする(テストグループは1クラスのみの
   ことがあるため、fold毎ではなく全fold合算で測る)。特徴量単位と、特徴量グループ単位(軸×種類)。
2. グループ除去(ablation): そのグループの特徴量を除いて再学習・再評価したときのbalanced accuracy。
   相関の強い特徴量は、permutationだと互いに補い合って過小評価されるため、その裏取り。
3. 単変量の分離度: 特徴量ごとの AUC(flat/step/rough の one-vs-rest、macro)。
4. 上位k個への削減: 各fold内で学習データのRF impurity importanceで上位kを選び、再学習して評価。
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut

from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import BURST
from src.roadml.features import SHAPE
from src.roadml.windows import build_run

plt.rcParams["font.family"] = "Hiragino Sans"

TYPES = {"基本4": BASIC, "尖度・クレスト": SHAPE, "バースト": BURST}
FEATURE_SETS = {"xyz30": "xyz", "m10": "m"}
TOP_KS = [2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 20, 30]
RNG_SEED = 0


def feature_columns(axes: str) -> list[str]:
    return [f"{a}_{f}" for a in axes for feats in TYPES.values() for f in feats]


def feature_groups(axes: str) -> dict[str, list[str]]:
    """グループ名 -> 特徴量列。軸×種類、種類のみ、軸のみ。"""
    groups: dict[str, list[str]] = {}
    for a in axes:
        for tname, feats in TYPES.items():
            groups[f"{a}軸:{tname}"] = [f"{a}_{f}" for f in feats]
    if len(axes) > 1:
        for tname, feats in TYPES.items():
            groups[f"全軸:{tname}"] = [f"{a}_{f}" for a in axes for f in feats]
        for a in axes:
            groups[f"{a}軸:全部"] = [f"{a}_{f}" for feats in TYPES.values() for f in feats]
    return groups


def permutation_cv(df, cols, groups, model, repeats, rng):
    """全fold合算のbalanced accuracyの低下量。groups: 名前 -> 列リスト。"""
    y = df["label"].to_numpy()
    folds = list(LeaveOneGroupOut().split(df, y, df["group"]))
    fitted = []
    base_pred = np.empty(len(df), dtype=object)
    for tr, te in folds:
        m = clone(model).fit(df.iloc[tr][cols], y[tr])
        fitted.append(m)
        base_pred[te] = m.predict(df.iloc[te][cols])
    base = balanced_accuracy_score(y, base_pred)
    drops = {}
    for name, gcols in groups.items():
        vals = []
        for _ in range(repeats):
            pred = np.empty(len(df), dtype=object)
            for (tr, te), m in zip(folds, fitted):
                x = df.iloc[te][cols].copy()
                perm = rng.permutation(len(te))
                x[gcols] = x[gcols].to_numpy()[perm]
                pred[te] = m.predict(x)
            vals.append(base - balanced_accuracy_score(y, pred))
        drops[name] = vals
    return base, drops


def logo_bal_acc(df, cols, model) -> float:
    y = df["label"].to_numpy()
    pred = np.empty(len(df), dtype=object)
    for tr, te in LeaveOneGroupOut().split(df, y, df["group"]):
        pred[te] = clone(model).fit(df.iloc[tr][cols], y[tr]).predict(df.iloc[te][cols])
    return balanced_accuracy_score(y, pred)


def topk_logo(df, cols, model, k) -> float:
    """各fold内で学習データのRF impurityにより上位kを選んで評価(選択にテストを使わない)。"""
    y = df["label"].to_numpy()
    pred = np.empty(len(df), dtype=object)
    for tr, te in LeaveOneGroupOut().split(df, y, df["group"]):
        rf = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42)
        rf.fit(df.iloc[tr][cols], y[tr])
        top = [cols[i] for i in np.argsort(rf.feature_importances_)[::-1][:k]]
        pred[te] = clone(model).fit(df.iloc[tr][top], y[tr]).predict(df.iloc[te][top])
    return balanced_accuracy_score(y, pred)


def univariate_auc(df, cols) -> pd.DataFrame:
    y = df["label"].to_numpy()
    rows = []
    for c in cols:
        aucs = {}
        for lab in LABELS:
            a = roc_auc_score(y == lab, df[c])
            aucs[lab] = max(a, 1 - a)  # 向きは問わない
        rows.append({"feature": c, **{f"auc_{k}": v for k, v in aucs.items()},
                     "auc_macro": float(np.mean(list(aucs.values())))})
    return pd.DataFrame(rows)


def plot_perm(table: pd.DataFrame, title: str, path: Path, top: int | None = None,
              error_bar: bool = False) -> None:
    """棒 = 10回のシャッフルの平均。error_bar=True で ±std のエラーバーも描く。"""
    models_ = list(table["model"].unique())
    order = (table.groupby("name")["mean"].mean().sort_values(ascending=False).index.tolist())
    if top:
        order = order[:top]
    fig, ax = plt.subplots(figsize=(8, 0.32 * len(order) * len(models_) / 1.4 + 1.6))
    h = 0.38
    colors = {"SVM": "#2a6fb0", "RandomForest": "#d98a2b"}
    for j, m in enumerate(models_):
        sub = table[table["model"] == m].set_index("name").reindex(order)
        ypos = np.arange(len(order)) + (j - (len(models_) - 1) / 2) * h
        ax.barh(ypos, sub["mean"], height=h, xerr=sub["std"] if error_bar else None,
                color=colors.get(m, "gray"), label=m, error_kw={"lw": 0.8, "ecolor": "#555"})
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    ax.invert_yaxis()
    ax.axvline(0, color="k", lw=0.8)
    ax.set_xlabel("balanced accuracy の低下量(シャッフル時, 全fold合算, 10回の平均"
                  + ("±std)" if error_bar else ")"))
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_all(feat: pd.DataFrame, group: pd.DataFrame, out: Path, error_bar: bool) -> None:
    for (window_s, set_name), sub in feat.groupby(["window_s", "set"]):
        plot_perm(sub, f"特徴量別 permutation importance ({set_name}, 窓{window_s}s)",
                  out / f"figures/perm_features_{set_name}_{window_s}s.png", error_bar=error_bar)
    for (window_s, set_name), sub in group.groupby(["window_s", "set"]):
        plot_perm(sub, f"特徴量グループ別 permutation importance ({set_name}, 窓{window_s}s)",
                  out / f"figures/perm_groups_{set_name}_{window_s}s.png", error_bar=error_bar)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", help="後ろ固定のみのセッションを並べたディレクトリ")
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0, 1.0])
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--no-burst", action="store_true",
                        help="バースト特徴量を使わない(発表資料131-015と同じ、基本4+尖度・クレスト)。"
                             "特徴量セットは xyz18 / m6 になる")
    parser.add_argument("--output-dir", default="data/analysis/20261006_feature_importance_rear_only")
    parser.add_argument("--error-bar", action="store_true", help="permutationの図に ±std のエラーバーを描く")
    parser.add_argument("--replot", action="store_true",
                        help="計算せず、--output-dir の tables から図だけ描き直す")
    args = parser.parse_args()

    if args.replot:
        out = Path(args.output_dir)
        plot_all(pd.read_csv(out / "tables/permutation_features.csv"),
                 pd.read_csv(out / "tables/permutation_groups.csv"), out, args.error_bar)
        return
    if not args.data_dir:
        parser.error("--data-dir が必要(--replot 以外)")

    feature_sets = FEATURE_SETS
    if args.no_burst:
        TYPES.pop("バースト")
        feature_sets = {"xyz18": "xyz", "m6": "m"}

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(exist_ok=True)

    feat_rows, group_rows, abl_rows, topk_rows, auc_frames = [], [], [], [], []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
        print(f"\n=== 窓{window_s}s {dict(df['label'].value_counts())} groups={df['group'].nunique()}", flush=True)
        for set_name, axes in feature_sets.items():
            cols = feature_columns(axes)
            groups = feature_groups(axes)
            auc = univariate_auc(df, cols).assign(window_s=window_s, set=set_name)
            auc_frames.append(auc)
            for model_name, model in models().items():
                rng = np.random.default_rng(RNG_SEED)
                base, f_drops = permutation_cv(df, cols, {c: [c] for c in cols}, model, args.repeats, rng)
                _, g_drops = permutation_cv(df, cols, groups, model, args.repeats, rng)
                print(f"-- {set_name} {model_name} base={base:.3f}", flush=True)
                for name, vals in f_drops.items():
                    feat_rows.append({"window_s": window_s, "set": set_name, "model": model_name,
                                      "name": name, "mean": np.mean(vals), "std": np.std(vals), "base": base})
                for name, vals in g_drops.items():
                    group_rows.append({"window_s": window_s, "set": set_name, "model": model_name,
                                       "name": name, "mean": np.mean(vals), "std": np.std(vals), "base": base})
                    kept = [c for c in cols if c not in groups[name]]
                    if kept:
                        abl = logo_bal_acc(df, kept, model)
                        abl_rows.append({"window_s": window_s, "set": set_name, "model": model_name,
                                         "removed": name, "n_features": len(kept),
                                         "bal_acc": abl, "delta": abl - base})
                for k in [k for k in TOP_KS if k <= len(cols)]:
                    topk_rows.append({"window_s": window_s, "set": set_name, "model": model_name,
                                      "k": k, "bal_acc": topk_logo(df, cols, model, k)})
                    print(f"   top{k}: {topk_rows[-1]['bal_acc']:.3f}", flush=True)

    feat = pd.DataFrame(feat_rows)
    group = pd.DataFrame(group_rows)
    abl = pd.DataFrame(abl_rows)
    topk = pd.DataFrame(topk_rows)
    auc_all = pd.concat(auc_frames, ignore_index=True)
    feat.to_csv(out / "tables/permutation_features.csv", index=False)
    group.to_csv(out / "tables/permutation_groups.csv", index=False)
    abl.to_csv(out / "tables/ablation_groups.csv", index=False)
    topk.to_csv(out / "tables/topk_reduction.csv", index=False)
    auc_all.to_csv(out / "tables/univariate_auc.csv", index=False)

    plot_all(feat, group, out, args.error_bar)
    print("\n[グループpermutation]\n", group.round(3).to_string(index=False))
    print("\n[ablation]\n", abl.round(3).to_string(index=False))
    print("\n[top-k]\n", topk.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
