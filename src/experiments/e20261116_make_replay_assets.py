"""Android アプリの「再生」(記録済みのデータを判定の処理に流し、PC の判定と比べる)に使うデータを作る。

段差・凸凹・flat から 1 セッションずつ(11.1、68〜69 kg、汎用の車椅子)。
  <session>_input.csv.gz : acc.csv から、判定に使う列だけ(timestamp・accX/Y/Z・rotX/Y/Z/W)。値は書き換えない
    → デバッグ版のアプリにだけ入れる(apps/detector-android/app/src/debug/assets/replay/)。モデルが変わっても同じ
  <session>_expected.csv : そのモデルでの PC の判定(e20261116_export_onnx の parity/<session>.csv の start_ms・onnx_pred)
    → モデルの版のフォルダに置く(apps/detector-android/models/<--version>/replay/)。モデルを変えたら作り直す
"""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "apps/detector-android/app/src/debug/assets/replay"
MODELS_DIR = ROOT / "apps/detector-android/models"
SESSIONS = {"20261101142339": "11.1", "20261101143126": "11.1", "20261101143455": "11.1"}  # step・rough・flat
COLUMNS = ["timestamp", "accX", "accY", "accZ", "rotX", "rotY", "rotZ", "rotW"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v4_20261118", help="モデルの版(models/ の下のフォルダ名)")
    args = parser.parse_args()
    expected_dir = MODELS_DIR / args.version / "replay"
    OUT.mkdir(parents=True, exist_ok=True)
    expected_dir.mkdir(parents=True, exist_ok=True)
    for s, d in SESSIONS.items():
        src = ROOT / "wheelchair_data" / d / s / "acc.csv"
        # 文字列のまま写す(数値に直して書き戻すと、桁が変わるおそれがあるため)
        acc = pd.read_csv(src, usecols=COLUMNS, dtype=str)[COLUMNS]
        with gzip.open(OUT / f"{s}_input.csv.gz", "wt", encoding="utf-8") as f:
            acc.to_csv(f, index=False)
        par = pd.read_csv(ROOT / "data/analysis/20261116_export_onnx/parity" / f"{s}.csv")
        par[["start_ms", "onnx_pred"]].to_csv(expected_dir / f"{s}_expected.csv", index=False)
        print(s, len(acc), "行", (OUT / f"{s}_input.csv.gz").stat().st_size // 1024, "KB", len(par), "窓")


if __name__ == "__main__":
    main()
