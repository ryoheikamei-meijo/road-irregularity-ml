"""体重・車椅子によらない周波数帯の特徴量(10.31 + 11.1)。

考え方: 車椅子 + 人 は「質量 + ばね」の振動系で、固有振動数(汎用 15〜30 Hz、従来 30〜60 Hz)より低い周波数では、
車体は路面の形にほぼそのまま追従する。体重・車椅子で揺れが変わるのは、固有振動数の付近から上。
8 Hz より下には、漕ぐ動きや体の揺れが入る。そこで、上下の揺れを 8〜16 Hz に絞った zb を作り、z の代わりに使う。
帯域の選び方の確認用に、4〜8 Hz(zl)・4〜16 Hz(zw)・8〜32 Hz(zm、汎用の固有振動数を含む)も作る。

特徴量セット:
  core5  : z_rms・z_kurt・tilt_range・g_low_high・g_over_z(これまでの基本)
  core5b : core5 の z_rms・z_kurt を、8〜16 Hz の zb_rms・zb_kurt に置き換えたもの(体重に強い)
  inv5   : zb_rms・zb_kurt・tilt_range・g_low_high・zb_burst_duty。条件で変わりやすい g_over_z(分母が全帯域の z)を、
           条件で変わりにくい zb_burst_duty(8〜16 Hz の包絡線が最大の 25% を超えている時間の割合)に置き換えたもの(車椅子にも強い)
  band_*: core5b の zb を、ほかの帯域に置き換えたもの(帯域の選び方の確認)

1. 帯域ごとの比: 同じ場所の組(51 kg ÷ 69 kg、従来 ÷ 汎用)で、z の振幅の比を帯域ごとに出す
   (ラベル付きで止まっていない 2.0 秒の窓のパワースペクトルの中央値)。クラスごとの振幅(汎用・68〜69 kg)も出す
2. 特徴量ごとの「条件による差」と「クラスの差」: 特徴量を全体の中央値・四分位範囲で標準化し(大きさの特徴量は
   対数をとってから)、同じ場所の組の差と、クラスの中央値の差を同じ単位で比べる
3. 精度: e20261101_correction_eval と同じテスト(same・chair・light2heavy・heavy2light・上限)で、
   core5 と、z を zb に置き換えた特徴量セットを比べる(SVM、窓 1.0・2.0 秒、START を 1 秒ずらす方針A)

出力(data/analysis/20261101_band_features/):
  band_ratio.csv    : 帯域ごとの振幅の比(組ごと)
  band_class.csv    : 帯域ごとの、クラスの振幅(セッションの中央値)
  sensitivity.csv   : 特徴量ごとの、条件による差とクラスの差(標準化した単位)
  results.csv       : テスト・特徴量・窓ごとのクラス別の再現率
  confusion.csv     : 混同行列
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter
from scipy.signal import sosfiltfilt
from scipy.signal import welch
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_correction_eval import MOVING_Z
from src.experiments.e20261101_correction_eval import PAIRS
from src.experiments.e20261101_correction_eval import build
from src.experiments.e20261101_gyro_features import CORE5
from src.experiments.e20261101_gyro_features import add_gyro
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261101_band_features"
WINDOWS_S = [1.0, 2.0]
BANDS = {"zb": (8.0, 16.0), "zl": (4.0, 8.0), "zw": (4.0, 16.0), "zm": (8.0, 32.0)}
RATIO_EDGES = [0.5, 1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32, 64, 128]
CORE5B = ["zb_rms", "zb_kurt", "tilt_range", "g_low_high", "g_over_z"]
INV5 = ["zb_rms", "zb_kurt", "tilt_range", "g_low_high", "zb_burst_duty"]
FEATURE_SETS = {
    "core5": CORE5,
    "core5b": CORE5B,
    "inv5": INV5,
    **{f"band_{a}": [f"{a}_rms", f"{a}_kurt", "tilt_range", "g_low_high", "g_over_z"] for a in ["zl", "zw", "zm"]},
}
SENS_FEATURES = ["z_rms", "zb_rms", "zl_rms", "zm_rms", "z_kurt", "zb_kurt", "zb_burst_duty", "tilt_range",
                 "g_low_high", "g_over_z", "g_over_zb", "h_rms", "g_rms"]
LOG_FEATURES = {"z_rms", "zb_rms", "tilt_range", "h_rms", "g_rms"}  # 倍率で変わる量は対数で比べる
TESTS = {"chair": ("68-69kg", "original"), "light2heavy": ("51kg", "68-69kg"), "heavy2light": ("68-69kg", "51kg")}


def add_band(sess: dict, bands: dict | None = None) -> None:
    """上下の揺れを帯域に絞った軸(既定は BANDS)を足す(ゼロ位相のバターワース 4 次)。"""
    for name, band in (bands or BANDS).items():
        sos = butter(4, band, btype="bandpass", fs=sess["fs"], output="sos")
        sess["axes"][name] = sosfiltfilt(sos, sess["axes"]["z"])


def session_psd(sess: dict, table: pd.DataFrame, window_s: float) -> tuple[np.ndarray, np.ndarray]:
    """ラベル付きで止まっていない窓の、z のパワースペクトルの中央値。"""
    ts, fs, z = sess["ts"], sess["fs"], sess["axes"]["z"]
    t = table[table["label"].notna() & (table["z_rms"] >= MOVING_Z)]
    n = int(round(window_s * fs * 0.95))
    psd = []
    for start in t["start_ms"]:
        lo = np.searchsorted(ts, start)
        seg = z[lo:lo + n]
        if len(seg) == n:
            f, p = welch(seg - seg.mean(), fs=fs, nperseg=n)
            psd.append(p)
    return f, np.median(np.array(psd), axis=0)


def band_amp(f: np.ndarray, p: np.ndarray) -> dict:
    return {f"{lo:g}-{hi:g}": float(np.sqrt(p[(f >= lo) & (f < hi)].sum()))
            for lo, hi in zip(RATIO_EDGES[:-1], RATIO_EDGES[1:])}


def recall_row(y: np.ndarray, pred: np.ndarray) -> dict:
    return {f"r_{DISPLAY[k]}": float((pred[y == k] == k).mean()) if (y == k).any() else np.nan for k in LABELS}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = pd.concat([load_meta(["10.31", "11.1"], "standard", [68, 69, 51]),
                      load_meta(["10.31"], "original", [68])], ignore_index=True)
    meta["cond"] = np.where(meta["wheelchair"] == "original", "original",
                            np.where(meta["weight_kg"] == 51, "51kg", "68-69kg"))
    groups = {c: list(meta.loc[meta["cond"] == c, "session_id"]) for c in meta["cond"].unique()}
    cond_of = dict(zip(meta["session_id"], meta["cond"]))
    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s  # 読むだけ
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        add_band(sess)
        for a in ("x", "y", "m"):  # 使わない軸(計算を軽くする)
            sess["axes"].pop(a)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    kind_of = dict(zip(meta["session_id"], meta["kind"]))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    rows, conf_rows = [], []
    for window_s in WINDOWS_S:
        tables = build(sessions, passes, kind_of, window_s)
        for t in tables.values():
            t["g_over_zb"] = np.log10(t["g_rms"] / t["zb_rms"])

        if window_s == 2.0:
            # 1. 帯域ごとの比と、クラスごとの振幅
            amp = {s: band_amp(*session_psd(sessions[s], tables[s], window_s)) for s in tables}
            ratio_rows = [{"which": w, "place": name, **{b: amp[a][b] / amp[r][b] for b in amp[a]}}
                          for w, pairs in PAIRS.items() for name, a, r in pairs]
            band_ratio = pd.DataFrame(ratio_rows)
            band_ratio.to_csv(OUT / "band_ratio.csv", index=False)
            print("帯域ごとの振幅の比(比べる側 ÷ 基準の側):")
            print(band_ratio.round(2).to_string(index=False))
            cls = pd.DataFrame([{"kind": kind_of[s], **amp[s]} for s in tables if cond_of[s] == "68-69kg"])
            band_class = cls.groupby("kind").median()
            band_class.to_csv(OUT / "band_class.csv")
            print("\nクラスごとの振幅(汎用・68〜69 kg、セッションの中央値):")
            print(band_class.round(3))

            # 2. 特徴量ごとの、条件による差とクラスの差
            lab = pd.concat([t.dropna(subset=["label"]) for t in tables.values()], ignore_index=True)
            std = lab[SENS_FEATURES].copy()
            for f in LOG_FEATURES:
                std[f] = np.log(std[f])
            center, scale = std.median(), std.quantile(0.75) - std.quantile(0.25)
            std = (std - center) / scale
            std["group"], std["label"] = lab["group"].to_numpy(), lab["label"].to_numpy()
            sess_med = std.groupby("group")[SENS_FEATURES].median()
            sens = {}
            for w, pairs in PAIRS.items():
                d = np.array([(sess_med.loc[a] - sess_med.loc[r]).abs().to_numpy() for _, a, r in pairs])
                sens[f"差_{w}"] = np.median(d, axis=0)
            heavy = std[std["group"].map(cond_of) == "68-69kg"].groupby("label")[SENS_FEATURES].median()
            sens["クラス差_flat-rough"] = (heavy.loc["dekobo"] - heavy.loc["flat"]).abs().to_numpy()
            sens["クラス差_flat-step"] = (heavy.loc["dansa"] - heavy.loc["flat"]).abs().to_numpy()
            sens["クラス差_step-rough"] = (heavy.loc["dansa"] - heavy.loc["dekobo"]).abs().to_numpy()
            sensitivity = pd.DataFrame(sens, index=SENS_FEATURES)
            sensitivity.to_csv(OUT / "sensitivity.csv")
            print("\n特徴量ごとの、条件による差とクラスの差(標準化した単位。組の差は中央値):")
            print(sensitivity.round(2))

        # 3. 精度
        for (fs_name, features), test_name in itertools.product(FEATURE_SETS.items(), ["same", *TESTS]):
            if test_name == "same":
                df = pd.concat([tables[s].dropna(subset=["label"]) for s in groups["68-69kg"]], ignore_index=True)
                pred = cross_val_predict(models()["SVM"], df[features], df["label"], groups=df["group"],
                                         cv=LeaveOneGroupOut(), n_jobs=-1)
                y = df["label"].to_numpy()
            else:
                tr, te = TESTS[test_name]
                train = pd.concat([tables[s].dropna(subset=["label"]) for s in groups[tr]], ignore_index=True)
                test = pd.concat([tables[s].dropna(subset=["label"]) for s in groups[te]], ignore_index=True)
                pred = models()["SVM"].fit(train[features], train["label"]).predict(test[features])
                y = test["label"].to_numpy()
            key = {"window_s": window_s, "features": fs_name, "test": test_name}
            rows.append({**key, **recall_row(y, pred)})
            m = confusion_matrix(y, pred, labels=LABELS)
            for i, t in enumerate(LABELS):
                for j, q in enumerate(LABELS):
                    conf_rows.append({**key, "true": DISPLAY[t], "pred": DISPLAY[q], "n": int(m[i, j])})
        for (fs_name, features), (test_name, (tr, te)) in itertools.product(FEATURE_SETS.items(), TESTS.items()):
            df = pd.concat([tables[s].dropna(subset=["label"]) for s in groups[tr] + groups[te]], ignore_index=True)
            pred = cross_val_predict(models()["SVM"], df[features], df["label"], groups=df["group"],
                                     cv=LeaveOneGroupOut(), n_jobs=-1)
            mask = df["group"].isin(groups[te]).to_numpy()
            rows.append({"window_s": window_s, "features": fs_name, "test": f"{test_name}_oracle",
                         **recall_row(df["label"].to_numpy()[mask], pred[mask])})
        res = pd.DataFrame([r for r in rows if r["window_s"] == window_s])
        res["v"] = res.apply(lambda r: f"{r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f}", axis=1)
        print(f"\n== 窓 {window_s:.1f} 秒(flat/step/rough)")
        print(res.pivot(index="features", columns="test", values="v")
              .loc[list(FEATURE_SETS), ["same", "chair", "chair_oracle", "light2heavy", "light2heavy_oracle",
                                        "heavy2light"]])

    pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(OUT / "confusion.csv", index=False)


if __name__ == "__main__":
    main()
