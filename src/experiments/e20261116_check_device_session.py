"""判定アプリ(apps/detector-android)が端末で記録したセッションを、PC で判定し直して、端末の判定と比べる。

端末の sessions/<日時>/ の input.csv(判定に使ったサンプル)を、PC の基準の実装(src/roadml/core_model.py。傾きの基準はモデルの model_info.json の tilt_ref)と
書き出したモデル(core_svm.onnx)で判定し、judge.csv(端末の特徴量・判定)と窓ごとに比べる。

使い方:
  adb pull /sdcard/Android/data/com.example.roaddetector/files/sessions/<日時> <置き場所>
  uv run python -m src.experiments.e20261116_check_device_session <置き場所>/<日時> [--version v4_20261118]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd

from src.roadml.core_model import CORE
from src.roadml.core_model import core_features
from src.roadml.core_model import load_raw
from src.roadml.core_model import signals

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "apps/detector-android/models"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--version", default="v4_20261118", help="端末に入れたモデルの版(models/ の下のフォルダ名)")
    args = parser.parse_args()
    raw = load_raw(args.session_dir, "input.csv")
    dt = np.diff(raw["ts"])
    print(f"サンプル {len(raw['ts'])}  間隔の中央値 {np.median(dt):.2f} ms({1000 / np.median(dt):.0f} Hz)"
          f"  長さ {(raw['ts'][-1] - raw['ts'][0]) / 1000:.1f} 秒")
    model_dir = MODELS_DIR / args.version
    tilt_ref = json.loads((model_dir / "model_info.json").read_text(encoding="utf-8"))["tilt_ref"]  # 端末と同じ基準
    pc = core_features(signals(raw, tilt_ref), 2.0, tilt_ref)
    sess = ort.InferenceSession(str(model_dir / "core_svm.onnx"), providers=["CPUExecutionProvider"])
    pc["pc_pred"] = sess.run(None, {"features": pc[CORE].to_numpy(np.float32)})[0]
    dev = pd.read_csv(args.session_dir / "judge.csv")
    both = dev.merge(pc, on="start_ms", suffixes=("_dev", "_pc"))
    print(f"窓: 端末 {len(dev)}  PC {len(pc)}  時刻が合った窓 {len(both)}")
    for c in CORE:
        d = np.abs(both[f"{c}_dev"] - both[f"{c}_pc"])
        print(f"  {c:10s} 差の最大 {d.max():.2e}")
    agree = (both["pred"] == both["pc_pred"]).mean()
    print(f"判定の一致: {agree:.4f}({int((both['pred'] != both['pc_pred']).sum())} 窓が不一致)")
    print("端末の判定の内訳:", dev["pred"].value_counts().to_dict())
    print(f"端末の時間: 推論 平均 {dev['infer_us'].mean() / 1000:.3f} ms・最大 {dev['infer_us'].max() / 1000:.3f} ms、"
          f"特徴量 平均 {dev['feature_us'].mean() / 1000:.3f} ms")


if __name__ == "__main__":
    main()
