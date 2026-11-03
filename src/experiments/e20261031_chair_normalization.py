"""平坦路を基準にした補正で、車椅子 2 台の違いを消せるかを調べる(10.31)。

汎用(standard)の車椅子で学習し、従来(original)の車椅子でテストする。従来には flat のセッションが無いので、
テストで見るのは step と rough の再現率。補正が汎用の中の評価(LOGO)を悪くしないかも見る。

キャリブレーション(平坦路の基準)はセッションごとに取る。
  段差・凸凹のセッション: 最初の CALIB_PASSES 回の通過の、START から 0.2〜0.9 秒(段差・凸凹に着く前の走行。
                          START から揺れ始めまで約 1 秒。e20261031_button_lag)
  flat のセッション      : 最初の 2〜17 秒(この部分の窓は評価に使わない)

補正の方法:
  none     : 補正なし(xyz18・m6)
  scale    : 軸ごとに、キャリブレーションの rms で信号を割ってから特徴量を作る(以前検討していた案の (b))
  lpc      : 軸ごとに、キャリブレーションに AR モデル(線形予測)を当てはめ、その逆フィルタをかけた残差から
             特徴量を作る(SmartRoadSense と同じ考え方)。キャリブレーションの rms でも割る
  lpc_shape: lpc から、キャリブレーションの rms で割る部分を外したもの(揺れの「形」だけを補正し、大きさは補正しない)
  spectrum : 窓のパワースペクトルを、キャリブレーションのパワースペクトルで割り、帯域ごとの平均(dB)を特徴量にする
             (z と合成 m の 2 軸 × 6 帯域 = 12 個)。尖度・クレスト(振幅によらない)を足した版も見る
  spectrum_shape: 窓の帯域ごとのパワー(dB)から、キャリブレーションの「形」(帯域ごとのパワー ÷ 全体の和、dB)を引く。
             窓自体の大きさは残る(docs/knowledge/2026-11-01 の、形だけの補正)

--calib chair では、キャリブレーションをセッションごとではなく車椅子ごとに 1 つにする
(セッションごとの「着く前の走行」は、凸凹の近くの路面が粗く、基準がそろわないため)。
  汎用: 10.31 の静かな flat(20261031152608)の 10〜25 秒(この部分の窓は評価に使わない)
  従来: 10.4 の flat(20261004172306。従来の車椅子・後ろ固定)の 10〜25 秒

ラベルは e20261031_button_lag と同じ(方針A、始まりを 1 秒ずらす shift_1、2.0 秒窓)。
`20261031150809` は使わない(測定者の判断)。

出力(data/analysis/20261031_chair_normalization/): results_<--calib>.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.linalg import solve_toeplitz
from scipy.signal import lfilter
from scipy.signal import welch
from sklearn.base import clone
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import intervals_for
from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.features import cols

ROOT = Path(__file__).resolve().parents[2]
EXCLUDE = ["20261031150809"]
WINDOW_S = 2.0
CONDITION = "shift_1"
CALIB_PASSES = 10
CALIB_FROM_S, CALIB_TO_S = 0.2, 0.9  # 通過の START からの区間
FLAT_CALIB_S = (2.0, 17.0)  # flat のセッションの、キャリブレーションに使う区間(計測開始から)
LPC_ORDER = 16
NPERSEG = 256
BANDS_HZ = [(0.5, 3), (3, 8), (8, 15), (15, 30), (30, 60), (60, 160)]
SPEC_AXES = ["z", "m"]
# --calib chair の基準(セッションのフォルダ, 開始[s], 終了[s])
CHAIR_CALIB = {
    "standard": ("wheelchair_data/10.31/20261031152608", 10.0, 25.0),
    "original": ("wheelchair_data/10.4/20261004172306", 10.0, 25.0),
}
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}


def calibration_mask(sess: dict, passes: pd.DataFrame, kind: str) -> np.ndarray:
    ts = sess["ts"]
    t = (ts - ts[0]) / 1000.0
    if kind == "flat":
        return (t >= FLAT_CALIB_S[0]) & (t < FLAT_CALIB_S[1])
    mask = np.zeros(len(ts), bool)
    ok = passes[~passes["cancelled"]].sort_values("start_ms").head(CALIB_PASSES)
    for start in ok["start_ms"]:
        mask |= (ts >= start + CALIB_FROM_S * 1000) & (ts < start + CALIB_TO_S * 1000)
    return mask


def segments(mask: np.ndarray) -> list[slice]:
    """True が続く区間のリスト。"""
    edges = np.flatnonzero(np.diff(np.r_[0, mask.astype(int), 0]))
    return [slice(a, b) for a, b in zip(edges[::2], edges[1::2])]


def ar_coefficients(segs: list[np.ndarray], order: int) -> np.ndarray:
    """Yule-Walker で AR モデルを当てはめ、逆フィルタ [1, -a1, ..., -ap] を返す。"""
    r = np.zeros(order + 1)
    n = 0
    for x in segs:
        x = x - x.mean()
        full = np.correlate(x, x, mode="full")[len(x) - 1:len(x) + order]
        r[: len(full)] += full
        n += len(x)
    a = solve_toeplitz(r[:order], r[1:order + 1])
    return np.r_[1.0, -a]


def calibration_psd(segs: list[np.ndarray], fs: float) -> tuple[np.ndarray, np.ndarray]:
    psds, weights = [], []
    for x in segs:
        f, p = welch(x, fs=fs, nperseg=min(NPERSEG, len(x)), nfft=NPERSEG)
        psds.append(p)
        weights.append(len(x))
    return f, np.average(psds, axis=0, weights=weights)


def calib_segments(sess: dict, mask: np.ndarray) -> dict[str, list[np.ndarray]]:
    """軸ごとの、キャリブレーションの区間の信号。"""
    return {key: [x[s] for s in segments(mask)] for key, x in sess["axes"].items()}


def transformed_session(sess: dict, calib: dict, method: str) -> dict:
    """scale / lpc の補正をかけた軸に置き換えたセッション。"""
    axes = {}
    for key, x in sess["axes"].items():
        segs = calib[key]
        rms = float(np.sqrt(np.mean(np.concatenate(segs) ** 2)))
        if method == "scale":
            axes[key] = x / rms
        elif method == "lpc_shape":  # 形だけ。大きさは割らない
            a = ar_coefficients(segs, LPC_ORDER)
            axes[key] = lfilter(a, [1.0], x - np.concatenate(segs).mean())
        else:  # lpc
            a = ar_coefficients(segs, LPC_ORDER)
            mean = np.concatenate(segs).mean()
            resid = lfilter(a, [1.0], x - mean)
            resid_calib = np.concatenate([lfilter(a, [1.0], seg - mean) for seg in segs])
            axes[key] = resid / float(np.sqrt(np.mean(resid_calib**2)))
    return {**sess, "axes": axes}


def spectrum_features(sess: dict, calib_segs: dict, starts: np.ndarray) -> pd.DataFrame:
    ts, fs = sess["ts"], sess["fs"]
    calib, calib_shape = {}, {}
    for key in SPEC_AXES:
        f, p = calibration_psd(calib_segs[key], fs)
        calib[key] = p
        band = np.array([p[(f >= lo) & (f < hi)].mean() for lo, hi in BANDS_HZ])
        calib_shape[key] = 10 * np.log10(band / band.sum())
    rows = []
    for start in starts:
        lo, hi = np.searchsorted(ts, [start, start + WINDOW_S * 1000.0])
        row = {"start_ms": start}
        for key in SPEC_AXES:
            _, p = welch(sess["axes"][key][lo:hi], fs=fs, nperseg=NPERSEG)
            ratio_db = 10 * np.log10(p / calib[key])
            for i, (b_lo, b_hi) in enumerate(BANDS_HZ):
                band = (f >= b_lo) & (f < b_hi)
                row[f"{key}_spec_{b_lo:g}_{b_hi:g}"] = float(ratio_db[band].mean())
                row[f"{key}_shape_{b_lo:g}_{b_hi:g}"] = float(10 * np.log10(p[band].mean()) - calib_shape[key][i])
        rows.append(row)
    return pd.DataFrame(rows)


SPEC = [f"{a}_spec_{lo:g}_{hi:g}" for a in SPEC_AXES for lo, hi in BANDS_HZ]
SHAPE_SPEC = [f"{a}_shape_{lo:g}_{hi:g}" for a in SPEC_AXES for lo, hi in BANDS_HZ]
# (補正, 特徴量セットの名前, 列)
CASES = [
    ("none", "xyz18", cols("xyz", BASIC + SHAPE)),
    ("none", "m6", cols("m", BASIC + SHAPE)),
    ("scale", "xyz18", cols("xyz", BASIC + SHAPE)),
    ("scale", "m6", cols("m", BASIC + SHAPE)),
    ("lpc", "xyz18", cols("xyz", BASIC + SHAPE)),
    ("lpc", "m6", cols("m", BASIC + SHAPE)),
    ("spectrum", "spec12", SPEC),
    ("spectrum", "spec12+shape", SPEC + cols("zm", SHAPE)),
    ("lpc_shape", "xyz18", cols("xyz", BASIC + SHAPE)),
    ("lpc_shape", "m6", cols("m", BASIC + SHAPE)),
    ("spectrum_shape", "spec12", SHAPE_SPEC),
    ("spectrum_shape", "spec12+shape", SHAPE_SPEC + cols("zm", SHAPE)),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", default="configs/sessions/10.31.csv")
    parser.add_argument("--data-dir", default="wheelchair_data/10.31")
    parser.add_argument("--calib", default="session", choices=["session", "chair"],
                        help="キャリブレーションをセッションごと(段差・凸凹に着く前の走行)にするか、車椅子ごとにするか")
    parser.add_argument("--output-dir", default="data/analysis/20261031_chair_normalization")
    args = parser.parse_args()

    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(ROOT / args.sessions, dtype={"session_id": str})
    meta = meta[~meta["session_id"].isin(EXCLUDE)]
    kind_of = dict(zip(meta["session_id"], meta["kind"]))
    chair_of = dict(zip(meta["session_id"], meta["wheelchair"]))

    frames: dict[str, list] = {"none": [], "scale": [], "lpc": [], "lpc_shape": [], "spectrum": [], "spectrum_shape": []}
    calib_seconds = {}
    chair_calib = {}
    if args.calib == "chair":
        for chair, (path, a, b) in CHAIR_CALIB.items():
            ref = load_session(ROOT / path)
            t = (ref["ts"] - ref["ts"][0]) / 1000.0
            chair_calib[chair] = calib_segments(ref, (t >= a) & (t < b))
    for s in meta["session_id"]:
        sess = load_session(ROOT / args.data_dir / s)
        passes = load_passes(ROOT / args.data_dir / s) if kind_of[s] != "flat" else pd.DataFrame(
            columns=["kind", "pass_id", "start_ms", "stop_ms", "sub", "cancelled"])
        if args.calib == "chair":
            calib = chair_calib[chair_of[s]]
            calib_seconds[s] = sum(len(x) for x in calib["z"]) / sess["fs"]
        else:
            mask = calibration_mask(sess, passes, kind_of[s])
            calib = calib_segments(sess, mask)
            calib_seconds[s] = mask.sum() / sess["fs"]
        base = window_features(sess, WINDOW_S)
        intervals, dropped = intervals_for(passes, CONDITION) if len(passes) else ({}, [])
        labels = label_windows(base, WINDOW_S, kind_of[s], intervals, dropped)
        keep = labels.notna().to_numpy().copy()
        # キャリブレーションに使った区間の窓は評価に使わない
        t_rel = ((base["start_ms"] - sess["ts"][0]) / 1000.0).to_numpy()
        if args.calib == "session" and kind_of[s] == "flat":
            keep &= t_rel >= FLAT_CALIB_S[1]
        for path, _a, b in CHAIR_CALIB.values():
            if args.calib == "chair" and path.endswith(s):
                keep &= t_rel >= b
        meta_cols = {"label": labels, "group": s, "wheelchair": chair_of[s]}
        frames["none"].append(base.assign(**meta_cols)[keep])
        for method in ("scale", "lpc", "lpc_shape"):
            win = window_features(transformed_session(sess, calib, method), WINDOW_S)
            frames[method].append(win.assign(**meta_cols)[keep])
        spec = spectrum_features(sess, calib, base["start_ms"].to_numpy())
        spec = spec.merge(base[["start_ms"] + cols("zm", SHAPE)], on="start_ms")
        frames["spectrum"].append(spec.assign(**meta_cols)[keep])
        frames["spectrum_shape"].append(spec.assign(**meta_cols)[keep])
    print("キャリブレーションの長さ [s]:", {k[-6:]: round(v, 1) for k, v in calib_seconds.items()})

    rows = []
    for method, feature_set, features in CASES:
        df = pd.concat(frames[method], ignore_index=True)
        std = df[df["wheelchair"] == "standard"]
        orig = df[df["wheelchair"] == "original"]
        for model_name, model in models().items():
            pred = cross_val_predict(model, std[features], std["label"], groups=std["group"], cv=LeaveOneGroupOut())
            fitted = clone(model).fit(std[features], std["label"])
            pred_o = fitted.predict(orig[features])
            row = {"method": method, "features": feature_set, "model": model_name}
            for k in ("flat", "dansa", "dekobo"):
                row[f"std_{NAME[k]}"] = float((pred[std["label"] == k] == k).mean())
            for k in ("dansa", "dekobo"):
                sub = pred_o[(orig["label"] == k).to_numpy()]
                row[f"orig_{NAME[k]}"] = float((sub == k).mean())
                for q in ("flat", "dansa", "dekobo"):
                    if q != k:
                        row[f"orig_{NAME[k]}_to_{NAME[q]}"] = float((sub == q).mean())
            rows.append(row)
            print(f"{method:8s} {feature_set:12s} {model_name:12s} "
                  f"汎用(LOGO) flat/step/rough={row['std_flat']:.2f}/{row['std_step']:.2f}/{row['std_rough']:.2f}  "
                  f"汎用→従来 step/rough={row['orig_step']:.2f}/{row['orig_rough']:.2f}", flush=True)
    pd.DataFrame(rows).to_csv(out / f"results_{args.calib}.csv", index=False)


if __name__ == "__main__":
    main()
