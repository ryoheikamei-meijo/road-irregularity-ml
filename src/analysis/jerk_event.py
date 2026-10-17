"""ジャーク（加加速度）特徴量による flat/step(dansa)/rough(dekobo) の識別力分析。

`src.analysis.flat_event` の基本特徴量（range/diff_max/rms/std）分析とは別に、
x/y/z 各軸のジャーク特徴量（jerk_rms/jerk_std）に絞って
段差（step）と凹凸（rough）の違いが現れるかを確認する。

2026-09-09時点で `jerk_max` は特徴量セットから除外し、`jerk_rms`/`jerk_std`の
2種のみを対象とする。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from src.analysis.flat_event import AXES
from src.analysis.flat_event import AXIS_DISPLAY_NAMES
from src.analysis.flat_event import DISPLAY_LABELS
from src.analysis.flat_event import build_analysis_dataframe
from src.analysis.flat_event import cliffs_delta

plt.rcParams["font.family"] = "Hiragino Sans"

JERK_SUFFIXES = ["jerk_rms", "jerk_std"]
AXIS_JERK_COLUMNS = {axis: [f"{axis}_{suffix}" for suffix in JERK_SUFFIXES] for axis in AXES}
ALL_JERK_COLUMNS = [column for axis in AXES for column in AXIS_JERK_COLUMNS[axis]]


def plot_three_class_jerk_distributions(dataframe: pd.DataFrame, output_path: Path) -> None:
    """x/y/z 3軸 × jerk_rms/jerk_std のグリッドで flat/step/rough を比較する。"""
    ncols = len(JERK_SUFFIXES)
    figure, axes = plt.subplots(nrows=3, ncols=ncols, figsize=(4.3 * ncols, 11))
    display = dataframe.assign(display_label=dataframe["label"].map(DISPLAY_LABELS))
    groups = ("flat", "step", "rough")
    for row, axis_key in enumerate(AXES):
        for col, suffix in enumerate(JERK_SUFFIXES):
            feature = f"{axis_key}_{suffix}"
            ax = axes[row, col]
            values_by_group = [
                display.loc[display["display_label"] == group, feature].to_numpy(dtype=float)
                for group in groups
            ]
            ax.boxplot(
                values_by_group,
                tick_labels=groups,
                showfliers=False,
                medianprops={"color": "tab:orange", "linewidth": 1.5},
            )
            for index, values in enumerate(values_by_group, start=1):
                rng = np.random.default_rng(42 + index)
                shown = (
                    values if len(values) <= 800 else rng.choice(values, size=800, replace=False)
                )
                jitter = rng.normal(index, 0.045, size=len(shown))
                ax.scatter(jitter, shown, s=4, alpha=0.12, color="tab:blue")
            ax.set_title(feature)
            ax.grid(axis="y", alpha=0.3)
            if col == 0:
                ax.set_ylabel(AXIS_DISPLAY_NAMES[axis_key])
    figure.suptitle(
        "flat・step(段差)・rough(凹凸) のジャーク（加加速度）特徴量分布 [m/s³]", y=0.99
    )
    figure.legend(
        handles=[Line2D([], [], color="tab:orange", linewidth=1.5, label="中央値")],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.005),
        frameon=False,
    )
    figure.subplots_adjust(left=0.07, right=0.98, bottom=0.09, top=0.93, wspace=0.28, hspace=0.42)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def build_jerk_class_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    """3クラスの記述統計と、step(dansa) vs rough(dekobo) の単変量AUC・Cliff's deltaを作る。"""
    rows: list[dict[str, float | str]] = []
    dansa = dataframe[dataframe["label"] == "dansa"]
    dekobo = dataframe[dataframe["label"] == "dekobo"]
    for feature in ALL_JERK_COLUMNS:
        row: dict[str, float | str] = {"feature": feature}
        for label, display_label in DISPLAY_LABELS.items():
            values = dataframe.loc[dataframe["label"] == label, feature]
            row[f"{display_label}_median"] = values.median()
            row[f"{display_label}_iqr"] = values.quantile(0.75) - values.quantile(0.25)
        row["auc_rough_high_vs_step"] = roc_auc_score(
            (pd.concat([dansa, dekobo])["label"] == "dekobo").astype(int),
            pd.concat([dansa, dekobo])[feature],
        )
        row["cliffs_delta_rough_vs_step"] = cliffs_delta(
            dekobo[feature].to_numpy(dtype=float),
            dansa[feature].to_numpy(dtype=float),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_jerk_pairwise_feature_auc(dataframe: pd.DataFrame) -> pd.DataFrame:
    """flat/step/rough の3ペアそれぞれについて、ジャーク特徴量の単一AUCを計算する。"""
    pairs = [("flat", "dansa"), ("flat", "dekobo"), ("dansa", "dekobo")]
    rows: list[dict[str, float | str]] = []
    for first, second in pairs:
        pair_df = dataframe[dataframe["label"].isin([first, second])]
        y_true = (pair_df["label"] == second).astype(int)
        for feature in ALL_JERK_COLUMNS:
            rows.append(
                {
                    "comparison": f"{DISPLAY_LABELS[first]} vs {DISPLAY_LABELS[second]}",
                    "feature": feature,
                    "auc_second_class_high": roc_auc_score(y_true, pair_df[feature]),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260909_jerk_event",
        help="Analysis directory. Figures and tables are created below it.",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=1.0,
        help="Window duration in seconds. The stride remains 0.25 seconds.",
    )
    args = parser.parse_args()

    if args.window_seconds <= 0:
        raise ValueError("window-seconds must be positive")

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    dataframe = build_analysis_dataframe(window_seconds=args.window_seconds)
    missing_columns = [c for c in ALL_JERK_COLUMNS if c not in dataframe.columns]
    if missing_columns:
        raise ValueError(
            "Jerk feature columns are missing. "
            f"wheelchair_pipeline.py may need updating: {missing_columns}"
        )

    dataframe.to_csv(tables_dir / "window_features_with_jerk.csv", index=False)

    plot_three_class_jerk_distributions(
        dataframe, figures_dir / "three_class_jerk_distributions.png"
    )

    class_summary = build_jerk_class_summary(dataframe)
    class_summary.to_csv(tables_dir / "jerk_class_feature_summary.csv", index=False)

    pairwise_auc = build_jerk_pairwise_feature_auc(dataframe)
    pairwise_auc.to_csv(tables_dir / "jerk_pairwise_feature_auc.csv", index=False)

    print(f"Saved jerk analysis outputs to: {output_dir}")
    print("\nLabel counts:")
    print(dataframe["label"].value_counts().sort_index().to_string())
    print("\nJerk class summary (step vs rough AUC / Cliff's delta):")
    print(class_summary.round(3).to_string(index=False))
    print("\nJerk pairwise single-feature AUC:")
    print(pairwise_auc.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
