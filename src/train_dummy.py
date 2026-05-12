from __future__ import annotations

import argparse

from sklearn.datasets import make_classification
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from src.config import load_config
from src.models import build_model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(args.config)

    X, y = make_classification(
        n_samples=300,
        n_features=12,
        n_informative=6,
        n_redundant=2,
        n_classes=2,
        random_state=42,
    )

    test_size = config["evaluation"].get("test_size", 0.2)
    random_state = config["evaluation"].get("random_state", 42)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,
    )

    model = build_model(config)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    print("Confusion matrix:")
    print(confusion_matrix(y_test, y_pred))
    print()
    print("Classification report:")
    print(classification_report(y_test, y_pred))


if __name__ == "__main__":
    main()
