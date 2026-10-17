"""合成加速度|a|の基本特徴量＋ジャーク特徴量（計6特徴）と、クラス均等化の組み合わせ効果。

これまでの分析を統合する:
- z軸のみ4特徴量（実運用の学習パイプラインが使う特徴量セット）
- [20260909のジャーク分析](../../knowledge/9.9/20260909_jerk_feature_analysis.md)で追加した
  ジャーク特徴量の考え方
- [20260909の合成加速度分析](../../knowledge/9.9/20260909_magnitude_event_analysis.md)で追加した
  合成加速度|a|の基本4特徴量＋ジャーク2特徴量（計6特徴）
- [20260909のクラス均等化分析](../../knowledge/9.9/20260909_class_balance_downsampling.md)の
  ダウンサンプリング

「z軸4特徴量のみ」を「合成加速度|a|の基本特徴量＋ジャーク（計6特徴量）」に置き換えたとき、
dansa(段差)のrecallを含む識別性能がどれだけ改善するか、クラス均等化と組み合わせた場合に
どうなるかを、同じrun単位グループ5分割CVで確認する。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.legacy.analysis.class_balance import MODEL_DISPLAY_NAMES
from src.legacy.analysis.class_balance import METRIC_DISPLAY_NAMES
from src.legacy.analysis.class_balance import run_group_cv
from src.legacy.analysis.flat_event import Z_FEATURE_COLUMNS
from src.legacy.analysis.magnitude_event import ALL_MAG_FEATURE_COLUMNS
from src.legacy.analysis.magnitude_event import build_magnitude_analysis_dataframe

plt.rcParams["font.family"] = "Hiragino Sans"

FEATURE_SETS: dict[str, list[str]] = {
    "z_only": Z_FEATURE_COLUMNS,
    "mag_plus_jerk_only": ALL_MAG_FEATURE_COLUMNS,
}
FEATURE_SET_DISPLAY_NAMES = {
    "z_only": "z軸のみ（4特徴, 実運用）",
    "mag_plus_jerk_only": "合成加速度+ジャーク（6特徴）",
}


def plot_feature_set_comparison(summary_df: pd.DataFrame, output_path: Path) -> None:
    """モデルごとに、特徴量セット × クラス均等化の4条件を並べる。"""
    metrics = ["balanced_accuracy", "flat_recall", "step_recall", "rough_recall"]
    models = list(MODEL_DISPLAY_NAMES.keys())
    conditions = [
        ("z_only", False, "tab:gray"),
        ("z_only", True, "tab:blue"),
        ("mag_plus_jerk_only", False, "tab:orange"),
        ("mag_plus_jerk_only", True, "tab:red"),
    ]
    figure, axes = plt.subplots(nrows=1, ncols=len(models), figsize=(15, 6), sharey=True)
    bar_width = 0.2
    x_positions = np.arange(len(metrics))
    for axis, model_name in zip(axes, models, strict=True):
        for offset, (feature_set, balance_classes, color) in enumerate(conditions):
            row = summary_df[
                (summary_df["model"] == model_name)
                & (summary_df["feature_set"] == feature_set)
                & (summary_df["balance_classes"] == balance_classes)
            ].iloc[0]
            values = [row[metric] for metric in metrics]
            condition_label = "downsampled" if balance_classes else "baseline"
            label = f"{FEATURE_SET_DISPLAY_NAMES[feature_set]} / {condition_label}"
            axis.bar(
                x_positions + (offset - 1.5) * bar_width,
                values,
                width=bar_width,
                color=color,
                label=label,
            )
        axis.set_xticks(x_positions)
        axis.set_xticklabels(
            [METRIC_DISPLAY_NAMES[metric] for metric in metrics], rotation=20, ha="right"
        )
        axis.set_ylim(0, 1.0)
        axis.set_title(MODEL_DISPLAY_NAMES[model_name])
        axis.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("score")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=2, frameon=False
    )
    figure.suptitle("特徴量セット（z軸 vs 合成加速度）× クラス均等化の組み合わせ比較（run単位グループ5分割CV）")
    figure.subplots_adjust(left=0.06, right=0.98, bottom=0.30, top=0.88, wspace=0.06)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260909_multi_feature_balance",
        help="Analysis directory. Figures and tables are created below it.",
    )
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    dataframe = build_magnitude_analysis_dataframe(window_seconds=args.window_seconds)

    summaries: list[dict[str, float | str | int]] = []
    for feature_set_name, feature_columns in FEATURE_SETS.items():
        for model_name in ("svm", "random_forest"):
            for balance_classes in (False, True):
                summary, matrix_df, _fold_df, report_text = run_group_cv(
                    dataframe,
                    model_name=model_name,
                    balance_classes=balance_classes,
                    feature_columns=feature_columns,
                )
                summary["feature_set"] = feature_set_name
                summary["n_features"] = len(feature_columns)
                condition = "downsampled" if balance_classes else "baseline"
                summaries.append(summary)
                matrix_df.to_csv(
                    tables_dir
                    / f"confusion_matrix_{feature_set_name}_{model_name}_{condition}.csv"
                )
                (
                    tables_dir
                    / f"classification_report_{feature_set_name}_{model_name}_{condition}.txt"
                ).write_text(report_text, encoding="utf-8")
                print(f"\n=== {feature_set_name} / {model_name} / {condition} ===")
                print(report_text)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(tables_dir / "multi_feature_balance_summary.csv", index=False)
    plot_feature_set_comparison(
        summary_df, figures_dir / "multi_feature_balance_comparison.png"
    )
    print(f"\nSaved multi-feature/class-balance analysis outputs to: {output_dir}")
    print("\nSummary (balanced_accuracy / macro_f1 / per-class recall):")
    print(
        summary_df[
            [
                "feature_set",
                "n_features",
                "model",
                "balance_classes",
                "balanced_accuracy",
                "macro_f1",
                "flat_recall",
                "step_recall",
                "rough_recall",
            ]
        ]
        .round(4)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
