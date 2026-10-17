"""Flat, step, and rough event feature analysis."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix
from sklearn.metrics import f1_score
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from src.legacy.config import load_config
from src.legacy.wheelchair_pipeline import AXIS_LINEAR_COLUMNS
from src.legacy.wheelchair_pipeline import build_multi_axis_dataset_dataframe
from src.legacy.wheelchair_pipeline import compute_overlap_ratio
from src.legacy.wheelchair_pipeline import load_world_dataframe
from src.legacy.wheelchair_pipeline import load_run_intervals_from_config

plt.rcParams["font.family"] = "Hiragino Sans"

AXES = ("x", "y", "z")
AXIS_DISPLAY_NAMES = {"x": "x軸", "y": "y軸", "z": "z軸（鉛直）"}
# CVモデル評価（build_pairwise_group_cv_summary / build_multiclass_group_cv）は
# 既存のz軸4特徴量のみを使い、分布図・テーブルの多軸拡張とは独立に維持する。
Z_FEATURE_COLUMNS = ["z_std", "z_range", "z_rms", "z_diff_max"]
AXIS_FEATURE_COLUMNS = {
    axis: [f"{axis}_std", f"{axis}_range", f"{axis}_rms", f"{axis}_diff_max"]
    for axis in AXES
}
FEATURE_COLUMNS = [
    feature for axis in AXES for feature in AXIS_FEATURE_COLUMNS[axis]
]
LABELS = ["flat", "dansa", "dekobo"]
DISPLAY_LABELS = {"flat": "flat", "dansa": "step", "dekobo": "rough"}
# 7/12 の 51 kg・有効セッション。71 kg の2走行は体重条件が異なるため除外する。
VALID_712_RUN_IDS = {
    "20260711201502",
    "20260711201718",
    "20260711201741",
    "20260711202154",
    "20260711202229",
    "20260711202302",
    "20260711202425",
    "20260711202454",
    "20260711202513",
    "20260711202657",
    "20260711202732",
}


def build_analysis_dataframe(
    *, window_seconds: float, axes: tuple[str, ...] = AXES
) -> pd.DataFrame:
    config_622 = deepcopy(load_config("configs/legacy/wheelchair_world_z_svm.yaml"))
    config_712 = deepcopy(load_config("configs/legacy/wheelchair_world_z_svm_712.yaml"))
    for config in (config_622, config_712):
        config["window"]["window_seconds"] = window_seconds

    dataset_622 = build_multi_axis_dataset_dataframe(config=config_622, axes=axes)
    dataset_712 = build_multi_axis_dataset_dataframe(
        config=config_712,
        run_ids=sorted(VALID_712_RUN_IDS),
        axes=axes,
    )
    return pd.concat([dataset_622, dataset_712], ignore_index=True)


def choose_representatives(dataframe: pd.DataFrame) -> pd.DataFrame:
    """各ラベルの z_std 分布の 25/50/75 パーセンタイルに近い窓を選ぶ。

    flat は前後2窓とも flat の候補に限定し、イベントは同一ラベルが連続する
    区間の中央側の候補に限定する。極端な一例を恣意的に選ばないための規則である。
    """
    candidate_frames: list[pd.DataFrame] = []
    for run_id, run_df in dataframe.groupby("run_id", sort=True):
        ordered = run_df.sort_values("window_id").copy()
        ordered["previous_label"] = ordered["label"].shift(1)
        ordered["next_label"] = ordered["label"].shift(-1)
        ordered["run_id"] = run_id
        candidate_frames.append(ordered)
    candidates = pd.concat(candidate_frames, ignore_index=True)

    selected: list[pd.Series] = []
    used_run_ids: set[str] = set()
    for label in LABELS:
        label_candidates = candidates[candidates["label"] == label].copy()
        if label == "flat":
            label_candidates = label_candidates[
                (label_candidates["previous_label"] == "flat")
                & (label_candidates["next_label"] == "flat")
            ]
        else:
            label_candidates = label_candidates[
                (label_candidates["previous_label"] == label)
                | (label_candidates["next_label"] == label)
            ]
        if len(label_candidates) < 3:
            raise ValueError(f"Not enough representative candidates for {label}")

        for quantile in (0.25, 0.50, 0.75):
            target = label_candidates["z_std"].quantile(quantile)
            ranked = label_candidates.assign(
                distance=lambda frame: (frame["z_std"] - target).abs(),
                already_used=lambda frame: frame["run_id"].isin(used_run_ids),
            ).sort_values(["already_used", "distance", "run_id", "window_id"])
            row = ranked.iloc[0]
            selected.append(row)
            used_run_ids.add(str(row["run_id"]))

    return pd.DataFrame(selected).drop(columns=["previous_label", "next_label"])


def load_run_waveform(run_id: str) -> pd.DataFrame:
    data_root = "wheelchair_data/6.22" if run_id.startswith("202606") else "wheelchair_data/7.12"
    path = Path(data_root) / "analysis/world_csv" / run_id / "acc_world.csv"
    return load_world_dataframe(path)


def plot_representative_waveforms(
    representatives: pd.DataFrame,
    output_path: Path,
    *,
    window_seconds: float,
    axis_key: str = "z",
) -> None:
    """代表window周辺の波形を描画する。

    代表windowの選定基準（z_std の25/50/75パーセンタイル、`choose_representatives`）
    は軸を変えても固定し、表示する波形だけを `axis_key` で切り替える。
    """
    world_column = AXIS_LINEAR_COLUMNS[axis_key]
    figure, axes = plt.subplots(
        nrows=3,
        ncols=3,
        figsize=(13, 9),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    y_min = np.inf
    y_max = -np.inf
    waveforms: list[tuple[pd.Series, pd.DataFrame]] = []
    for representative in representatives.itertuples(index=False):
        waveform = load_run_waveform(str(representative.run_id))
        center_ms = (float(representative.start_ms) + float(representative.end_ms)) / 2
        view = waveform[
            waveform["elapsed"].between(center_ms - 1500.0, center_ms + 1500.0)
        ].copy()
        view["relative_seconds"] = (view["elapsed"] - center_ms) / 1000.0
        values = view[world_column].to_numpy(dtype=float)
        y_min = min(y_min, float(np.min(values)))
        y_max = max(y_max, float(np.max(values)))
        waveforms.append((representative, view))

    margin = max(0.5, (y_max - y_min) * 0.08)
    for axis, (representative, waveform) in zip(axes.flat, waveforms, strict=True):
        axis.plot(
            waveform["relative_seconds"],
            waveform[world_column],
            color="tab:blue",
            marker="o",
            markersize=3,
            linewidth=1.2,
        )
        half_window = window_seconds / 2
        axis.axvspan(
            -half_window,
            half_window,
            color="tab:orange",
            alpha=0.18,
            label=f"selected {window_seconds:g} s",
        )
        axis.axvline(0.0, color="0.45", linewidth=0.8)
        axis.set_title(
            f"{DISPLAY_LABELS[representative.label]} | {representative.run_id}\n"
            f"window {int(representative.window_id)}, z_std={representative.z_std:.2f}"
        )
        axis.grid(alpha=0.3)
        axis.set_ylim(y_min - margin, y_max + margin)
    for axis in axes[-1, :]:
        axis.set_xlabel(f"選択した{window_seconds:g}秒窓の中心からの時間 [秒]")
    for axis in axes[:, 0]:
        axis.set_ylabel(f"{world_column} [m/s²]")
    figure.suptitle(
        f"代表的な{AXIS_DISPLAY_NAMES[axis_key]}加速度波形"
        f"（橙色：選択した{window_seconds:g}秒窓、選定基準はz_std）"
    )
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_feature_distributions(
    dataframe: pd.DataFrame,
    output_path: Path,
    *,
    features: list[str],
    axis_key: str = "z",
) -> None:
    figure, axes = plt.subplots(nrows=2, ncols=2, figsize=(11, 8))
    display = dataframe.assign(group=np.where(dataframe["label"] == "flat", "flat", "event"))
    for axis, feature in zip(axes.flat, features, strict=True):
        groups = [
            display.loc[display["group"] == group, feature].to_numpy(dtype=float)
            for group in ("flat", "event")
        ]
        axis.boxplot(
            groups,
            tick_labels=["flat", "event"],
            showfliers=False,
            medianprops={"color": "tab:orange", "linewidth": 1.5},
        )
        for index, values in enumerate(groups, start=1):
            # 全窓の重なりを見える化するため、決定的な乱数で横方向に散らす。
            rng = np.random.default_rng(42 + index)
            shown = values if len(values) <= 800 else rng.choice(values, size=800, replace=False)
            jitter = rng.normal(index, 0.045, size=len(shown))
            axis.scatter(jitter, shown, s=4, alpha=0.12, color="tab:blue")
        axis.set_title(feature)
        axis.set_ylabel("feature value")
        axis.grid(axis="y", alpha=0.3)
    figure.suptitle(
        f"flat と event（step + rough）の{AXIS_DISPLAY_NAMES[axis_key]}基本特徴量分布",
        y=0.98,
    )
    figure.legend(
        handles=[Line2D([], [], color="tab:orange", linewidth=1.5, label="中央値")],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        frameon=False,
    )
    figure.subplots_adjust(
        left=0.08, right=0.98, bottom=0.10, top=0.91, wspace=0.20, hspace=0.32
    )
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_three_class_feature_distributions(
    dataframe: pd.DataFrame,
    output_path: Path,
    *,
    features: list[str],
    axis_key: str = "z",
) -> None:
    figure, axes = plt.subplots(nrows=2, ncols=2, figsize=(11, 8))
    display = dataframe.assign(display_label=dataframe["label"].map(DISPLAY_LABELS))
    groups = ("flat", "step", "rough")
    for axis, feature in zip(axes.flat, features, strict=True):
        values_by_group = [
            display.loc[display["display_label"] == group, feature].to_numpy(dtype=float)
            for group in groups
        ]
        axis.boxplot(
            values_by_group,
            tick_labels=groups,
            showfliers=False,
            medianprops={"color": "tab:orange", "linewidth": 1.5},
        )
        for index, values in enumerate(values_by_group, start=1):
            rng = np.random.default_rng(42 + index)
            shown = values if len(values) <= 800 else rng.choice(values, size=800, replace=False)
            jitter = rng.normal(index, 0.045, size=len(shown))
            axis.scatter(jitter, shown, s=4, alpha=0.12, color="tab:blue")
        axis.set_title(feature)
        axis.set_ylabel("feature value")
        axis.grid(axis="y", alpha=0.3)
    figure.suptitle(
        f"flat・step・rough の{AXIS_DISPLAY_NAMES[axis_key]}基本特徴量分布", y=0.98
    )
    figure.legend(
        handles=[Line2D([], [], color="tab:orange", linewidth=1.5, label="中央値")],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        frameon=False,
    )
    figure.subplots_adjust(
        left=0.08, right=0.98, bottom=0.10, top=0.91, wspace=0.20, hspace=0.32
    )
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def cliffs_delta(left: np.ndarray, right: np.ndarray) -> float:
    """P(left > right) - P(left < right) を返す。"""
    comparisons = left[:, None] - right[None, :]
    return float((np.sum(comparisons > 0) - np.sum(comparisons < 0)) / comparisons.size)


def build_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    event = dataframe[dataframe["label"] != "flat"]
    flat = dataframe[dataframe["label"] == "flat"]
    for feature in FEATURE_COLUMNS:
        y_true = (dataframe["label"] != "flat").astype(int)
        auc = roc_auc_score(y_true, dataframe[feature])
        rows.append(
            {
                "feature": feature,
                "flat_median": flat[feature].median(),
                "flat_iqr": flat[feature].quantile(0.75) - flat[feature].quantile(0.25),
                "event_median": event[feature].median(),
                "event_iqr": event[feature].quantile(0.75) - event[feature].quantile(0.25),
                "event_minus_flat_median": event[feature].median() - flat[feature].median(),
                "window_auc_event_high": auc,
                "cliffs_delta_event_vs_flat": cliffs_delta(
                    event[feature].to_numpy(dtype=float),
                    flat[feature].to_numpy(dtype=float),
                ),
            }
        )
    return pd.DataFrame(rows)


def build_run_level_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    per_run = dataframe.assign(group=np.where(dataframe["label"] == "flat", "flat", "event"))
    per_run = per_run.groupby(["run_id", "group"], as_index=False)[FEATURE_COLUMNS].median()
    rows: list[dict[str, float | int | str]] = []
    for feature in FEATURE_COLUMNS:
        flat = per_run.loc[per_run["group"] == "flat", feature]
        event = per_run.loc[per_run["group"] == "event", feature]
        rows.append(
            {
                "feature": feature,
                "runs_with_flat": len(flat),
                "runs_with_event": len(event),
                "flat_run_median": flat.median(),
                "event_run_median": event.median(),
                "event_minus_flat_run_median": event.median() - flat.median(),
            }
        )
    return pd.DataFrame(rows)


def build_class_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    """3クラスの記述統計と、step/rough 間の単変量AUCを作る。"""
    rows: list[dict[str, float | str]] = []
    dansa = dataframe[dataframe["label"] == "dansa"]
    dekobo = dataframe[dataframe["label"] == "dekobo"]
    for feature in FEATURE_COLUMNS:
        row: dict[str, float | str] = {"feature": feature}
        for label, display_label in DISPLAY_LABELS.items():
            values = dataframe.loc[dataframe["label"] == label, feature]
            row[f"{display_label}_median"] = values.median()
            row[f"{display_label}_iqr"] = values.quantile(0.75) - values.quantile(0.25)
        pairwise = pd.concat([dansa, dekobo], ignore_index=True)
        row["auc_rough_high_vs_step"] = roc_auc_score(
            (pairwise["label"] == "dekobo").astype(int), pairwise[feature]
        )
        rows.append(row)
    return pd.DataFrame(rows)


def config_and_run_dir_for(run_id: str) -> tuple[dict, Path]:
    if run_id.startswith("202606"):
        return load_config("configs/legacy/wheelchair_world_z_svm.yaml"), Path("wheelchair_data/6.22") / run_id
    return load_config("configs/legacy/wheelchair_world_z_svm_712.yaml"), Path("wheelchair_data/7.12") / run_id


def build_event_feature_tables(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """イベントごとの窓特徴量と、そのイベント内要約値を作る。

    イベント区間はデータセット作成時と同じ定義（開始0.5秒前倒し、窓との重なり
    50%以上）を用いる。イベント内の中央値は、イベント時間が異なることを考慮した
    代表値であり、各窓の生の特徴量も別CSVに残す。
    """
    window_rows: list[dict[str, float | int | str]] = []
    threshold = 0.5
    for run_id, run_df in dataframe.groupby("run_id", sort=True):
        config, run_dir = config_and_run_dir_for(str(run_id))
        intervals_by_label = load_run_intervals_from_config(run_dir, config)
        for label in ("dansa", "dekobo"):
            labeled_windows = run_df[run_df["label"] == label]
            for event_number, interval in enumerate(intervals_by_label[label], start=1):
                start_ms, end_ms = interval
                overlap = labeled_windows.apply(
                    lambda row: compute_overlap_ratio(
                        window_start_ms=float(row["start_ms"]),
                        window_end_ms=float(row["end_ms"]),
                        intervals=[interval],
                    ),
                    axis=1,
                )
                event_windows = labeled_windows.loc[overlap >= threshold]
                event_id = f"{run_id}_{DISPLAY_LABELS[label]}_{event_number:02d}"
                for window in event_windows.itertuples(index=False):
                    window_rows.append(
                        {
                            "event_id": event_id,
                            "run_id": str(run_id),
                            "label": DISPLAY_LABELS[label],
                            "event_number_in_run": event_number,
                            "labeled_interval_start_ms": round(start_ms),
                            "labeled_interval_end_ms": round(end_ms),
                            "window_id": int(window.window_id),
                            "window_start_ms": int(window.start_ms),
                            "window_end_ms": int(window.end_ms),
                            **{
                                feature: getattr(window, feature)
                                for feature in FEATURE_COLUMNS
                            },
                        }
                    )

    event_windows_df = pd.DataFrame(window_rows)
    if event_windows_df.empty:
        raise ValueError("No labeled event windows found")
    summary = (
        event_windows_df.groupby(
            [
                "event_id",
                "run_id",
                "label",
                "event_number_in_run",
                "labeled_interval_start_ms",
                "labeled_interval_end_ms",
            ],
            as_index=False,
        )
        .agg(
            window_count=("window_id", "size"),
            **{
                f"{feature}_median": (feature, "median")
                for feature in FEATURE_COLUMNS
            },
            **{
                f"{feature}_mean": (feature, "mean")
                for feature in FEATURE_COLUMNS
            },
        )
        .sort_values(["label", "run_id", "event_number_in_run"])
    )
    return event_windows_df, summary


def build_pairwise_feature_auc(dataframe: pd.DataFrame) -> pd.DataFrame:
    """各クラス対の単一特徴量AUCを計算する。第2クラスを陽性（高値側）とする。"""
    pairs = [("flat", "dansa"), ("flat", "dekobo"), ("dansa", "dekobo")]
    rows: list[dict[str, float | str]] = []
    for first, second in pairs:
        pair_df = dataframe[dataframe["label"].isin([first, second])]
        y_true = (pair_df["label"] == second).astype(int)
        for feature in FEATURE_COLUMNS:
            rows.append(
                {
                    "comparison": f"{DISPLAY_LABELS[first]} vs {DISPLAY_LABELS[second]}",
                    "feature": feature,
                    "auc_second_class_high": roc_auc_score(y_true, pair_df[feature]),
                }
            )
    return pd.DataFrame(rows)


def build_pairwise_group_cv_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    """run をまたがない5分割CVで、基本特徴量によるペア分類を評価する。"""
    pairs = [("flat", "dansa"), ("flat", "dekobo"), ("dansa", "dekobo")]
    models = {
        "logistic_regression": make_pipeline(
            StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000)
        ),
        "rbf_svm": make_pipeline(StandardScaler(), SVC(C=1.0, class_weight="balanced")),
    }
    rows: list[dict[str, float | int | str]] = []
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    for first, second in pairs:
        pair_df = dataframe[dataframe["label"].isin([first, second])].copy()
        X = pair_df[Z_FEATURE_COLUMNS]
        y = pair_df["label"]
        groups = pair_df["run_id"]
        for model_name, model in models.items():
            predictions = cross_val_predict(model, X, y, groups=groups, cv=splitter)
            rows.append(
                {
                    "comparison": f"{DISPLAY_LABELS[first]} vs {DISPLAY_LABELS[second]}",
                    "model": model_name,
                    "windows": len(pair_df),
                    "runs": pair_df["run_id"].nunique(),
                    "balanced_accuracy": balanced_accuracy_score(y, predictions),
                    "macro_f1": f1_score(y, predictions, average="macro"),
                }
            )
    return pd.DataFrame(rows)


def build_multiclass_group_cv(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """run をまたがない5分割CVで3クラス分類の性能を評価する。"""
    model = make_pipeline(
        StandardScaler(), SVC(C=1.0, class_weight="balanced")
    )
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    X = dataframe[Z_FEATURE_COLUMNS]
    y = dataframe["label"]
    predictions = cross_val_predict(
        model,
        X,
        y,
        groups=dataframe["run_id"],
        cv=splitter,
    )
    summary = pd.DataFrame(
        [
            {
                "model": "rbf_svm",
                "windows": len(dataframe),
                "runs": dataframe["run_id"].nunique(),
                "balanced_accuracy": balanced_accuracy_score(y, predictions),
                "macro_f1": f1_score(y, predictions, labels=LABELS, average="macro"),
            }
        ]
    )
    matrix = confusion_matrix(y, predictions, labels=LABELS)
    matrix_df = pd.DataFrame(matrix, index=LABELS, columns=LABELS)
    matrix_df.index.name = "true_label"
    return summary, matrix_df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="data/analysis/20260721_flat_event",
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

    dataframe.to_csv(tables_dir / "window_features.csv", index=False)
    representatives = choose_representatives(dataframe)
    representatives.to_csv(tables_dir / "representative_windows.csv", index=False)
    for axis_key in AXES:
        # z軸は既存の分析結果と同じファイル名を維持し、x/y軸は接尾辞付きで追加する。
        suffix = "" if axis_key == "z" else f"_{axis_key}"
        plot_representative_waveforms(
            representatives,
            figures_dir / f"representative_waveforms{suffix}.png",
            window_seconds=args.window_seconds,
            axis_key=axis_key,
        )
        plot_feature_distributions(
            dataframe,
            figures_dir / f"feature_distributions{suffix}.png",
            features=AXIS_FEATURE_COLUMNS[axis_key],
            axis_key=axis_key,
        )
        plot_three_class_feature_distributions(
            dataframe,
            figures_dir / f"three_class_feature_distributions{suffix}.png",
            features=AXIS_FEATURE_COLUMNS[axis_key],
            axis_key=axis_key,
        )
    build_summary(dataframe).to_csv(tables_dir / "feature_summary.csv", index=False)
    build_run_level_summary(dataframe).to_csv(tables_dir / "run_level_summary.csv", index=False)
    build_class_summary(dataframe).to_csv(tables_dir / "class_feature_summary.csv", index=False)
    event_window_features, event_feature_summary = build_event_feature_tables(dataframe)
    event_window_features.to_csv(tables_dir / "event_window_features.csv", index=False)
    event_feature_summary.to_csv(tables_dir / "event_feature_summary.csv", index=False)
    pairwise_feature_auc = build_pairwise_feature_auc(dataframe)
    pairwise_feature_auc.to_csv(tables_dir / "pairwise_feature_auc.csv", index=False)
    pairwise_group_cv = build_pairwise_group_cv_summary(dataframe)
    pairwise_group_cv.to_csv(tables_dir / "pairwise_group_cv_summary.csv", index=False)
    multiclass_group_cv, multiclass_group_cv_matrix = build_multiclass_group_cv(dataframe)
    multiclass_group_cv.to_csv(tables_dir / "multiclass_group_cv_summary.csv", index=False)
    multiclass_group_cv_matrix.to_csv(
        tables_dir / "multiclass_group_cv_confusion_matrix.csv"
    )
    label_counts = dataframe["label"].value_counts().reindex(LABELS, fill_value=0)
    pd.DataFrame(
        [
            {
                "window_seconds": args.window_seconds,
                "stride_seconds": 0.25,
                "sampling_interval_seconds": 0.25,
                "windows": len(dataframe),
                "runs": dataframe["run_id"].nunique(),
                **label_counts.to_dict(),
            }
        ]
    ).to_csv(tables_dir / "analysis_metadata.csv", index=False)

    print(f"Saved analysis outputs to: {output_dir}")
    print("Label counts:")
    print(dataframe["label"].value_counts().sort_index().to_string())
    print("\nFeature summary:")
    print(build_summary(dataframe).round(3).to_string(index=False))
    print("\nRun-level summary:")
    print(build_run_level_summary(dataframe).round(3).to_string(index=False))
    print("\nThree-class feature summary:")
    print(build_class_summary(dataframe).round(3).to_string(index=False))
    print("\nEvent-level feature summary (median within each event):")
    print(event_feature_summary.round(3).to_string(index=False))
    print("\nPairwise single-feature AUC:")
    print(pairwise_feature_auc.round(3).to_string(index=False))
    print("\nPairwise run-group cross-validation:")
    print(pairwise_group_cv.round(3).to_string(index=False))
    print("\nThree-class run-group cross-validation:")
    print(multiclass_group_cv.round(3).to_string(index=False))
    print("\nRepresentative windows:")
    representative_output = representatives.assign(
        display_label=representatives["label"].map(DISPLAY_LABELS)
    )
    print(
        representative_output[
            ["display_label", "run_id", "window_id", "start_ms", "end_ms", "z_std"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
