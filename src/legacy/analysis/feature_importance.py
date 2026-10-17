"""18特徴量のうち、実際に識別に効いているものを特定し、削減候補を提案する。

[全軸+ジャーク×クラス均等化の分析](../../knowledge/9.9/20260909_multi_feature_class_balance.md)で
最良だった設定（SVM/Random Forest、all_axes_plus_jerk特徴量、ダウンサンプリングあり）について、
run単位グループ5分割CVの各foldでpermutation importance（テストfoldでの寄与度、
モデルに依存しない指標）を計算し、fold平均で特徴量をランキングする。

permutation importanceはモデルの種類を問わず使えるため、Random ForestとSVMの
両方で計算し、モデル間でランキングが一致するか（＝どのモデルでも重要とされる
特徴量ほど信頼できる）も確認する。

上位の特徴量だけに絞った縮小特徴量セットでも同等の性能が出るかを、
同じ評価パイプラインで確認する。
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
from sklearn.inspection import permutation_importance
from sklearn.model_selection import StratifiedGroupKFold

from src.legacy.analysis.class_balance import MODEL_CONFIG_PATHS
from src.legacy.analysis.class_balance import MODEL_DISPLAY_NAMES
from src.legacy.analysis.class_balance import downsample_to_equal_classes
from src.legacy.analysis.class_balance import run_group_cv
from src.legacy.analysis.flat_event import FEATURE_COLUMNS
from src.legacy.analysis.flat_event import build_analysis_dataframe
from src.legacy.analysis.jerk_event import ALL_JERK_COLUMNS
from src.legacy.config import load_config
from src.legacy.models import build_model

plt.rcParams["font.family"] = "Hiragino Sans"

ALL_FEATURE_COLUMNS = FEATURE_COLUMNS + ALL_JERK_COLUMNS
# 20260909の分析で最良だった設定（各モデルでダウンサンプリングあり）を対象にする。
TARGET_MODEL_NAMES = ["random_forest", "svm"]
TARGET_BALANCE_CLASSES = True


def compute_permutation_importance_cv(
    dataframe: pd.DataFrame,
    *,
    model_name: str,
    feature_columns: list[str],
    balance_classes: bool,
    random_state: int = 42,
    n_repeats: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """runをまたがない5分割CVの各foldで、テストfold側のpermutation importanceを計算する。

    学習fold内のみダウンサンプリングする点は`run_group_cv`と同じ。テストfoldは
    加工せず、そのfoldで実際に汎化に寄与した特徴量を測る。

    戻り値は (fold平均でランキングした要約表, fold毎の生の値の表)。後者は
    5分割しかないため、平均±標準偏差のエラーバーより「foldごとの点をそのまま
    5つ並べる」方が分布を誤解なく示せる。
    """
    model_config = load_config(MODEL_CONFIG_PATHS[model_name])
    base_model = build_model(model_config)

    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=random_state)
    X_full = dataframe[feature_columns]
    y_full = dataframe["label"]
    groups = dataframe["run_id"]

    perm_importances: list[np.ndarray] = []
    impurity_importances: list[np.ndarray] = []
    for train_idx, test_idx in splitter.split(X_full, y_full, groups):
        train_df = dataframe.iloc[train_idx]
        test_df = dataframe.iloc[test_idx]
        fit_df = (
            downsample_to_equal_classes(train_df, random_state=random_state)
            if balance_classes
            else train_df
        )

        fold_model = clone(base_model)
        fold_model.fit(fit_df[feature_columns], fit_df["label"])

        result = permutation_importance(
            fold_model,
            test_df[feature_columns],
            test_df["label"],
            scoring="balanced_accuracy",
            n_repeats=n_repeats,
            random_state=random_state,
            n_jobs=-1,
        )
        perm_importances.append(result.importances_mean)
        if hasattr(fold_model, "feature_importances_"):
            impurity_importances.append(fold_model.feature_importances_)

    perm_df = pd.DataFrame(perm_importances, columns=feature_columns)
    summary = pd.DataFrame(
        {
            "feature": feature_columns,
            "permutation_importance_mean": perm_df.mean().to_numpy(),
            "permutation_importance_std": perm_df.std().to_numpy(),
        }
    )
    if impurity_importances:
        impurity_df = pd.DataFrame(impurity_importances, columns=feature_columns)
        summary["impurity_importance_mean"] = (
            impurity_df.mean().reindex(summary["feature"]).to_numpy()
        )
    summary = summary.sort_values("permutation_importance_mean", ascending=False).reset_index(
        drop=True
    )
    return summary, perm_df


def _draw_fold_range(
    axis: plt.Axes,
    *,
    y_positions: np.ndarray,
    fold_df: pd.DataFrame,
    features_ordered: list[str],
    line_color: str,
    marker_color: str,
    y_offset: float = 0.0,
    marker: str = "o",
    label: str | None = None,
) -> None:
    """各特徴量について、5fold分の値を「平均点＋最小-最大の範囲を示す1本の線」で表す。

    平均±標準偏差の横棒（エラーバー）は誤差線がバーを覆い隠して読みにくく、
    5foldぶんの点をそのまま散らす方式も点が広がりすぎて逆に見づらかった。
    fold数が5と少ないため、「実際に取り得た範囲（最小〜最大）」を1本の細い線、
    「平均」を1個の点で示すだけにして、視覚要素を最小限にした。
    """
    for y, feature in zip(y_positions, features_ordered, strict=True):
        values = fold_df[feature].to_numpy()
        axis.plot(
            [values.min(), values.max()],
            [y + y_offset, y + y_offset],
            color=line_color,
            linewidth=2.2,
            solid_capstyle="round",
            alpha=0.6,
            zorder=2,
        )
        axis.scatter(
            [values.mean()],
            [y + y_offset],
            color=marker_color,
            marker=marker,
            edgecolor="white",
            linewidth=0.6,
            s=55,
            zorder=3,
            label=label if y == y_positions[0] else None,
        )


def plot_feature_importance(
    importance_df: pd.DataFrame,
    fold_df: pd.DataFrame,
    output_path: Path,
    *,
    model_name: str,
    feature_set_label: str = "全軸+ジャーク特徴量",
) -> None:
    ordered = importance_df.sort_values("permutation_importance_mean", ascending=True)
    features_ordered = ordered["feature"].tolist()
    y_positions = np.arange(len(features_ordered))

    figure, axis = plt.subplots(figsize=(9, 8.5))
    axis.grid(axis="x", alpha=0.3, zorder=0)
    axis.axvline(0.0, color="0.3", linewidth=1.0, zorder=1)
    marker_colors = [
        "tab:blue" if value >= 0 else "0.6"
        for value in ordered["permutation_importance_mean"]
    ]
    for y, feature, marker_color in zip(y_positions, features_ordered, marker_colors, strict=True):
        values = fold_df[feature].to_numpy()
        axis.plot(
            [values.min(), values.max()],
            [y, y],
            color="0.55",
            linewidth=2.2,
            solid_capstyle="round",
            alpha=0.6,
            zorder=2,
        )
        axis.scatter(
            [values.mean()],
            [y],
            color=marker_color,
            edgecolor="white",
            linewidth=0.6,
            s=70,
            zorder=3,
        )
    axis.set_yticks(y_positions)
    axis.set_yticklabels(features_ordered)
    axis.set_xlabel("permutation importance（シャッフルした時のbalanced_accuracyの低下量）")
    axis.set_title(
        f"特徴量重要度（{MODEL_DISPLAY_NAMES[model_name]}, {feature_set_label}, "
        "ダウンサンプリングあり）\n"
        "●＝5foldの平均、線＝5foldでの最小〜最大の範囲（右にあるほど重要、0付近・左は寄与なし）"
    )
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_feature_importance_agreement(
    importance_by_model: dict[str, pd.DataFrame],
    output_path: Path,
    *,
    feature_set_label: str = "全軸+ジャーク",
) -> None:
    """モデル間で重要度ランキングがどれだけ一致するかを、RF基準の順序で並べて示す。

    エラーバー・レンジ線は付けず、5fold平均の値だけを単純な横棒グラフで示す
    （fold間ばらつきの線が読みにくいという指摘を受け、モデル比較図はシンプルな
    棒グラフに戻した）。
    """
    rf_order = (
        importance_by_model["random_forest"]
        .sort_values("permutation_importance_mean", ascending=True)["feature"]
        .tolist()
    )
    figure, axis = plt.subplots(figsize=(10, 8.5))
    bar_height = 0.35
    y_positions = np.arange(len(rf_order))
    bar_colors = {"random_forest": "tab:blue", "svm": "tab:orange"}
    for offset, model_name in enumerate(("random_forest", "svm")):
        model_df = importance_by_model[model_name].set_index("feature")
        values = [model_df.loc[feature, "permutation_importance_mean"] for feature in rf_order]
        axis.barh(
            y_positions + (offset - 0.5) * bar_height,
            values,
            height=bar_height,
            color=bar_colors[model_name],
            label=MODEL_DISPLAY_NAMES[model_name],
        )
    axis.set_yticks(y_positions)
    axis.set_yticklabels(rf_order)
    axis.axvline(0.0, color="0.3", linewidth=0.8)
    axis.set_xlabel("permutation importance（シャッフルした時のbalanced_accuracyの低下量、5fold平均）")
    axis.set_title(
        f"特徴量重要度のモデル間比較（Random Forestの順序で表示、{feature_set_label}・ダウンサンプリングあり）"
    )
    axis.grid(axis="x", alpha=0.3)
    axis.legend(loc="lower right")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260909_feature_importance",
        help="Analysis directory. Figures and tables are created below it.",
    )
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of top-ranked features to keep in the reduced feature set.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    dataframe = build_analysis_dataframe(window_seconds=args.window_seconds)

    importance_by_model: dict[str, pd.DataFrame] = {}
    fold_df_by_model: dict[str, pd.DataFrame] = {}
    top_k_by_model: dict[str, list[str]] = {}
    for model_name in TARGET_MODEL_NAMES:
        importance_df, fold_df = compute_permutation_importance_cv(
            dataframe,
            model_name=model_name,
            feature_columns=ALL_FEATURE_COLUMNS,
            balance_classes=TARGET_BALANCE_CLASSES,
        )
        importance_by_model[model_name] = importance_df
        fold_df_by_model[model_name] = fold_df
        importance_df.to_csv(tables_dir / f"feature_importance_{model_name}.csv", index=False)
        fold_df.to_csv(tables_dir / f"feature_importance_{model_name}_by_fold.csv", index=False)
        plot_feature_importance(
            importance_df,
            fold_df,
            figures_dir / f"feature_importance_{model_name}.png",
            model_name=model_name,
        )

        print(f"\nFeature importance ({model_name}, permutation, balanced_accuracy, 5fold平均):")
        print(importance_df.round(4).to_string(index=False))

        top_k_features = importance_df.head(args.top_k)["feature"].tolist()
        top_k_by_model[model_name] = top_k_features
        (tables_dir / f"reduced_feature_set_{model_name}.txt").write_text(
            "\n".join(top_k_features) + "\n", encoding="utf-8"
        )
        print(f"Top {args.top_k} features ({model_name}): {top_k_features}")

    plot_feature_importance_agreement(
        importance_by_model, figures_dir / "feature_importance_agreement.png"
    )

    # モデル間のランキング一致度も記録しておく（RF上位10とSVM上位10の重なり）。
    common_top_k = sorted(
        set(top_k_by_model["random_forest"]) & set(top_k_by_model["svm"])
    )
    print(
        f"\nRF/SVM共通の上位{args.top_k}特徴量（{len(common_top_k)}個）: {common_top_k}"
    )
    merged_importance_df = importance_by_model["random_forest"][
        ["feature", "permutation_importance_mean"]
    ].rename(columns={"permutation_importance_mean": "random_forest_importance"}).merge(
        importance_by_model["svm"][["feature", "permutation_importance_mean"]].rename(
            columns={"permutation_importance_mean": "svm_importance"}
        ),
        on="feature",
    )
    merged_importance_df = merged_importance_df.sort_values(
        "random_forest_importance", ascending=False
    )
    merged_importance_df.to_csv(
        tables_dir / "feature_importance_rf_vs_svm.csv", index=False
    )

    comparison_rows: list[dict[str, float | str | int]] = []
    feature_sets: dict[str, list[str]] = {"all_18_features": ALL_FEATURE_COLUMNS}
    for model_name in TARGET_MODEL_NAMES:
        feature_sets[f"top_{args.top_k}_by_{model_name}"] = top_k_by_model[model_name]
    for feature_set_name, feature_columns in feature_sets.items():
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
                comparison_rows.append(summary)

    comparison_df = pd.DataFrame(comparison_rows)
    comparison_df.to_csv(tables_dir / "reduced_vs_full_feature_comparison.csv", index=False)
    print(f"\nSaved feature-importance outputs to: {output_dir}")
    print("\nReduced vs full feature set comparison:")
    print(
        comparison_df[
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
