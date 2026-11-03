"""補正(体重・車椅子の違い)が効くかを、補正なしで精度が落ちる条件で調べる(10.31 + 11.1)。

テスト(どれも SVM、窓 1.0・2.0 秒、START を 1 秒ずらす方針A):
  same      : 汎用・68〜69 kg の 18 セッションの、セッション単位の LOGO(補正で悪くならないかの確認)
  chair     : 汎用・68〜69 kg で学習 → 従来の車椅子(10.31、68 kg、step 3・rough 2。flat は無い)でテスト
  light2heavy: 51 kg(6 セッション)で学習 → 汎用・68〜69 kg(18 セッション)でテスト
  heavy2light: 汎用・68〜69 kg で学習 → 51 kg でテスト(e20261101_weight_transfer と同じ)
  上限(oracle): 学習とテストのセッションを合わせたセッション単位の LOGO で、テスト側のセッションだけを集計

補正:
  none : 補正なし
  A    : 直前の静かな走行との比。各窓の揺れの大きさの特徴量(z・h の基本4)を、その窓までの直前 60 秒の窓のうち、
         小さいほうから 20 パーセンタイルの値で割る。走り始めの 30 秒は、最初の 30 秒の窓を基準にする
  Am   : A と同じだが、基準に使う窓を、止まっていない窓(z_rms >= MOVING_Z)に限る。段差のセッションには、
         通過の合間に止まっている時間があり(z_rms < 1 m/s² が約 3 割)、A の基準が「止まっているとき」になってしまうため
  A2   : A に加えて、傾きの大きさ(tilt_range・tilt_std)と傾きの速さ(g の基本4)も同じように割る
  D    : 振幅を変えた水増し。学習のセッションごとに、揺れ・傾きの大きさの特徴量を 0.7・0.85・1.2・1.45 倍した
         コピーを足す(セッション全体の揺れが一様に大きく・小さくなった場合をまねる。尖度・クレスト・比は変わらない)
  A+D、Am+D、A2+D : 水増ししてから A・Am・A2 の比をとる

水増しは、計算した特徴量にメモリ上で倍率をかけるだけで、生データ(wheelchair_data/、read-only)には何も書かない。

出力(data/analysis/20261101_correction_eval/):
  results.csv      : テスト・補正・特徴量・窓ごとのクラス別の再現率
  pair_ratio.csv   : 同じ場所の組の、z_rms(補正なし・A)の中央値と比
  baseline.csv     : セッションごとの基準(A の分母)の中央値
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import intervals
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import CORE5
from src.experiments.e20261101_gyro_features import HZ12
from src.experiments.e20261101_gyro_features import SHIFT_S
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_gyro_features import gyro_window_features
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import cols

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_correction_eval"
WINDOWS_S = [1.0, 2.0]
FEATURE_SETS = {"core5": CORE5, "hz12": HZ12}
HISTORY_S, WARMUP_S, BASE_PCT = 60.0, 30.0, 20.0
MOVING_Z = 1.0  # これ未満の z_rms の窓は、止まっているとみなして基準に使わない(Am)
SCALES = [0.7, 0.85, 1.2, 1.45]
ACC_AMP = cols("zh", BASIC)  # 揺れの大きさの特徴量(A で割る)
GYRO_AMP = cols("g", BASIC) + ["tilt_range", "tilt_std"]  # 傾きの大きさの特徴量(A2 で割る)
CORRECTIONS = ["none", "A", "Am", "A2", "D", "A+D", "Am+D", "A2+D"]
# 続けて測った同じ場所の組(比べる側, 基準の側)
PAIRS = {
    "weight": [("段差 ①", "20261101140355", "20261101140700"), ("段差 ②", "20261101142036", "20261101142339"),
               ("凸凹 ①", "20261101141512", "20261101141730"), ("凸凹 ②", "20261101142926", "20261101143126"),
               ("flat ①", "20261101141139", "20261101141253"), ("flat ②", "20261101142633", "20261101143455")],
    "chair": [("段差 (10.31) ①", "20261031142344", "20261031142102"), ("凸凹 (10.31) ①", "20261031142814", "20261031143004"),
              ("段差 (10.31) ②", "20261031144130", "20261031144423"), ("凸凹 (10.31) ②", "20261031145240", "20261031145017")],
}


def local_ratio(win: pd.DataFrame, features: list[str], moving_only: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """各窓の特徴量を、直前 HISTORY_S 秒の窓の BASE_PCT パーセンタイルで割る(走り始めは最初の WARMUP_S 秒を基準)。

    moving_only なら、基準に使う窓を z_rms >= MOVING_Z の窓に限る(該当が無ければ全部の窓)。
    """
    t = win["start_ms"].to_numpy()
    vals = win[features].to_numpy(float)
    use = (win["z_rms"].to_numpy() >= MOVING_Z) if moving_only else np.ones(len(t), bool)
    t0 = t[0]
    warm_m = (t <= t0 + WARMUP_S * 1000.0) & use
    warm_base = np.percentile(vals[warm_m if warm_m.any() else use], BASE_PCT, axis=0)
    base = np.empty_like(vals)
    for i, ti in enumerate(t):
        if ti - t0 < WARMUP_S * 1000.0:
            base[i] = warm_base
        else:
            m = (t >= ti - HISTORY_S * 1000.0) & (t <= ti)
            base[i] = np.percentile(vals[m & use], BASE_PCT, axis=0) if (m & use).any() else base[i - 1]
    out = win.copy()
    out[features] = vals / np.maximum(base, 1e-9)
    return out, pd.DataFrame(base, columns=features)


def build(sessions: dict, passes: dict, kind_of: dict, window_s: float) -> dict:
    """セッションごとの、ラベル付きの窓の表(補正なしの特徴量、全部の窓)。"""
    tables = {}
    for s, sess in sessions.items():
        win = window_features(sess, window_s)
        win = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
        iv, dr = intervals(passes[s], SHIFT_S) if s in passes else ({}, [])
        tables[s] = win.assign(label=label_windows(win, window_s, kind_of[s], iv, dr), group=s)
    return tables


def corrected(table: pd.DataFrame, method: str) -> pd.DataFrame:
    """補正した特徴量の、ラベル付きの窓だけ(基準は、ラベルの無い窓も含む全部の窓から作る)。"""
    if method.startswith("A2"):
        table, _ = local_ratio(table, ACC_AMP + GYRO_AMP)
    elif method.startswith("Am"):
        table, _ = local_ratio(table, ACC_AMP, moving_only=True)
    elif method.startswith("A"):
        table, _ = local_ratio(table, ACC_AMP)
    return table.dropna(subset=["label"])


def augmented(table: pd.DataFrame, method: str) -> pd.DataFrame:
    """学習用。D を含む補正なら、揺れ・傾きの大きさを SCALES 倍したコピーを足す(メモリ上だけ)。"""
    frames = [corrected(table, method)]
    if method.endswith("D"):
        base_method = method.removesuffix("+D").removesuffix("D") or "none"
        for k in SCALES:
            scaled = table.copy()
            scaled[ACC_AMP + GYRO_AMP] = scaled[ACC_AMP + GYRO_AMP] * k
            scaled["g_over_z"] = table["g_over_z"]  # 両方が同じ倍率なので比は変わらない
            frames.append(corrected(scaled, base_method).assign(group=f"{table['group'].iloc[0]}_x{k}"))
    return pd.concat(frames, ignore_index=True)


def recall_row(y: np.ndarray, pred: np.ndarray) -> dict:
    return {f"r_{DISPLAY[k]}": float((pred[y == k] == k).mean()) if (y == k).any() else np.nan for k in LABELS}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = pd.concat([load_meta(["10.31", "11.1"], "standard", [68, 69, 51]),
                      load_meta(["10.31"], "original", [68])], ignore_index=True)
    meta["cond"] = np.where(meta["wheelchair"] == "original", "original",
                            np.where(meta["weight_kg"] == 51, "51kg", "68-69kg"))
    print("使うセッション:", meta.groupby(["cond", "kind"]).size().to_dict())
    groups = {c: list(meta.loc[meta["cond"] == c, "session_id"]) for c in meta["cond"].unique()}
    tests = {"chair": ("68-69kg", "original"), "light2heavy": ("51kg", "68-69kg"),
             "heavy2light": ("68-69kg", "51kg")}

    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s  # 読むだけ
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    kind_of = dict(zip(meta["session_id"], meta["kind"]))

    rows, pair_rows, base_rows = [], [], []
    for window_s in WINDOWS_S:
        tables = build(sessions, passes, kind_of, window_s)
        # 基準の大きさと、同じ場所の組の比(2.0 秒・1.0 秒とも)
        for s, tab in tables.items():
            _, base = local_ratio(tab, ACC_AMP + GYRO_AMP)
            _, base_m = local_ratio(tab, ACC_AMP, moving_only=True)
            base_rows.append({"window_s": window_s, "session": s, "kind": kind_of[s],
                              **base.median().add_prefix("base_").to_dict(),
                              **base_m.median().add_prefix("base_moving_").to_dict()})
        for which, pairs in PAIRS.items():
            for name, a, b in pairs:
                row = {"window_s": window_s, "which": which, "place": name, "session": a, "ref": b}
                for method in ["none", "A", "Am", "A2"]:
                    for f in ["z_rms", "tilt_range"]:
                        va = corrected(tables[a], method)[f].median()
                        vb = corrected(tables[b], method)[f].median()
                        row.update({f"{f}_{method}": va, f"{f}_{method}_ref": vb, f"{f}_{method}_ratio": va / vb})
                pair_rows.append(row)

        for (fs_name, features), method in itertools.product(FEATURE_SETS.items(), CORRECTIONS):
            key = {"window_s": window_s, "features": fs_name, "correction": method}
            # same: 68〜69 kg の LOGO(学習側だけ水増し)
            same = groups["68-69kg"]
            preds, ys = [], []
            for test_s in same:
                train = pd.concat([augmented(tables[s], method) for s in same if s != test_s], ignore_index=True)
                test = corrected(tables[test_s], method)
                preds.append(models()["SVM"].fit(train[features], train["label"]).predict(test[features]))
                ys.append(test["label"].to_numpy())
            rows.append({**key, "test": "same", **recall_row(np.concatenate(ys), np.concatenate(preds))})
            for test_name, (tr, te) in tests.items():
                train = pd.concat([augmented(tables[s], method) for s in groups[tr]], ignore_index=True)
                test = pd.concat([corrected(tables[s], method) for s in groups[te]], ignore_index=True)
                pred = models()["SVM"].fit(train[features], train["label"]).predict(test[features])
                rows.append({**key, "test": test_name, **recall_row(test["label"].to_numpy(), pred)})
            print(f"{window_s:.1f}s {fs_name:5s} {method:5s} " + "  ".join(
                f"{r['test']}={r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f}" for r in rows[-4:]), flush=True)

        # 上限: 学習とテストを合わせた LOGO で、テスト側だけを集計(補正なし)
        for (fs_name, features), (test_name, (tr, te)) in itertools.product(FEATURE_SETS.items(), tests.items()):
            df = pd.concat([corrected(tables[s], "none") for s in groups[tr] + groups[te]], ignore_index=True)
            pred = cross_val_predict(models()["SVM"], df[features], df["label"], groups=df["group"],
                                     cv=LeaveOneGroupOut(), n_jobs=-1)
            m = df["group"].isin(groups[te]).to_numpy()
            r = {"window_s": window_s, "features": fs_name, "correction": "oracle", "test": test_name,
                 **recall_row(df["label"].to_numpy()[m], pred[m])}
            rows.append(r)
            print(f"{window_s:.1f}s {fs_name:5s} oracle {test_name}={r['r_flat']:.2f}/{r['r_step']:.2f}/"
                  f"{r['r_rough']:.2f}", flush=True)

    pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False)
    pd.DataFrame(pair_rows).to_csv(OUT / "pair_ratio.csv", index=False)
    pd.DataFrame(base_rows).to_csv(OUT / "baseline.csv", index=False)


if __name__ == "__main__":
    main()
