from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from src.config import load_config
from src.models import build_model
from src.wheelchair_pipeline import build_processed_output_dir

METADATA_COLUMNS = ["run_id", "window_id", "start_ms", "end_ms"]
LABEL_COLUMN = "label"


def load_dataset_dataframe(input_path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(input_path)
    required_columns = [*METADATA_COLUMNS, LABEL_COLUMN]
    missing_columns = [
        column for column in required_columns if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing required columns in dataset CSV: {joined}")
    dataframe["run_id"] = dataframe["run_id"].astype(str)
    dataframe[LABEL_COLUMN] = dataframe[LABEL_COLUMN].astype(str)
    return dataframe


def select_feature_columns(dataframe: pd.DataFrame) -> list[str]:
    excluded_columns = {LABEL_COLUMN, *METADATA_COLUMNS}
    feature_columns = [
        column for column in dataframe.columns if column not in excluded_columns
    ]
    if not feature_columns:
        raise ValueError("No feature columns found in dataset CSV")
    return feature_columns


def validate_run_ids(
    dataframe: pd.DataFrame,
    *,
    train_run_ids: list[str],
    eval_run_ids: list[str],
) -> None:
    available_run_ids = set(dataframe["run_id"].astype(str))
    missing_train_run_ids = sorted(set(train_run_ids) - available_run_ids)
    missing_eval_run_ids = sorted(set(eval_run_ids) - available_run_ids)
    if missing_train_run_ids:
        joined = ", ".join(missing_train_run_ids)
        raise ValueError(f"Unknown train run_id: {joined}")
    if missing_eval_run_ids:
        joined = ", ".join(missing_eval_run_ids)
        raise ValueError(f"Unknown eval run_id: {joined}")
    overlapping_run_ids = sorted(set(train_run_ids) & set(eval_run_ids))
    if overlapping_run_ids:
        joined = ", ".join(overlapping_run_ids)
        raise ValueError(f"run_id cannot be both train and eval: {joined}")


def filter_by_run_ids(dataframe: pd.DataFrame, run_ids: list[str]) -> pd.DataFrame:
    filtered = dataframe[dataframe["run_id"].isin(run_ids)].copy()
    if filtered.empty:
        joined = ", ".join(run_ids)
        raise ValueError(f"No rows found for run_ids: {joined}")
    return filtered


def build_dataset(
    dataframe: pd.DataFrame,
    *,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    X = dataframe[feature_columns]
    y = dataframe[LABEL_COLUMN].astype(str)
    return X, y


def save_classification_report(
    report_text: str,
    output_dir: Path,
    model_name: str,
    eval_name: str,
) -> Path:
    output_path = output_dir / f"classification_report_{model_name}_{eval_name}.txt"
    output_path.write_text(report_text, encoding="utf-8")
    return output_path


def save_confusion_matrix(
    matrix,
    output_dir: Path,
    model_name: str,
    eval_name: str,
    labels: list[str],
) -> Path:
    output_path = output_dir / f"confusion_matrix_{model_name}_{eval_name}.csv"
    matrix_df = pd.DataFrame(matrix, index=labels, columns=labels)
    matrix_df.to_csv(output_path, index_label="label")
    return output_path


def save_run_split(
    *,
    output_dir: Path,
    train_run_ids: list[str],
    eval_run_ids: list[str],
) -> Path:
    output_path = output_dir / "run_split.txt"
    lines = [
        f"train_run_ids={','.join(train_run_ids)}",
        f"eval_run_ids={','.join(eval_run_ids)}",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def print_summary(
    *,
    input_path: str,
    model_name: str,
    train_run_ids: list[str],
    eval_run_ids: list[str],
    train_samples: int,
    eval_samples: int,
    output_dir: Path,
) -> None:
    print(f"Dataset: {input_path}")
    print(f"Model: {model_name}")
    print(f"Train runs: {', '.join(train_run_ids)}")
    print(f"Eval runs: {', '.join(eval_run_ids)}")
    print(f"Train samples: {train_samples}")
    print(f"Eval samples: {eval_samples}")
    print(f"Saved evaluation to: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--train-run-id", required=True, action="append")
    parser.add_argument("--eval-run-id", required=True, action="append")
    args = parser.parse_args()

    config = load_config(args.config)
    if config["label"].get("mode") != "multiclass":
        raise ValueError(
            "This training CLI currently supports only label.mode=multiclass"
        )

    label_order = config["label"].get("labels", ["flat", "dansa", "dekobo"])
    dataframe = load_dataset_dataframe(args.input)
    validate_run_ids(
        dataframe,
        train_run_ids=args.train_run_id,
        eval_run_ids=args.eval_run_id,
    )

    feature_columns = select_feature_columns(dataframe)
    train_dataframe = filter_by_run_ids(dataframe, args.train_run_id)
    eval_dataframe = filter_by_run_ids(dataframe, args.eval_run_id)
    X_train, y_train = build_dataset(train_dataframe, feature_columns=feature_columns)

    model = build_model(config)
    model.fit(X_train, y_train)

    model_name = config["model"]["name"]
    output_dir = build_processed_output_dir(config)
    save_run_split(
        output_dir=output_dir,
        train_run_ids=args.train_run_id,
        eval_run_ids=args.eval_run_id,
    )

    for eval_run_id in args.eval_run_id:
        per_run_dataframe = filter_by_run_ids(dataframe, [eval_run_id])
        X_eval, y_eval = build_dataset(
            per_run_dataframe,
            feature_columns=feature_columns,
        )
        y_pred = model.predict(X_eval)
        report_text = classification_report(
            y_eval,
            y_pred,
            labels=label_order,
            digits=4,
            zero_division=0,
        )
        matrix = confusion_matrix(y_eval, y_pred, labels=label_order)
        save_classification_report(report_text, output_dir, model_name, eval_run_id)
        save_confusion_matrix(matrix, output_dir, model_name, eval_run_id, label_order)

    X_eval_all, y_eval_all = build_dataset(
        eval_dataframe,
        feature_columns=feature_columns,
    )
    y_pred_all = model.predict(X_eval_all)
    report_text_all = classification_report(
        y_eval_all,
        y_pred_all,
        labels=label_order,
        digits=4,
        zero_division=0,
    )
    matrix_all = confusion_matrix(y_eval_all, y_pred_all, labels=label_order)
    save_classification_report(report_text_all, output_dir, model_name, "all_eval")
    save_confusion_matrix(matrix_all, output_dir, model_name, "all_eval", label_order)
    print_summary(
        input_path=args.input,
        model_name=model_name,
        train_run_ids=args.train_run_id,
        eval_run_ids=args.eval_run_id,
        train_samples=len(X_train),
        eval_samples=len(X_eval_all),
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
