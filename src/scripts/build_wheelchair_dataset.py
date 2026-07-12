from __future__ import annotations

import argparse

from src.config import load_config
from src.wheelchair_pipeline import build_dataset_dataframe
from src.wheelchair_pipeline import build_dataset_output_path
from src.wheelchair_pipeline import save_dataset_dataframe


def print_summary(output_path, dataframe) -> None:
    print(f"Saved wheelchair dataset to: {output_path}")
    print(f"Runs: {dataframe['run_id'].nunique() if not dataframe.empty else 0}")
    print(f"Windows: {len(dataframe)}")
    print("Label counts:")
    for label, count in dataframe["label"].value_counts().sort_index().items():
        print(f"  {label}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", action="append")
    args = parser.parse_args()

    config = load_config(args.config)
    dataframe = build_dataset_dataframe(config=config, run_ids=args.run_id)
    output_path = build_dataset_output_path(config)
    saved_path = save_dataset_dataframe(dataframe, output_path)
    print_summary(saved_path, dataframe)


if __name__ == "__main__":
    main()
