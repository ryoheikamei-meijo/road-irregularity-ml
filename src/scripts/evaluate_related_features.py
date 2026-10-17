"""関連研究で使われている特徴量を、後ろ固定のみの10.3+10.4に足して評価する。

評価の枠組み(方針A、窓の1/4刻み、LOGO、モデル)は evaluate_103_burst_segment と同じ。
追加する特徴量のグループ:
- stats: 歪度・パーセンタイル(5/25/50/75/95%)・IQR・ゼロ交差率・平均交差率 (Virin 2025, Wu 2020)
- freq : 帯域パワー(log)・ピーク周波数・スペクトル重心・スペクトルエントロピー (Wu 2020)
- stft : 短時間フーリエ変換のフレームごとのエネルギーの変動係数・エントロピー (Martinelli 2022)
- hv   : 水平の大きさ√(x²+y²)と鉛直zの比 (Eriksson 2008 のx/z比を、向きに依存しない形にしたもの)
- prev : 直前の(重ならない)窓のベース特徴量 (Hoffmann 2013)
`--combo` で、効いたものの組み合わせと、そこから1グループずつ抜いた評価(ステップ6)も行う。
stats・freq・stft は軸ごとに計算し、hv・prev は窓特徴量から後で作る。

各グループについて、次の4通りを比べる(ベースは xyz30 と m10)。
  ベース / ベース+追加 / 基本4+追加 / 追加のみ
"ベース+追加" と "ベース" の差が、そのグループを抜いたときの落ち幅(ablation)にあたる。
3クラスに加えて、step と rough だけに絞った2クラスの balanced accuracy(`sr_bal_acc`)も出す。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import stft
from scipy.stats import skew

from src.scripts.evaluate_103_baseline import models
from src.scripts.evaluate_103_burst_segment import BASIC
from src.scripts.evaluate_103_burst_segment import BURST
from src.scripts.evaluate_103_burst_segment import SHAPE
from src.scripts.evaluate_103_burst_segment import build_run
from src.roadml.evaluation import evaluate
from src.roadml.features import cols

STATS = ["skew", "p05", "p25", "p50", "p75", "p95", "iqr", "zero_cross", "mean_cross"]
# 10.5 の前後比較で、凸凹の 20Hz 付近と 40〜80Hz に差が出ていたことをもとに区切る。
BANDS = [(0.5, 10.0), (10.0, 30.0), (30.0, 60.0), (60.0, 100.0), (100.0, np.inf)]
BAND_POWER = [f"bp_{int(lo)}_{'max' if np.isinf(hi) else int(hi)}" for lo, hi in BANDS]
FREQ = BAND_POWER + ["peak_freq", "centroid", "spec_entropy"]
STFT = ["stft_cv", "stft_entropy"]
STFT_FRAME_S = 0.1  # 段差のバースト(数百ms)より短く、1窓に10〜20フレーム入る長さ
HV = ["hv_rms_ratio", "hv_std_ratio"]
# ステップ1・2で効いた(flatの再現率を上げた)もの。
FLAT_CUES = ["zero_cross", "centroid"] + BAND_POWER
PER_AXIS_GROUPS = {"stats": STATS, "freq": FREQ, "stft": STFT}
GROUP_NAMES = ["stats", "freq", "stft", "hv", "prev"]
BASES = {"xyz30": "xyz", "m10": "m"}


def stats_features(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    p05, p25, p50, p75, p95 = np.percentile(values, [5, 25, 50, 75, 95])
    centered = values - values.mean()
    return {
        f"{prefix}_skew": float(skew(values)),
        f"{prefix}_p05": p05, f"{prefix}_p25": p25, f"{prefix}_p50": p50,
        f"{prefix}_p75": p75, f"{prefix}_p95": p95, f"{prefix}_iqr": p75 - p25,
        # 窓幅によらないよう、1秒あたりの回数にする。
        f"{prefix}_zero_cross": float(np.sum(np.diff(np.signbit(values)) != 0)) / window_s,
        f"{prefix}_mean_cross": float(np.sum(np.diff(np.signbit(centered)) != 0)) / window_s,
    }


def freq_features(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    x = values - values.mean()
    taper = np.hanning(len(x))
    power = np.abs(np.fft.rfft(x * taper)) ** 2 / (fs * np.sum(taper**2))
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    df = freqs[1] - freqs[0]
    row = {}
    for (lo, hi), name in zip(BANDS, BAND_POWER):
        mask = (freqs >= lo) & (freqs < hi)
        row[f"{prefix}_{name}"] = float(np.log10(power[mask].sum() * df + 1e-12))
    ac = power[1:]  # 直流成分を除く
    total = ac.sum()
    prob = ac / total if total > 0 else np.full(len(ac), 1.0 / len(ac))
    row[f"{prefix}_peak_freq"] = float(freqs[1:][np.argmax(ac)])
    row[f"{prefix}_centroid"] = float(np.sum(freqs[1:] * prob))
    row[f"{prefix}_spec_entropy"] = float(-np.sum(prob * np.log(prob + 1e-20)) / np.log(len(prob)))
    return row


def stft_features(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    """フレームごとのエネルギーが、時間方向にどれだけばらつくか。

    単発の衝撃(step)は一部のフレームにエネルギーが集中して変動係数が大きく、エントロピーが小さい。
    繰り返しの振動(rough・flat)は、どのフレームにも同程度のエネルギーがあり、その逆になる。
    """
    nperseg = max(8, int(STFT_FRAME_S * fs))
    _, _, z = stft(values - values.mean(), fs=fs, nperseg=nperseg, noverlap=nperseg // 2,
                   boundary=None, padded=False)
    energy = np.sum(np.abs(z) ** 2, axis=0)
    total = energy.sum()
    if len(energy) < 2 or total <= 0:
        return {f"{prefix}_stft_cv": 0.0, f"{prefix}_stft_entropy": 1.0}
    prob = energy / total
    return {
        f"{prefix}_stft_cv": float(energy.std() / energy.mean()),
        f"{prefix}_stft_entropy": float(-np.sum(prob * np.log(prob + 1e-20)) / np.log(len(prob))),
    }


def add_hv(df: pd.DataFrame) -> pd.DataFrame:
    """水平(x,y)と鉛直(z)の比。水平の大きさ√(x²+y²)は水平面内の向きに依存しない。

    rms²(√(x²+y²)) = rms²(x) + rms²(y) なので、窓特徴量から計算できる(std も同様)。
    """
    return df.assign(
        hv_rms_ratio=np.sqrt(df["x_rms"] ** 2 + df["y_rms"] ** 2) / df["z_rms"],
        hv_std_ratio=np.sqrt(df["x_std"] ** 2 + df["y_std"] ** 2) / df["z_std"],
    )


def add_prev(df: pd.DataFrame, window_s: float, feature_cols: list[str]) -> pd.DataFrame:
    """直前の重ならない窓(開始が窓幅ぶん前)の特徴量を `prev_` を付けて足す。

    同じセッション(flat はブロック)の中だけで探し、無い窓(先頭など)は自分自身の値で埋める。
    """
    key = df[["group", "start_ms"]].copy()
    key["start_ms"] = (key["start_ms"] - window_s * 1000.0).round(1)
    src = df[["group", "start_ms", *feature_cols]].copy()
    src["start_ms"] = src["start_ms"].round(1)
    prev = key.merge(src, on=["group", "start_ms"], how="left")
    out = df.copy()
    for c in feature_cols:
        out[f"prev_{c}"] = prev[c].fillna(df[c]).to_numpy()
    out["has_prev"] = prev[feature_cols[0]].notna().to_numpy()
    return out


def group_columns(group: str, axes: str) -> list[str]:
    if group in PER_AXIS_GROUPS:
        return cols(axes, PER_AXIS_GROUPS[group])
    if group == "hv":
        return HV
    if group == "prev":
        return [f"prev_{c}" for c in cols(axes, BASIC + SHAPE + BURST)]
    raise ValueError(group)


def load_windows(run_dirs: list[Path], window_s: float, cache: Path, rebuild: bool) -> pd.DataFrame:
    if cache.exists() and not rebuild:
        df = pd.read_csv(cache)
    else:
        df = pd.concat([build_run(d, window_s, 5, extra_features=(stats_features, freq_features, stft_features))
                        for d in run_dirs], ignore_index=True)
        df.to_csv(cache, index=False)
    df = add_hv(df)
    return add_prev(df, window_s, cols("xyzm", BASIC + SHAPE + BURST + STFT))


def combo_configs(axes: str) -> dict[str, list[str]]:
    """ステップ6: 効いたものの組み合わせと、全部入りから1グループずつ抜いたもの。"""
    def with_prev(feats: list[str]) -> list[str]:
        return cols(axes, feats) + [f"prev_{c}" for c in cols(axes, feats)]

    base, flat = cols(axes, BASIC + SHAPE + BURST), cols(axes, FLAT_CUES)
    full = with_prev(BASIC + SHAPE + BURST) + flat
    return {
        "ベース": base,
        "ベース+flat系": base + flat,
        "ベース+前の窓": with_prev(BASIC + SHAPE + BURST),
        "全部(ベース+前の窓+flat系)": full,
        "全部-基本4": [c for c in full if c not in with_prev(BASIC)],
        "全部-尖度・クレスト": [c for c in full if c not in with_prev(SHAPE)],
        "全部-バースト": [c for c in full if c not in with_prev(BURST)],
        "全部-flat系": [c for c in full if c not in flat],
        "全部-前の窓": [c for c in full if not c.startswith("prev_")],
        # 尖度・クレスト・バーストを STFT の2個に置き換えた、少ない個数の構成(ステップ3)。
        "小さい構成(基本4+STFT+flat系)": cols(axes, BASIC + STFT) + flat,
        "小さい構成+前の窓": with_prev(BASIC + STFT) + flat,
    }


def run_combo(windows: dict[float, pd.DataFrame], out: Path) -> None:
    rows = []
    for window_s, df in windows.items():
        print(f"\n=== combo 窓{window_s}s", flush=True)
        for base_name, axes in BASES.items():
            for config, feature_cols in combo_configs(axes).items():
                for model_name, model in models().items():
                    r = evaluate(df, feature_cols, model)
                    rows.append({"group": "combo", "window_s": window_s, "base": base_name,
                                 "config": config, "model": model_name,
                                 "n_features": len(feature_cols), **r})
                    print(f"  {base_name:6s}{config:22s}{model_name:13s} n={len(feature_cols):2d} "
                          f"bal_acc={r['bal_acc']:.3f} flat/step/rough="
                          f"{r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f} "
                          f"step-vs-rough={r['sr_bal_acc']:.3f}", flush=True)
    pd.DataFrame(rows).to_csv(out / "combo_sweep.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="後ろ固定のみのセッションを並べたディレクトリ")
    parser.add_argument("--groups", nargs="*", default=GROUP_NAMES, choices=GROUP_NAMES)
    parser.add_argument("--combo", action="store_true", help="ステップ6(組み合わせとグループ除去)を実行する")
    parser.add_argument("--windows", type=float, nargs="+", default=[1.0, 2.0])
    parser.add_argument("--output-dir", default="data/analysis/20261006_related_features")
    parser.add_argument("--rebuild", action="store_true", help="窓特徴量のキャッシュを作り直す")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    windows = {w: load_windows(run_dirs, w, out / f"windows_{w}s.csv", args.rebuild) for w in args.windows}
    for group in args.groups:
        rows = []
        for window_s, df in windows.items():
            print(f"\n=== {group} 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
            for base_name, axes in BASES.items():
                extra = group_columns(group, axes)
                configs = {
                    "基本4": cols(axes, BASIC),
                    "ベース": cols(axes, BASIC + SHAPE + BURST),
                    "ベース+追加": cols(axes, BASIC + SHAPE + BURST) + extra,
                    "基本4+追加": cols(axes, BASIC) + extra,
                    "追加のみ": extra,
                }
                for config, feature_cols in configs.items():
                    for model_name, model in models().items():
                        r = evaluate(df, feature_cols, model)
                        rows.append({"group": group, "window_s": window_s, "base": base_name,
                                     "config": config, "model": model_name,
                                     "n_features": len(feature_cols), **r})
                        print(f"  {base_name:6s}{config:8s}{model_name:13s} n={len(feature_cols):2d} "
                              f"bal_acc={r['bal_acc']:.3f} flat/step/rough="
                              f"{r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f} "
                              f"step-vs-rough={r['sr_bal_acc']:.3f}", flush=True)
        pd.DataFrame(rows).to_csv(out / f"{group}_sweep.csv", index=False)
    if args.combo:
        run_combo(windows, out)


if __name__ == "__main__":
    main()
