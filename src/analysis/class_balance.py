"""クラス均等化（ダウンサンプリング）による3クラス分類性能への影響を確認する。

段差(step=dansa)が全体の約2%しかない現状のクラス不均衡に対し、学習データを
クラスごとに等数（学習foldの最小クラス数）までダウンサンプリングした場合に、
既存の `class_weight="balanced"` のみの場合（ベースライン）と比べて識別性能
（特に step の recall）がどう変わるかを、run単位のグループ5分割CVで確認する。
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
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import classification_report
from sklearn.metrics import confusion_matrix
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedGroupKFold

from src.analysis.flat_event import DISPLAY_LABELS
from src.analysis.flat_event import LABELS
from src.analysis.flat_event import Z_FEATURE_COLUMNS
from src.analysis.flat_event import build_analysis_dataframe
from src.config import load_config
from src.models import build_model

# 実運用と同じモデル設定（configs/）をそのまま使う。
MODEL_CONFIG_PATHS = {
    "svm": "configs/wheelchair_world_z_combined_svm.yaml",
    "random_forest": "configs/wheelchair_world_z_combined_random_forest.yaml",
}

plt.rcParams["font.family"] = "Hiragino Sans"
MODEL_DISPLAY_NAMES = {"svm": "SVM", "random_forest": "Random Forest"}
METRIC_DISPLAY_NAMES = {
    "balanced_accuracy": "balanced accuracy",
    "flat_recall": "flat recall",
    "step_recall": "step recall",
    "rough_recall": "rough recall",
}


def downsample_to_equal_classes(dataframe: pd.DataFrame, *, random_state: int) -> pd.DataFrame:
    """label列ごとに、最も少ないクラスの件数まで無作為抽出して揃える。"""
    target_n = int(dataframe["label"].value_counts().min())
    parts = [
        group.sample(n=target_n, random_state=random_state)
        for _, group in dataframe.groupby("label")
        if len(group) > 0
    ]
    return pd.concat(parts, ignore_index=True) if parts else dataframe.iloc[0:0]


def run_group_cv(
    dataframe: pd.DataFrame,
    *,
    model_name: str,
    balance_classes: bool,
    feature_columns: list[str] | None = None,
    random_state: int = 42,
) -> tuple[dict[str, float | str | int], pd.DataFrame, pd.DataFrame, str]:
    """runをまたがない5分割CVで、学習fold内のみダウンサンプリングして評価する。

    テストfoldは一切加工しない（実運用時の自然なクラス比率のまま評価する）。
    `feature_columns` 省略時は実運用と同じz軸4特徴量（`Z_FEATURE_COLUMNS`）を使う。
    """
    if feature_columns is None:
        feature_columns = Z_FEATURE_COLUMNS

    model_config = load_config(MODEL_CONFIG_PATHS[model_name])
    base_model = build_model(model_config)

    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=random_state)
    X_full = dataframe[feature_columns]
    y_full = dataframe["label"]
    groups = dataframe["run_id"]

    y_pred = pd.Series(index=dataframe.index, dtype=object)
    fold_rows: list[dict[str, int]] = []
    for fold_id, (train_idx, test_idx) in enumerate(
        splitter.split(X_full, y_full, groups), start=1
    ):
        train_df = dataframe.iloc[train_idx]
        test_df = dataframe.iloc[test_idx]
        before_counts = train_df["label"].value_counts().reindex(LABELS, fill_value=0)

        fit_df = train_df
        if balance_classes:
            fit_df = downsample_to_equal_classes(train_df, random_state=random_state)
        after_counts = fit_df["label"].value_counts().reindex(LABELS, fill_value=0)

        fold_model = clone(base_model)
        fold_model.fit(fit_df[feature_columns], fit_df["label"])
        predictions = fold_model.predict(test_df[feature_columns])
        y_pred.iloc[test_idx] = predictions

        fold_rows.append(
            {
                "fold": fold_id,
                "test_runs": int(test_df["run_id"].nunique()),
                **{f"train_{label}_before": int(before_counts[label]) for label in LABELS},
                **{f"train_{label}_after": int(after_counts[label]) for label in LABELS},
            }
        )

    report_text = classification_report(
        y_full, y_pred, labels=LABELS, digits=4, zero_division=0
    )
    matrix = confusion_matrix(y_full, y_pred, labels=LABELS)
    matrix_df = pd.DataFrame(matrix, index=LABELS, columns=LABELS)
    matrix_df.index.name = "true_label"

    summary: dict[str, float | str | int] = {
        "model": model_name,
        "balance_classes": balance_classes,
        "windows": len(dataframe),
        "runs": int(dataframe["run_id"].nunique()),
        "balanced_accuracy": balanced_accuracy_score(y_full, y_pred),
        "macro_f1": f1_score(y_full, y_pred, labels=LABELS, average="macro"),
    }
    for label in LABELS:
        label_mask = y_full == label
        summary[f"{DISPLAY_LABELS[label]}_recall"] = float((y_pred[label_mask] == label).mean())

    return summary, matrix_df, pd.DataFrame(fold_rows), report_text


def plot_balance_comparison(summary_df: pd.DataFrame, output_path: Path) -> None:
    """モデルごとに、baseline(class_weight=balancedのみ) vs downsampled の指標を並べる。"""
    metrics = ["balanced_accuracy", "flat_recall", "step_recall", "rough_recall"]
    models = list(MODEL_DISPLAY_NAMES.keys())
    figure, axes = plt.subplots(nrows=1, ncols=len(models), figsize=(12, 5), sharey=True)
    bar_width = 0.35
    x_positions = np.arange(len(metrics))
    for axis, model_name in zip(axes, models, strict=True):
        for offset, (balance_classes, color, label) in enumerate(
            [
                (False, "tab:gray", "baseline (class_weight=balanced)"),
                (True, "tab:blue", "downsampled (33%均等)"),
            ]
        ):
            row = summary_df[
                (summary_df["model"] == model_name)
                & (summary_df["balance_classes"] == balance_classes)
            ].iloc[0]
            values = [row[metric] for metric in metrics]
            axis.bar(
                x_positions + (offset - 0.5) * bar_width,
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
    figure.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=2, frameon=False)
    figure.suptitle("クラス均等化(ダウンサンプリング)前後の性能比較（run単位グループ5分割CV）")
    figure.subplots_adjust(left=0.07, right=0.98, bottom=0.24, top=0.88, wspace=0.08)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260909_class_balance",
        help="Analysis directory. Tables are created below it.",
    )
    parser.add_argument("--window-seconds", type=float, default=1.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    dataframe = build_analysis_dataframe(window_seconds=args.window_seconds)

    summaries: list[dict[str, float | str | int]] = []
    for model_name in ("svm", "random_forest"):
        for balance_classes in (False, True):
            summary, matrix_df, fold_df, report_text = run_group_cv(
                dataframe, model_name=model_name, balance_classes=balance_classes
            )
            condition = "downsampled" if balance_classes else "baseline"
            summaries.append(summary)
            matrix_df.to_csv(tables_dir / f"confusion_matrix_{model_name}_{condition}.csv")
            (tables_dir / f"classification_report_{model_name}_{condition}.txt").write_text(
                report_text, encoding="utf-8"
            )
            if balance_classes:
                fold_df.to_csv(tables_dir / f"fold_class_counts_{model_name}.csv", index=False)
            print(f"\n=== {model_name} / {condition} ===")
            print(report_text)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(tables_dir / "class_balance_summary.csv", index=False)
    plot_balance_comparison(summary_df, figures_dir / "class_balance_comparison.png")
    print(f"\nSaved class-balance analysis outputs to: {output_dir}")
    print("\nSummary (balanced_accuracy / macro_f1 / per-class recall):")
    print(summary_df.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
