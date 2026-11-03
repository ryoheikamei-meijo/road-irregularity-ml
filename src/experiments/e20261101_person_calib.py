"""人ごとの平坦路の基準で割る補正(体重の違い)が効くかを調べる(10.31 + 11.1)。

11.1 に、2 人が同じ平坦路を続けて走ったセッションがある(GPS の位置の差は約 2 m)。これを人ごとの基準にする。
  51 kg の人     : 20261101141139(14:11)
  68〜69 kg の人 : 20261101141253(14:12)。10.31(68 kg)の同じ人のセッションにも使う
基準のセッションは、学習にもテストにも使わない(補正なしも同じセッションを除いて比べる)。

補正:
  none : 補正なし
  P    : 揺れの大きさの特徴量(z・h の基本4)を、その人の基準のセッションの窓の中央値で割る
         (基準の窓は、止まっていない窓(z_rms >= 1.0)だけ。窓の長さは評価と同じ)
  P2   : P に加えて、傾きの大きさ(tilt_range・tilt_std、g の基本4)も同じように割る

テスト(SVM、窓 1.0・2.0 秒、START を 1 秒ずらす方針A):
  light2heavy : 51 kg(5 セッション)で学習 → 68〜69 kg(17 セッション)でテスト
  heavy2light : 68〜69 kg(17 セッション)で学習 → 51 kg(5 セッション)でテスト
  上限        : 2 人を合わせたセッション単位の LOGO で、テスト側だけを集計(補正なし)
人ごとに 1 つの数で割るので、同じ人の中だけの評価(LOGO)は、補正の有無で変わらない(標準化するため)。

出力(data/analysis/20261101_person_calib/):
  results.csv    : テスト・補正・特徴量・窓ごとのクラス別の再現率
  confusion.csv  : 混同行列
  reference.csv  : 人ごとの基準の値
  pair_ratio.csv : 同じ場所の組(51 kg ÷ 69 kg)の、補正の前後の比
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_correction_eval import ACC_AMP
from src.experiments.e20261101_correction_eval import GYRO_AMP
from src.experiments.e20261101_correction_eval import MOVING_Z
from src.experiments.e20261101_correction_eval import PAIRS
from src.experiments.e20261101_correction_eval import build
from src.experiments.e20261101_gyro_features import CORE5
from src.experiments.e20261101_gyro_features import HZ12
from src.experiments.e20261101_gyro_features import add_gyro
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_person_calib"
WINDOWS_S = [1.0, 2.0]
FEATURE_SETS = {"core5": CORE5, "hz12": HZ12}
REFERENCE = {"51kg": "20261101141139", "68-69kg": "20261101141253"}
CORRECTIONS = {"none": [], "P": ACC_AMP, "P2": ACC_AMP + GYRO_AMP}
TESTS = {"light2heavy": ("51kg", "68-69kg"), "heavy2light": ("68-69kg", "51kg")}


def recall_row(y: np.ndarray, pred: np.ndarray) -> dict:
    return {f"r_{DISPLAY[k]}": float((pred[y == k] == k).mean()) if (y == k).any() else np.nan for k in LABELS}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = load_meta(["10.31", "11.1"], "standard", [68, 69, 51])
    meta["person"] = np.where(meta["weight_kg"] == 51, "51kg", "68-69kg")
    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s  # 読むだけ
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    person_of = dict(zip(meta["session_id"], meta["person"]))
    groups = {p: [s for s in meta.loc[meta["person"] == p, "session_id"] if s not in REFERENCE.values()]
              for p in REFERENCE}
    print("使うセッション(基準を除く):", {p: len(v) for p, v in groups.items()})

    rows, conf_rows, ref_rows, pair_rows = [], [], [], []
    for window_s in WINDOWS_S:
        tables = build(sessions, passes, dict(zip(meta["session_id"], meta["kind"])), window_s)
        ref = {}
        for p, s in REFERENCE.items():
            t = tables[s]
            ref[p] = t.loc[t["z_rms"] >= MOVING_Z, ACC_AMP + GYRO_AMP].median()
            ref_rows.append({"window_s": window_s, "person": p, "session": s, **ref[p].to_dict()})
        print(f"\n== 窓 {window_s:.1f} 秒  基準の z_rms: " + "  ".join(f"{p} {ref[p]['z_rms']:.2f}" for p in ref))

        def labeled(s: str, method: str) -> pd.DataFrame:
            t = tables[s].dropna(subset=["label"]).copy()
            f = CORRECTIONS[method]
            if f:
                t[f] = t[f] / ref[person_of[s]][f]
            return t

        for name, a, b in PAIRS["weight"]:
            if a in REFERENCE.values() or b in REFERENCE.values():
                continue
            row = {"window_s": window_s, "place": name, "session": a, "ref": b}
            for method in CORRECTIONS:
                for f in ["z_rms", "h_rms", "tilt_range"]:
                    row[f"{f}_{method}_ratio"] = labeled(a, method)[f].median() / labeled(b, method)[f].median()
            pair_rows.append(row)

        for (fs_name, features), method, (test_name, (tr, te)) in itertools.product(
                FEATURE_SETS.items(), CORRECTIONS, TESTS.items()):
            train = pd.concat([labeled(s, method) for s in groups[tr]], ignore_index=True)
            test = pd.concat([labeled(s, method) for s in groups[te]], ignore_index=True)
            pred = models()["SVM"].fit(train[features], train["label"]).predict(test[features])
            key = {"window_s": window_s, "features": fs_name, "correction": method, "test": test_name}
            rows.append({**key, **recall_row(test["label"].to_numpy(), pred)})
            m = confusion_matrix(test["label"], pred, labels=LABELS)
            for i, t in enumerate(LABELS):
                for j, q in enumerate(LABELS):
                    conf_rows.append({**key, "true": DISPLAY[t], "pred": DISPLAY[q], "n": int(m[i, j])})
            r = rows[-1]
            print(f"{fs_name:5s} {method:4s} {test_name:11s} flat/step/rough = {r['r_flat']:.2f}/{r['r_step']:.2f}/"
                  f"{r['r_rough']:.2f}", flush=True)

        for (fs_name, features), (test_name, (tr, te)) in itertools.product(FEATURE_SETS.items(), TESTS.items()):
            df = pd.concat([labeled(s, "none") for s in groups[tr] + groups[te]], ignore_index=True)
            pred = cross_val_predict(models()["SVM"], df[features], df["label"], groups=df["group"],
                                     cv=LeaveOneGroupOut(), n_jobs=-1)
            mask = df["group"].isin(groups[te]).to_numpy()
            r = {"window_s": window_s, "features": fs_name, "correction": "oracle", "test": test_name,
                 **recall_row(df["label"].to_numpy()[mask], pred[mask])}
            rows.append(r)
            print(f"{fs_name:5s} 上限 {test_name:11s} flat/step/rough = {r['r_flat']:.2f}/{r['r_step']:.2f}/"
                  f"{r['r_rough']:.2f}", flush=True)

    pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(OUT / "confusion.csv", index=False)
    pd.DataFrame(ref_rows).to_csv(OUT / "reference.csv", index=False)
    pd.DataFrame(pair_rows).to_csv(OUT / "pair_ratio.csv", index=False)


if __name__ == "__main__":
    main()
