"""合成加速度+ジャーク特徴量（計6特徴）のうち、実際に効いているものを確認する。

[全軸+ジャーク特徴量の重要度分析](./feature_importance.py)と同じ方法
（run単位グループ5分割CVの各foldでpermutation importanceを計算し、RF/SVM
両モデルで比較する）を、[z軸 vs 合成加速度の比較](./multi_feature_balance.py)で
使った合成加速度+ジャーク特徴量セット（`mag_plus_jerk_only`、計6特徴）に適用する。

6特徴量とすでに少ないため、上位N個に絞る削減検討は行わない（重要度の確認のみ）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.analysis.feature_importance import TARGET_BALANCE_CLASSES
from src.analysis.feature_importance import TARGET_MODEL_NAMES
from src.analysis.feature_importance import compute_permutation_importance_cv
from src.analysis.feature_importance import plot_feature_importance
from src.analysis.feature_importance import plot_feature_importance_agreement
from src.analysis.magnitude_event import ALL_MAG_FEATURE_COLUMNS
from src.analysis.magnitude_event import build_magnitude_analysis_dataframe

FEATURE_SET_LABEL = "合成加速度+ジャーク特徴量"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260909_magnitude_feature_importance",
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

    importance_by_model: dict[str, pd.DataFrame] = {}
    for model_name in TARGET_MODEL_NAMES:
        importance_df, fold_df = compute_permutation_importance_cv(
            dataframe,
            model_name=model_name,
            feature_columns=ALL_MAG_FEATURE_COLUMNS,
            balance_classes=TARGET_BALANCE_CLASSES,
        )
        importance_by_model[model_name] = importance_df
        importance_df.to_csv(tables_dir / f"feature_importance_{model_name}.csv", index=False)
        fold_df.to_csv(tables_dir / f"feature_importance_{model_name}_by_fold.csv", index=False)
        plot_feature_importance(
            importance_df,
            fold_df,
            figures_dir / f"feature_importance_{model_name}.png",
            model_name=model_name,
            feature_set_label=FEATURE_SET_LABEL,
        )
        print(f"\nFeature importance ({model_name}, permutation, balanced_accuracy, 5fold平均):")
        print(importance_df.round(4).to_string(index=False))

    plot_feature_importance_agreement(
        importance_by_model,
        figures_dir / "feature_importance_agreement.png",
        feature_set_label=FEATURE_SET_LABEL,
    )

    merged_importance_df = (
        importance_by_model["random_forest"][["feature", "permutation_importance_mean"]]
        .rename(columns={"permutation_importance_mean": "random_forest_importance"})
        .merge(
            importance_by_model["svm"][["feature", "permutation_importance_mean"]].rename(
                columns={"permutation_importance_mean": "svm_importance"}
            ),
            on="feature",
        )
        .sort_values("random_forest_importance", ascending=False)
    )
    merged_importance_df.to_csv(tables_dir / "feature_importance_rf_vs_svm.csv", index=False)

    print(f"\nSaved magnitude feature-importance outputs to: {output_dir}")
    print("\nRF/SVM重要度並記:")
    print(merged_importance_df.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
