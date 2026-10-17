from __future__ import annotations

from typing import Any

from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


def build_model(config: dict[str, Any]):
    model_config = config["model"]
    model_name = model_config["name"]

    if model_name == "svm":
        # SVMは特徴量のスケールに敏感なため，標準化を含める．
        return Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    SVC(
                        kernel=model_config.get("kernel", "rbf"),
                        C=model_config.get("C", 1.0),
                        gamma=model_config.get("gamma", "scale"),
                        class_weight=model_config.get("class_weight", "balanced"),
                    ),
                ),
            ]
        )

    if model_name == "random_forest":
        # Random Forestは標準化が必須ではないため，分類器のみとする．
        return RandomForestClassifier(
            n_estimators=model_config.get("n_estimators", 200),
            max_depth=model_config.get("max_depth", None),
            class_weight=model_config.get("class_weight", "balanced"),
            random_state=model_config.get("random_state", 42),
            n_jobs=-1,
        )

    raise ValueError(f"Unknown model name: {model_name}")
