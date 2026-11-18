"""体重によらない周波数帯の特徴量を、ゼミの core(暫定)で確かめ直す。

考え方(基礎の振動理論): 地面が揺れる 1 自由度の系(ばね・ダンパーの上の質量)では、車体の揺れ ÷ 地面の揺れは
√[(1 + (2ζr)²) / ((1 − r²)² + (2ζr)²)](r = 揺れの周波数 ÷ 固有振動数)。質量(体重)は固有振動数と減衰比を通してしか
入らず、r が小さい(固有振動数より十分低い)帯域では 1 に近づく。そこで、上下の揺れを固有振動数より低い帯域に絞って特徴量にする。

1. 帯域ごとの比: 同じ場所を 51 kg と 69 kg の人が続けて走った 6 組で、上下(z)と水平(x・y)の振幅の比を帯域ごとに出す
2. 固有振動数: 学習に使う人(68〜69 kg)の flat のセッションだけから、z のパワースペクトルの山の周波数を出す
   (テストに使う 51 kg の人のデータは見ない)
3. 精度: core の z_rms・z_kurt を帯域版にしたもので、same(68〜69 kg の 16 セッションの LOGO)、light2heavy(51 → 68〜69 kg)、
   heavy2light(68〜69 → 51 kg)と、それぞれの上限(学習とテストを合わせた LOGO で、テスト側だけを集計)を比べる。
   帯域の下限は 4 Hz・8 Hz、上限は 8〜64 Hz で変える(上限が固有振動数に近づくと、体重のテストで落ちるかを見る)
4. 特徴量ごとの、体重による差とクラスの差(標準化した単位。e20261101_band_features と同じ方法)

条件: 汎用の車椅子、10.31・11.1、方針A、START を 1 秒ずらす、SVM、窓 2.0・1.0 秒。

出力(data/analysis/20261108_band_core_eval/):
  band_ratio.csv、natural_freq.csv、results.csv、sensitivity.csv
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from scipy.signal import butter
from scipy.signal import sosfiltfilt
from scipy.signal import welch
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261101_band_features import RATIO_EDGES
from src.experiments.e20261101_band_features import recall_row
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_correction_eval import MOVING_Z
from src.experiments.e20261101_correction_eval import PAIRS
from src.experiments.e20261101_correction_eval import build
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261105_rough_error_analysis import ROOT
from src.roadml.evaluation import models

OUT = ROOT / "data/analysis/20261108_band_core_eval"
WINDOWS_S = [2.0, 1.0]
CORE = ["z_rms", "z_kurt", "h_std", "h_crest", "tilt_range"]  # ゼミ資料 131-017 の core(暫定)
# 上下の揺れ z を絞る帯域(下限, 上限)。8〜16 Hz は 11.1 の core5b と同じ
Z_BANDS = {f"z{lo}_{hi}": (lo, hi) for lo, hi in
           [(4, 8), (4, 12), (4, 16), (4, 20), (4, 24), (4, 32), (4, 64), (8, 12), (8, 16), (8, 20), (8, 24), (8, 32)]}
H_BAND = (8, 16)  # 水平の揺れを絞る帯域(1 章の比を見てから使うか決める。探索的)
TESTS = {"light2heavy": ("51kg", "68-69kg"), "heavy2light": ("68-69kg", "51kg")}


def bandpass(x: np.ndarray, band: tuple[float, float], fs: float) -> np.ndarray:
    sos = butter(4, band, btype="bandpass", fs=fs, output="sos")
    return sosfiltfilt(sos, x)


def add_bands(sess: dict) -> None:
    fs, ax = sess["fs"], sess["axes"]
    for name, band in Z_BANDS.items():
        ax[name] = bandpass(ax["z"], band, fs)
    ax["hb"] = np.hypot(bandpass(ax["x"], H_BAND, fs), bandpass(ax["y"], H_BAND, fs))


def moving_psd(sess: dict, table: pd.DataFrame, window_s: float, axis: str) -> tuple[np.ndarray, np.ndarray]:
    """ラベル付きで止まっていない窓の、ある軸のパワースペクトルの中央値。"""
    ts, fs, v = sess["ts"], sess["fs"], sess["raw"][axis]
    t = table[table["label"].notna() & (table["z_rms"] >= MOVING_Z)]
    n = int(round(window_s * fs * 0.95))
    psd = []
    for start in t["start_ms"]:
        lo = np.searchsorted(ts, start)
        seg = v[lo:lo + n]
        if len(seg) == n:
            f, p = welch(seg - seg.mean(), fs=fs, nperseg=n)
            psd.append(p)
    return f, np.median(np.array(psd), axis=0)


def band_amp(f: np.ndarray, p: np.ndarray) -> dict:
    return {f"{lo:g}-{hi:g}": float(np.sqrt(p[(f >= lo) & (f < hi)].sum()))
            for lo, hi in zip(RATIO_EDGES[:-1], RATIO_EDGES[1:])}


def band_sets() -> dict:
    sets = {"core": CORE}
    for name in Z_BANDS:
        sets[f"core_{name}"] = [f"{name}_rms", f"{name}_kurt", "h_std", "h_crest", "tilt_range"]
    sets["core_z8_16_hb"] = ["z8_16_rms", "z8_16_kurt", "hb_std", "hb_crest", "tilt_range"]
    return sets


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    meta = load_meta(["10.31", "11.1"], "standard", [68, 69, 51])
    meta["cond"] = np.where(meta["weight_kg"] == 51, "51kg", "68-69kg")
    groups = {c: list(meta.loc[meta["cond"] == c, "session_id"]) for c in ("68-69kg", "51kg")}
    print({c: len(v) for c, v in groups.items()})
    kind_of = dict(zip(meta["session_id"], meta["kind"]))

    sessions, passes = {}, {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s  # 読むだけ
        sess = load_session(run_dir)
        ax = sess["axes"]
        ax["h"] = np.hypot(ax["x"], ax["y"])
        add_gyro(sess, run_dir)
        add_bands(sess)
        sess["raw"] = {"z": ax["z"], "x": ax["x"], "y": ax["y"]}
        for a in ("x", "y", "m"):  # 窓の特徴量に使わない軸
            ax.pop(a, None)
        sessions[s] = sess
        if k != "flat":
            passes[s] = load_passes(run_dir)
    feature_sets = band_sets()

    rows = []
    for window_s in WINDOWS_S:
        tables = build(sessions, passes, kind_of, window_s)

        if window_s == 2.0:
            # 1. 帯域ごとの比(51 kg ÷ 69 kg、同じ場所の 6 組)。水平は x・y のパワーの和
            amp = {}
            for s in tables:
                f, pz = moving_psd(sessions[s], tables[s], window_s, "z")
                _, px = moving_psd(sessions[s], tables[s], window_s, "x")
                _, py = moving_psd(sessions[s], tables[s], window_s, "y")
                amp[s] = {"z": band_amp(f, pz), "h": band_amp(f, px + py)}
            ratio_rows = [{"axis": a, "place": name, **{b: amp[x][a][b] / amp[r][a][b] for b in amp[x][a]}}
                          for a in ("z", "h") for name, x, r in PAIRS["weight"]]
            band_ratio = pd.DataFrame(ratio_rows)
            band_ratio.to_csv(OUT / "band_ratio.csv", index=False)
            print("帯域ごとの振幅の比(51 kg ÷ 69 kg):")
            print(band_ratio.round(2).to_string(index=False))

            # 2. 固有振動数(学習に使う 68〜69 kg の flat だけ)
            nf_rows = []
            for s in groups["68-69kg"]:
                if kind_of[s] != "flat":
                    continue
                f, pz = moving_psd(sessions[s], tables[s], window_s, "z")
                m = (f >= 10) & (f <= 60)
                nf_rows.append({"session": s, "peak_hz": float(f[m][np.argmax(pz[m])])})
            f_all = np.mean([moving_psd(sessions[s], tables[s], window_s, "z")[1]
                             for s in groups["68-69kg"] if kind_of[s] == "flat"], axis=0)
            m = (f >= 10) & (f <= 60)
            nf_rows.append({"session": "flat の平均", "peak_hz": float(f[m][np.argmax(f_all[m])])})
            nf = pd.DataFrame(nf_rows)
            nf.to_csv(OUT / "natural_freq.csv", index=False)
            print("\n固有振動数(68〜69 kg の flat の z の山、10〜60 Hz):")
            print(nf.round(1).to_string(index=False))

            # 4. 体重による差とクラスの差(標準化した単位)
            sens_feats = ["z_rms", "z8_16_rms", "z4_16_rms", "z_kurt", "z8_16_kurt", "z4_16_kurt",
                          "h_std", "hb_std", "h_crest", "hb_crest", "tilt_range"]
            log_feats = {"z_rms", "z8_16_rms", "z4_16_rms", "h_std", "hb_std", "tilt_range"}
            lab = pd.concat([t.dropna(subset=["label"]) for t in tables.values()], ignore_index=True)
            std = lab[sens_feats].copy()
            for c in log_feats:
                std[c] = np.log(std[c])
            std = (std - std.median()) / (std.quantile(0.75) - std.quantile(0.25))
            std["group"], std["label"] = lab["group"].to_numpy(), lab["label"].to_numpy()
            med = std.groupby("group")[sens_feats].median()
            diff = np.array([(med.loc[x] - med.loc[r]).abs().to_numpy() for _, x, r in PAIRS["weight"]])
            heavy = std[std["group"].isin(groups["68-69kg"])].groupby("label")[sens_feats].median()
            sens = pd.DataFrame({
                "weight_diff": np.median(diff, axis=0),
                "flat_rough": (heavy.loc["dekobo"] - heavy.loc["flat"]).abs().to_numpy(),
                "flat_step": (heavy.loc["dansa"] - heavy.loc["flat"]).abs().to_numpy(),
                "step_rough": (heavy.loc["dansa"] - heavy.loc["dekobo"]).abs().to_numpy(),
            }, index=sens_feats)
            sens.to_csv(OUT / "sensitivity.csv")
            print("\n体重による差とクラスの差(標準化した単位):")
            print(sens.round(2))

        # 3. 精度
        for (fs_name, feats), test in itertools.product(feature_sets.items(), ["same", *TESTS]):
            if test == "same":
                df = pd.concat([tables[s].dropna(subset=["label"]) for s in groups["68-69kg"]], ignore_index=True)
                pred = cross_val_predict(models()["SVM"], df[feats], df["label"], groups=df["group"],
                                         cv=LeaveOneGroupOut(), n_jobs=-1)
                y = df["label"].to_numpy()
            else:
                tr, te = TESTS[test]
                train = pd.concat([tables[s].dropna(subset=["label"]) for s in groups[tr]], ignore_index=True)
                testdf = pd.concat([tables[s].dropna(subset=["label"]) for s in groups[te]], ignore_index=True)
                pred = models()["SVM"].fit(train[feats], train["label"]).predict(testdf[feats])
                y = testdf["label"].to_numpy()
            rows.append({"window_s": window_s, "features": fs_name, "test": test, **recall_row(y, pred)})
        for (fs_name, feats), (test, (tr, te)) in itertools.product(feature_sets.items(), TESTS.items()):
            df = pd.concat([tables[s].dropna(subset=["label"]) for s in groups[tr] + groups[te]], ignore_index=True)
            pred = cross_val_predict(models()["SVM"], df[feats], df["label"], groups=df["group"],
                                     cv=LeaveOneGroupOut(), n_jobs=-1)
            mask = df["group"].isin(groups[te]).to_numpy()
            rows.append({"window_s": window_s, "features": fs_name, "test": f"{test}_oracle",
                         **recall_row(df["label"].to_numpy()[mask], pred[mask])})
        res = pd.DataFrame([r for r in rows if r["window_s"] == window_s])
        res["v"] = res.apply(lambda r: f"{r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f}", axis=1)
        print(f"\n== 窓 {window_s:.1f} 秒(flat/step/rough)")
        print(res.pivot(index="features", columns="test", values="v")
              .loc[list(feature_sets), ["same", "light2heavy", "light2heavy_oracle", "heavy2light", "heavy2light_oracle"]])

    pd.DataFrame(rows).to_csv(OUT / "results.csv", index=False)


if __name__ == "__main__":
    main()
