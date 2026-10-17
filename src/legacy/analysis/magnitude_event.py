"""合成加速度（|a| = sqrt(x^2+y^2+z^2)）特徴量による flat/step(dansa)/rough(dekobo) の識別力分析。

[2026-08-05の企業MTG議事録](../../knowledge/semi/company_mtg/2026-08-05/oshisuto_regular_mtg_notes.md)で
「合成加速度についても箱ひげ図を作成し、特徴を確認するとよい」という指摘があった。
`accWorldMag`は既にworld座標系CSVに含まれている（可視化専用で学習には未使用）ため、
これを重力分だけ補正した`world_mag_linear`を軸の1つとして扱い、x/y/z軸の分析
（[flat_event.py](./flat_event.py) / [jerk_event.py](./jerk_event.py)）と同じ方法で
基本4特徴量＋ジャーク2特徴量（計6特徴量、`jerk_max`は除外）を計算し、flat/step/roughの識別力を確認する。
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

from src.legacy.analysis.flat_event import DISPLAY_LABELS
from src.legacy.analysis.flat_event import build_analysis_dataframe
from src.legacy.analysis.flat_event import cliffs_delta

plt.rcParams["font.family"] = "Hiragino Sans"

MAG_AXES = ("x", "y", "z", "mag")
MAG_FEATURE_COLUMNS = ["mag_std", "mag_range", "mag_rms", "mag_diff_max"]
MAG_JERK_COLUMNS = ["mag_jerk_rms", "mag_jerk_std"]
ALL_MAG_FEATURE_COLUMNS = MAG_FEATURE_COLUMNS + MAG_JERK_COLUMNS


def build_magnitude_analysis_dataframe(*, window_seconds: float) -> pd.DataFrame:
    """x/y/z軸に加えて、合成加速度(mag)の特徴量も含むデータフレームを作る。"""
    return build_analysis_dataframe(window_seconds=window_seconds, axes=MAG_AXES)


def plot_three_class_magnitude_distributions(
    dataframe: pd.DataFrame, output_path: Path
) -> None:
    """合成加速度の基本4特徴量＋ジャーク2特徴量(計6)で flat/step/rough を比較する。"""
    figure, axes = plt.subplots(nrows=2, ncols=4, figsize=(15, 8))
    display = dataframe.assign(display_label=dataframe["label"].map(DISPLAY_LABELS))
    groups = ("flat", "step", "rough")
    features = MAG_FEATURE_COLUMNS + MAG_JERK_COLUMNS
    for index, ax in enumerate(axes.flat):
        if index >= len(features):
            ax.axis("off")
            continue
        feature = features[index]
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
        for group_index, values in enumerate(values_by_group, start=1):
            rng = np.random.default_rng(42 + group_index)
            shown = values if len(values) <= 800 else rng.choice(values, size=800, replace=False)
            jitter = rng.normal(group_index, 0.045, size=len(shown))
            ax.scatter(jitter, shown, s=4, alpha=0.12, color="tab:blue")
        ax.set_title(feature)
        ax.grid(axis="y", alpha=0.3)
    figure.suptitle(
        "flat・step(段差)・rough(凹凸) の合成加速度|a|特徴量分布（基本4種＋ジャーク2種）", y=0.98
    )
    figure.legend(
        handles=[Line2D([], [], color="tab:orange", linewidth=1.5, label="中央値")],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        frameon=False,
    )
    figure.subplots_adjust(left=0.05, right=0.98, bottom=0.12, top=0.90, wspace=0.28, hspace=0.35)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def build_magnitude_class_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    """合成加速度特徴量の3クラス記述統計と、step(dansa) vs rough(dekobo)のAUC・Cliff's delta。"""
    rows: list[dict[str, float | str]] = []
    dansa = dataframe[dataframe["label"] == "dansa"]
    dekobo = dataframe[dataframe["label"] == "dekobo"]
    for feature in ALL_MAG_FEATURE_COLUMNS:
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


def build_magnitude_pairwise_feature_auc(dataframe: pd.DataFrame) -> pd.DataFrame:
    """flat/step/rough の3ペアそれぞれについて、合成加速度特徴量の単一AUCを計算する。"""
    pairs = [("flat", "dansa"), ("flat", "dekobo"), ("dansa", "dekobo")]
    rows: list[dict[str, float | str]] = []
    for first, second in pairs:
        pair_df = dataframe[dataframe["label"].isin([first, second])]
        y_true = (pair_df["label"] == second).astype(int)
        for feature in ALL_MAG_FEATURE_COLUMNS:
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
        default="data/analysis/20260909_magnitude_event",
        help="Analysis directory. Figures and tables are created below it.",
    )
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()

    if args.window_seconds <= 0:
        raise ValueError("window-seconds must be positive")

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    dataframe = build_magnitude_analysis_dataframe(window_seconds=args.window_seconds)
    missing_columns = [c for c in ALL_MAG_FEATURE_COLUMNS if c not in dataframe.columns]
    if missing_columns:
        raise ValueError(
            "Magnitude feature columns are missing. "
            f"wheelchair_pipeline.py may need updating: {missing_columns}"
        )

    dataframe.to_csv(tables_dir / "window_features_with_magnitude.csv", index=False)

    plot_three_class_magnitude_distributions(
        dataframe, figures_dir / "three_class_magnitude_distributions.png"
    )

    class_summary = build_magnitude_class_summary(dataframe)
    class_summary.to_csv(tables_dir / "magnitude_class_feature_summary.csv", index=False)

    pairwise_auc = build_magnitude_pairwise_feature_auc(dataframe)
    pairwise_auc.to_csv(tables_dir / "magnitude_pairwise_feature_auc.csv", index=False)

    print(f"Saved magnitude analysis outputs to: {output_dir}")
    print("\nLabel counts:")
    print(dataframe["label"].value_counts().sort_index().to_string())
    print("\nMagnitude class summary (step vs rough AUC / Cliff's delta):")
    print(class_summary.round(3).to_string(index=False))
    print("\nMagnitude pairwise single-feature AUC:")
    print(pairwise_auc.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
