"""判定モデルを固定して ONNX に書き出し、PC 上で scikit-learn と同じ判定になるかを確かめる。

固定するモデル(第18回ゼミと 11.10 の企業 MTG の方針)
  特徴量 : core(z_rms・z_kurt・h_std・h_crest・tilt_range)。傾きの基準は --tilt-ref
           v1_20261116: ema30(時定数 30 秒の指数移動平均)
           v2_20261117: mean30(直近 30 秒の上向きの平均。Mizell 2003 の窓の平均。Hemminki ら 2013 で窓 30 秒が一番よかった)
           v3_20261118: mean10(直近 10 秒の上向きの平均。第19回ゼミで採用。v2 より step の再現率がわずかに高い 0.972 → 0.976)
           v4_20261118: startmean10(窓の最初のサンプルの時点の mean10 を、窓の中で固定。docs/knowledge/2026-11-18)
           (v1〜v3 は e20261116_tilt_reference で、セッション全体の中央値と同じかそれ以上の精度を確認。
            v4 は flat が 0.955 → 0.950、step・rough は中央値より上)
  ラベル : 段差は一番大きな衝撃の 0.5 秒前〜STOP、凸凹は START + 1 秒〜STOP(方針A)
  モデル : StandardScaler + SVM(RBF、C=1、gamma=scale、class_weight=balanced)
  データ : 汎用・68〜69 kg の 16 セッション全部(評価は LOGO で済んでいるので、書き出す前に全部で学習し直す)。
           STOP が遅れた凸凹の通過(configs/sessions/excluded_passes.csv。計測2-2 の #9・#11)は除く
  窓     : 2.0 秒、0.5 秒ずつずらす

確かめること
  1. 学習に使った窓で、scikit-learn と onnxruntime の判定が一致するか(入力は float32)
  2. アプリで判定するのと同じく、セッションの全部の窓(ラベルの無い区間も含む)で一致するか

出力
  apps/detector-android/models/<--version>/(モデルはアプリ側で版ごとに管理する。models/README.md)
    core_svm.onnx        : 書き出したモデル
    model_info.json      : 版、特徴量の順番、クラス、学習の条件、LOGO の精度、使ったライブラリの版
  data/analysis/20261116_export_onnx/
    parity/<session>.csv : 全部の窓の特徴量と、scikit-learn・onnxruntime の判定(アプリの単体テストの正解)
    parity_summary.csv   : セッションごとの一致率

使い方: uv run python -m src.experiments.e20261116_export_onnx --version v4_20261118 --tilt-ref startmean10
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import date
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
import skl2onnx
import sklearn
from skl2onnx import to_onnx
from skl2onnx.common.data_types import FloatTensorType

from src.experiments.e20261116_tilt_reference import excluded_passes
from src.experiments.e20261116_tilt_reference import labeled_windows
from src.experiments.e20261116_tilt_reference import session_list
from src.roadml.core_model import CORE
from src.roadml.core_model import WINDOW_S
from src.roadml.core_model import core_features
from src.roadml.core_model import load_raw
from src.roadml.core_model import signals
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261116_export_onnx"
MODELS_DIR = ROOT / "apps/detector-android/models"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v4_20261118", help="モデルの版(models/ の下のフォルダ名)")
    parser.add_argument("--tilt-ref", default="startmean10", help="傾きの基準(src/roadml/core_model.py)")
    args = parser.parse_args()
    tilt_ref = args.tilt_ref
    model_dir = MODELS_DIR / args.version
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "core_svm.onnx"
    (OUT / "parity").mkdir(parents=True, exist_ok=True)
    meta = session_list()
    train = labeled_windows(meta, tilt_ref).dropna(subset=["label"]).reset_index(drop=True)
    model = models()["SVM"].fit(train[CORE].to_numpy(), train["label"].to_numpy())
    print("クラス:", list(model.classes_), " 学習の窓:", train["label"].value_counts().to_dict())

    onx = to_onnx(model, initial_types=[("features", FloatTensorType([None, len(CORE)]))],
                  options={id(model.steps[-1][1]): {"zipmap": False}}, target_opset={"": 17, "ai.onnx.ml": 3})
    model_path.write_bytes(onx.SerializeToString())
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    print("ONNX の入力:", [(i.name, i.shape, i.type) for i in sess.get_inputs()])
    print("ONNX の出力:", [(o.name, o.shape, o.type) for o in sess.get_outputs()])

    def run_onnx(x: np.ndarray):
        label, scores = sess.run(None, {"features": x.astype(np.float32)})
        return np.asarray(label), np.asarray(scores)

    lab, _ = run_onnx(train[CORE].to_numpy())
    sk = model.predict(train[CORE].to_numpy())
    print(f"学習に使った窓: 一致 {np.mean(lab == sk):.4f}({int(np.sum(lab != sk))} 窓が不一致 / {len(sk)})")

    summary = []
    for s, d in zip(meta["session_id"], meta["day"]):
        win = core_features(signals(load_raw(ROOT / "wheelchair_data" / d / s), tilt_ref), WINDOW_S, tilt_ref)
        x = win[CORE].to_numpy()
        lab, scores = run_onnx(x)
        sk_pred, sk_dec = model.predict(x), model.decision_function(x)
        out = win.assign(sk_pred=sk_pred, onnx_pred=lab)
        for i, c in enumerate(model.classes_):
            out[f"onnx_score_{c}"] = scores[:, i]
            out[f"sk_score_{c}"] = sk_dec[:, i]
        out.to_csv(OUT / "parity" / f"{s}.csv", index=False)
        diff = np.abs(scores - sk_dec).max()
        summary.append({"session": s, "day": d, "n_windows": len(win), "agree": float(np.mean(lab == sk_pred)),
                        "n_disagree": int(np.sum(lab != sk_pred)), "max_score_diff": float(diff)})
        print(f"{s}: 窓 {len(win)}  一致 {summary[-1]['agree']:.4f}  スコアの差の最大 {diff:.2e}")
    pd.DataFrame(summary).to_csv(OUT / "parity_summary.csv", index=False)

    x1 = train[CORE].to_numpy()[:1].astype(np.float32)
    t0 = time.perf_counter()
    for _ in range(1000):
        sess.run(None, {"features": x1})
    print(f"onnxruntime(PC)の 1 窓あたりの推論時間: {(time.perf_counter() - t0):.3f} ms")

    logo = pd.read_csv(ROOT / "data/analysis/20261116_tilt_reference/results.csv").set_index("tilt_ref").loc[tilt_ref]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    info = {"version": args.version, "created": date.today().isoformat(),
            "research_repo_commit": commit + "(書き出したときの HEAD。作業中の変更を含むことがある)",
            "export_script": "src/experiments/e20261116_export_onnx.py",
            "features": CORE, "classes": [str(c) for c in model.classes_],
            "display": {"flat": "flat", "dansa": "step", "dekobo": "rough"},
            "window_s": WINDOW_S, "stride_s": 0.5, "min_fill": 0.8, "tilt_ref": tilt_ref, "gravity": 9.80665,
            "sampling_hz_trained": 333, "label_condition": "peak0.5", "sessions": list(meta["session_id"]),
            "excluded_passes": [f"{r.session_id} {r.kind} #{r.pass_id}" for r in excluded_passes().itertuples()],
            "n_train": {str(k): int(v) for k, v in train["label"].value_counts().items()},
            "n_support_vectors": int(model.steps[-1][1].support_vectors_.shape[0]),
            "logo_recall": {"flat": round(float(logo["r_flat"]), 3), "step": round(float(logo["r_step"]), 3),
                            "rough": round(float(logo["r_rough"]), 3)},
            "libraries": {"scikit-learn": sklearn.__version__, "skl2onnx": skl2onnx.__version__,
                          "onnxruntime": ort.__version__},
            "onnx_input": "features float32 [N, 5]",
            "onnx_outputs": "label string [N], probabilities float32 [N, 3](SVM の決定関数の値。確率ではない)"}
    (model_dir / "model_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("書き出した先:", model_dir.relative_to(ROOT), " サポートベクターの数:", info["n_support_vectors"],
          " モデルの大きさ:", model_path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
