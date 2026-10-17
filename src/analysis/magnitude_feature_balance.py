"""合成加速度|a|特徴量の分類性能を、2種類のフェアな比較で確認する。

- 比較A（同数比較）: z_only（z軸4特徴量）vs mag_basic_only（合成加速度の基本4特徴量、
  ジャークは含めない）。特徴量数を揃えたうえで、z軸単独と合成加速度単独のどちらが
  優れているかを見る。
- 比較B（置き換え検証）: all_axes_plus_jerk（x/y/z全軸＋ジャーク、計18特徴量）vs
  mag_plus_jerk_only（合成加速度の基本4特徴量＋ジャーク2特徴量、計6特徴量）。
  もし合成加速度だけでx/y/z全軸と同等の性能が出るなら、x/y/z軸を別々に持つ代わりに
  合成加速度1本に置き換えることで、特徴量数を増やさずに済む（18→6）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.analysis.class_balance import run_group_cv
from src.analysis.flat_event import FEATURE_COLUMNS
from src.analysis.flat_event import Z_FEATURE_COLUMNS
from src.analysis.jerk_event import ALL_JERK_COLUMNS
from src.analysis.magnitude_event import ALL_MAG_FEATURE_COLUMNS
from src.analysis.magnitude_event import MAG_AXES
from src.analysis.magnitude_event import MAG_FEATURE_COLUMNS
from src.analysis.magnitude_event import build_magnitude_analysis_dataframe

ALL_AXES_PLUS_JERK_COLUMNS = FEATURE_COLUMNS + ALL_JERK_COLUMNS
FEATURE_SETS: dict[str, list[str]] = {
    "z_only": Z_FEATURE_COLUMNS,
    "mag_basic_only": MAG_FEATURE_COLUMNS,
    "all_axes_plus_jerk": ALL_AXES_PLUS_JERK_COLUMNS,
    "mag_plus_jerk_only": ALL_MAG_FEATURE_COLUMNS,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260909_magnitude_feature_balance",
        help="Analysis directory. Tables are created below it.",
    )
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    dataframe = build_magnitude_analysis_dataframe(window_seconds=args.window_seconds)
    print(f"Axes included: {MAG_AXES}, windows: {len(dataframe)}")

    summaries: list[dict[str, float | str | int]] = []
    for feature_set_name, feature_columns in FEATURE_SETS.items():
        for model_name in ("svm", "random_forest"):
            for balance_classes in (False, True):
                summary, _matrix_df, _fold_df, _report_text = run_group_cv(
                    dataframe,
                    model_name=model_name,
                    balance_classes=balance_classes,
                    feature_columns=feature_columns,
                )
                summary["feature_set"] = feature_set_name
                summary["n_features"] = len(feature_columns)
                summaries.append(summary)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(tables_dir / "magnitude_feature_balance_summary.csv", index=False)
    print(f"\nSaved outputs to: {output_dir}")
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
