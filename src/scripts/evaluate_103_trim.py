"""event 区間の開始側を数秒削った(削った窓は学習にも評価にも使わない)ときの窓単位の精度を比べる。

計測は「ゆっくり進みながらボタンを押す→障害物へ進む→終了」の流れなので、区間の冒頭は
まだ障害物に着いていない可能性がある。冒頭の窓のラベルが不正確な影響を見る。
削り幅 0 秒は区間開始そのまま、"base" は従来設定(開始の0.5秒前から含める)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.scripts.evaluate_103_baseline import models
from src.scripts.evaluate_103_burst_segment import build_run
from src.scripts.evaluate_103_burst_segment import summarize
from src.scripts.evaluate_103_magnitude import cols

FEATURE_SETS = {
    "z4": cols("z", False, True),
    "m4": cols("m", False, True),
    "xyz12": cols("xyz", False, True),
    "z10(+尖度クレスト+バースト)": cols("z", True),
    "m10(+尖度クレスト+バースト)": cols("m", True),
    "xyz30(+尖度クレスト+バースト)": cols("xyz", True),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--windows", type=float, nargs="+", default=[1.0, 2.0])
    parser.add_argument("--trims", type=float, nargs="+", default=[0.0, 1.0, 2.0, 3.0])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    conditions = [("base(-0.5s)", 500.0)] + [(f"{t:g}s", -1000.0 * t) for t in args.trims]
    rows = []
    for window_s in args.windows:
        for cond, pre_ms in conditions:
            df = pd.concat([build_run(d, window_s, 5, pre_ms) for d in run_dirs], ignore_index=True)
            counts = df["label"].value_counts().to_dict()
            print(f"\n=== 窓{window_s}s 冒頭の削り={cond} 窓数 flat={counts.get('flat')} step={counts.get('dansa')} rough={counts.get('dekobo')}", flush=True)
            for set_name, feature_cols in FEATURE_SETS.items():
                for model_name, model in models().items():
                    pred = cross_val_predict(model, df[feature_cols], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
                    result = summarize(df["label"], pred)
                    rows.append({"window_s": window_s, "trim": cond, "features": set_name, "model": model_name,
                                 "n_flat": counts.get("flat"), "n_step": counts.get("dansa"), "n_rough": counts.get("dekobo"),
                                 **result})
                    print(f"  {set_name:30s}{model_name:13s} bal_acc={result['bal_acc']:.3f}", flush=True)
    result_df = pd.DataFrame(rows)
    result_df.to_csv(out / "trim_sweep.csv", index=False)


if __name__ == "__main__":
    main()
