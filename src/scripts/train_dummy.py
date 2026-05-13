from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from src.config import load_config
from src.models import build_model

METADATA_COLUMNS = ["window_id", "window_start_ms", "window_end_ms", "n_samples"]
LABEL_COLUMN = "label"
CONFUSION_MATRIX_LABELS = [0, 1, 2]


def load_feature_dataframe(input_path: str | Path) -> pd.DataFrame:
    dataframe = pd.read_csv(input_path)
    if LABEL_COLUMN not in dataframe.columns:
        raise ValueError(f"Missing required column: {LABEL_COLUMN}")
    return dataframe


def select_feature_columns(dataframe: pd.DataFrame) -> list[str]:
    excluded_columns = {LABEL_COLUMN, *METADATA_COLUMNS}
    feature_columns = [
        column for column in dataframe.columns if column not in excluded_columns
    ]
    if not feature_columns:
        raise ValueError("No feature columns found in input CSV")
    return feature_columns


def build_dataset(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    feature_columns = select_feature_columns(dataframe)
    X = dataframe[feature_columns]
    y = dataframe[LABEL_COLUMN].astype(int)
    return X, y


def build_eval_dataset(
    dataframe: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    missing_columns = [
        column for column in feature_columns if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Missing feature columns in eval CSV: {joined}")
    X = dataframe[feature_columns]
    y = dataframe[LABEL_COLUMN].astype(int)
    return X, y


def build_output_dir(processed_root_dir: str | Path) -> Path:
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir = Path(processed_root_dir) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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
) -> Path:
    output_path = output_dir / f"confusion_matrix_{model_name}_{eval_name}.csv"
    matrix_df = pd.DataFrame(
        matrix,
        index=CONFUSION_MATRIX_LABELS,
        columns=CONFUSION_MATRIX_LABELS,
    )
    matrix_df.to_csv(output_path, index_label="label")
    return output_path


def print_summary(
    *,
    train_input_path: str,
    eval_input_path: str,
    model_name: str,
    train_samples: int,
    eval_samples: int,
    output_dir: Path,
    report_text: str,
) -> None:
    print(f"Train feature data: {train_input_path}")
    print(f"Eval feature data: {eval_input_path}")
    print(f"Model: {model_name}")
    print(f"Train samples: {train_samples}")
    print(f"Eval samples: {eval_samples}")
    print(f"Saved evaluation to: {output_dir}")
    print()
    print("Classification report:")
    print(report_text)


def build_eval_name(input_path: str | Path) -> str:
    input_file = Path(input_path)
    return input_file.stem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--train-input", required=True)
    parser.add_argument("--eval-input", required=True, action="append")
    args = parser.parse_args()

    config = load_config(args.config)
    if config["label"].get("mode") != "multiclass":
        raise ValueError(
            "This training CLI currently supports only label.mode=multiclass"
        )

    train_dataframe = load_feature_dataframe(args.train_input)
    feature_columns = select_feature_columns(train_dataframe)
    X_train, y_train = build_dataset(train_dataframe)

    model = build_model(config)
    model.fit(X_train, y_train)
    model_name = config["model"]["name"]
    output_dir = build_output_dir(config["data"]["processed_dir"])

    for eval_input in args.eval_input:
        eval_dataframe = load_feature_dataframe(eval_input)
        X_eval, y_eval = build_eval_dataset(eval_dataframe, feature_columns)
        y_pred = model.predict(X_eval)
        report_text = classification_report(
            y_eval,
            y_pred,
            labels=CONFUSION_MATRIX_LABELS,
            digits=4,
        )
        matrix = confusion_matrix(
            y_eval,
            y_pred,
            labels=CONFUSION_MATRIX_LABELS,
        )
        eval_name = build_eval_name(eval_input)
        save_classification_report(report_text, output_dir, model_name, eval_name)
        save_confusion_matrix(matrix, output_dir, model_name, eval_name)
        print_summary(
            train_input_path=args.train_input,
            eval_input_path=eval_input,
            model_name=model_name,
            train_samples=len(X_train),
            eval_samples=len(X_eval),
            output_dir=output_dir,
            report_text=report_text,
        )


if __name__ == "__main__":
    main()
