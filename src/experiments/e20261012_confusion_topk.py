"""上位4個(x_kurt・y_range・y_kurt・z_kurt)と全18個の混同行列を比べる(2.0秒、xyz18、LOGO)。

使い方: python -m src.experiments.e20261012_confusion_topk <rear_only_dir>
"""

import sys
from pathlib import Path
import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from src.roadml.evaluation import models
from src.roadml.features import BASIC, SHAPE
from src.roadml.windows import build_run
from src.roadml.features import cols
L = ["flat", "dansa", "dekobo"]
dirs = sorted(p for p in Path(sys.argv[1]).iterdir() if (p / "acc.csv").exists())
df = pd.concat([build_run(d, 2.0, 5) for d in dirs], ignore_index=True)
for name, fc in {"all18": cols("xyz", BASIC + SHAPE), "top4": ["x_kurt", "y_range", "y_kurt", "z_kurt"]}.items():
    for mn, m in models().items():
        p = cross_val_predict(m, df[fc], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
        print(name, mn, "rows=true flat/step/rough, cols=pred")
        print(confusion_matrix(df["label"], p, labels=L))
