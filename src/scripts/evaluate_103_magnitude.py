"""方針Aの10.3+10.4で、合成加速度(|a| - 重力)の特徴量を使った窓単位の評価を行う。

合成加速度は姿勢(回転ベクトル、約5Hz)や走行方向に依存しない。軸別(x,y,z)の特徴量と比べる。
評価の枠組み(窓・ラベル・LOGO・モデル)は evaluate_103_burst_segment と同じ。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.scripts.evaluate_103_baseline import LABELS
from src.scripts.evaluate_103_baseline import models
from src.scripts.evaluate_103_burst_segment import BASIC
from src.scripts.evaluate_103_burst_segment import BURST
from src.scripts.evaluate_103_burst_segment import SHAPE
from src.scripts.evaluate_103_burst_segment import build_run
from src.scripts.evaluate_103_burst_segment import summarize


def cols(axes: str, with_burst: bool, basic_only: bool = False) -> list[str]:
    feats = BASIC if basic_only else BASIC + SHAPE + (BURST if with_burst else [])
    return [f"{a}_{f}" for a in axes for f in feats]


FEATURE_SETS = {
    "m6(合成:基本+尖度+クレスト)": cols("m", False),
    "m10(合成:+バースト)": cols("m", True),
    "z10(参考:z軸+バースト)": cols("z", True),
    "xyz30(参考:3軸+バースト)": cols("xyz", True),
    "z+m(z軸と合成)": cols("zm", True),
    "xyz+m(3軸と合成)": cols("xyzm", True),
}

# 基本4特徴量(std, range, rms, diff_max)だけで、軸の組み合わせを比べる。
BASIC_SETS = {
    "z4(z軸)": cols("z", False, True),
    "m4(合成)": cols("m", False, True),
    "xyz12(3軸)": cols("xyz", False, True),
    "z+m 8(z軸と合成)": cols("zm", False, True),
    "xyz+m 16(3軸と合成)": cols("xyzm", False, True),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--windows", type=float, nargs="+", default=[1.0, 2.0])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--basic-only", action="store_true", help="基本4特徴量だけの比較を行う")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    feature_sets = BASIC_SETS if args.basic_only else FEATURE_SETS
    out_name = "magnitude_basic4_sweep.csv" if args.basic_only else "magnitude_sweep.csv"
    rows = []
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5) for d in run_dirs], ignore_index=True)
        print(f"\n=== 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
        for set_name, feature_cols in feature_sets.items():
            for model_name, model in models().items():
                pred = cross_val_predict(model, df[feature_cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
                result = summarize(df["label"], pred)
                rows.append({"window_s": window_s, "features": set_name, "model": model_name,
                             "n_features": len(feature_cols), **result})
                print(f"  {set_name:28s}{model_name:13s} bal_acc={result['bal_acc']:.3f} "
                      f"flat/step/rough={result['r_flat']:.2f}/{result['r_step']:.2f}/{result['r_rough']:.2f}", flush=True)
                if set_name.startswith(("m6", "m4")) and model_name == "SVM":
                    cm = confusion_matrix(df["label"], pred, labels=LABELS)
                    print(pd.DataFrame(cm, index=["flat", "step", "rough"], columns=["flat", "step", "rough"]).to_string())
    result_df = pd.DataFrame(rows)
    result_df.to_csv(out / out_name, index=False)
    print(result_df.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
