"""今の特徴量(基本4+尖度・クレスト)に、性質の違う特徴量を1種類ずつ足して評価する(後ろ固定のみ、10.3+10.4)。

評価の枠組み(方針A、窓の1/4刻み、LOGO、モデル)は evaluate_103_burst_segment と同じ。
ベースは z6(z軸のみ)・xyz18(3軸)・m6(合成)の3つ。追加する特徴量も、ベースと同じ軸ごとに計算する。

追加する特徴量のグループ:
- peaks       : ピーク数(1秒あたり)。|x−窓平均| が閾値θを超える極大の数。ピーク間の最小間隔は 50ms
- tat         : 閾値超過時間率。|x−窓平均| > θ のサンプルの割合
- band_ratio  : 帯域パワー比(帯域のパワー / 全体のパワー)。帯域は 10.6 の帯域パワーと同じ区切り
- spec_entropy: スペクトルエントロピー(0〜1)
- acf         : 自己相関のピーク値と、そのラグ[s]。ラグ0付近の山を避けるため、自己相関が最初に負になった後から窓の半分までで探す
θ は fold ごとに、学習データの flat の窓だけから μ+3σ(|x−窓平均| のサンプル全体)で決める。
テストの情報は使わない。step と rough の2クラス評価では flat はテストに入らないので、全 flat の窓から決める。

--step single    : ベースに1グループだけ足す
--step cumulative: single の結果(2.0秒窓、SVM と RF の3クラス精度の差の平均)の良い順に積み上げる
--step noise     : RF のシードを変えたときのベースのばらつき(差を読むときの目安)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix

from src.scripts.evaluate_103_baseline import LABELS
from src.scripts.evaluate_103_baseline import models
from src.scripts.evaluate_103_burst_segment import BASIC
from src.scripts.evaluate_103_burst_segment import SHAPE
from src.scripts.evaluate_103_burst_segment import build_run
from src.scripts.evaluate_103_burst_segment import summarize
from src.scripts.evaluate_related_features import BANDS
from src.scripts.evaluate_related_features import cols

BAND_RATIO = [f"br_{int(lo)}_{'max' if np.isinf(hi) else int(hi)}" for lo, hi in BANDS]
GROUPS = {
    "peaks": ["peak_rate"],
    "tat": ["tat"],
    "band_ratio": BAND_RATIO,
    "spec_entropy": ["spec_entropy"],
    "acf": ["acf_peak", "acf_lag"],
}
THRESHOLD_FEATS = ["peak_rate", "tat"]  # θ に依存するので fold ごとに計算する
BASES = {"z6": "z", "xyz18": "xyz", "m6": "m"}
PEAK_GAP_S = 0.050
THETA_SIGMA = 3.0
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}

# 窓ごとの |x−窓平均|(θ に依存する特徴量を fold ごとに計算し直すために持っておく)
RAW: list[np.ndarray] = []


def spectral_features(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    """帯域パワー比とスペクトルエントロピー。パワーの求め方は evaluate_related_features.freq_features と同じ。"""
    x = values - values.mean()
    taper = np.hanning(len(x))
    power = np.abs(np.fft.rfft(x * taper)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    ac, f = power[1:], freqs[1:]  # 直流成分を除く
    total = ac.sum()
    prob = ac / total if total > 0 else np.full(len(ac), 1.0 / len(ac))
    row = {f"{prefix}_{name}": float(prob[(f >= lo) & (f < hi)].sum()) for (lo, hi), name in zip(BANDS, BAND_RATIO)}
    row[f"{prefix}_spec_entropy"] = float(-np.sum(prob * np.log(prob + 1e-20)) / np.log(len(prob)))
    return row


def acf_features(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    """自己相関のピーク値とラグ。周期的な揺れほどピーク値が大きい。"""
    x = values - values.mean()
    n = len(x)
    spec = np.fft.rfft(x, 2 * n)
    r = np.fft.irfft(np.abs(spec) ** 2)[:n]
    if r[0] <= 0:
        return {f"{prefix}_acf_peak": 0.0, f"{prefix}_acf_lag": 0.0}
    r = r / r[0]
    half = n // 2
    neg = np.flatnonzero(r[:half] < 0)
    if len(neg) == 0:  # 窓の半分まで負にならない(ゆっくりした変化しかない)
        return {f"{prefix}_acf_peak": 0.0, f"{prefix}_acf_lag": half / fs}
    k = neg[0] + int(np.argmax(r[neg[0]:half]))
    return {f"{prefix}_acf_peak": float(r[k]), f"{prefix}_acf_lag": k / fs}


def raw_store(values: np.ndarray, prefix: str, fs: float, window_s: float) -> dict[str, float]:
    RAW.append(np.abs(values - values.mean()))
    return {f"{prefix}_rid": len(RAW) - 1, "fs": fs}


def load_windows(run_dirs: list[Path], window_s: float) -> pd.DataFrame:
    return pd.concat([build_run(d, window_s, 5, extra_features=(spectral_features, acf_features, raw_store))
                      for d in run_dirs], ignore_index=True)


class ThresholdFeatures:
    """θ に依存する特徴量(ピーク数・閾値超過時間率)。同じ θ の計算結果は使い回す。"""

    def __init__(self, df: pd.DataFrame, window_s: float):
        self.df, self.window_s = df, window_s
        self.fs = float(df["fs"].iloc[0])
        self.cache: dict[tuple[str, float], pd.DataFrame] = {}

    def theta(self, axis: str, flat_index: np.ndarray) -> float:
        samples = np.concatenate([RAW[i] for i in self.df.loc[flat_index, f"{axis}_rid"]])
        return float(samples.mean() + THETA_SIGMA * samples.std())

    def compute(self, axis: str, theta: float) -> pd.DataFrame:
        key = (axis, round(theta, 9))
        if key not in self.cache:
            dist = max(1, int(PEAK_GAP_S * self.fs))
            peaks, tat = [], []
            for i in self.df[f"{axis}_rid"]:
                a = RAW[i]
                peaks.append(len(find_peaks(a, height=theta, distance=dist)[0]) / self.window_s)
                tat.append(float(np.mean(a > theta)))
            self.cache[key] = pd.DataFrame({f"{axis}_peak_rate": peaks, f"{axis}_tat": tat}, index=self.df.index)
        return self.cache[key]

    def matrix(self, axes: str, feats: list[str], flat_index: np.ndarray) -> tuple[pd.DataFrame, dict]:
        parts, thetas = [], {}
        for a in axes:
            thetas[a] = self.theta(a, flat_index)
            parts.append(self.compute(a, thetas[a])[[f"{a}_{f}" for f in feats]])
        return pd.concat(parts, axis=1), thetas


def logo_predict(df: pd.DataFrame, static_cols: list[str], thr: ThresholdFeatures, axes: str,
                 thr_feats: list[str], model) -> tuple[np.ndarray, dict]:
    """LOGO の予測。θ に依存する特徴量は fold ごとに、学習側の flat の窓だけから θ を決めて作る。"""
    pred = np.empty(len(df), dtype=object)
    groups = df["group"].to_numpy()
    theta_log: dict[str, list[float]] = {a: [] for a in axes}
    for g in np.unique(groups):
        test = groups == g
        x = df[static_cols]
        if thr_feats:
            flat_train = df.index[(~test) & (df["label"] == "flat").to_numpy()]
            extra, thetas = thr.matrix(axes, thr_feats, flat_train)
            x = pd.concat([x, extra.loc[df.index]], axis=1)
            for a, t in thetas.items():
                theta_log[a].append(t)
        m = clone(model).fit(x[~test], df["label"][~test])
        pred[test] = m.predict(x[test])
    return pred, {a: float(np.mean(v)) for a, v in theta_log.items() if v}


def evaluate(df: pd.DataFrame, thr: ThresholdFeatures, axes: str, feats: list[str], model) -> dict:
    static = cols(axes, [f for f in feats if f not in THRESHOLD_FEATS])
    thr_feats = [f for f in feats if f in THRESHOLD_FEATS]
    pred, thetas = logo_predict(df, static, thr, axes, thr_feats, model)
    y = df["label"].to_numpy()
    result = summarize(y, pred)
    cm = confusion_matrix(y, pred, labels=LABELS)
    for i, t in enumerate(LABELS):
        for j, p in enumerate(LABELS):
            if i != j:
                result[f"n_{NAME[t]}_to_{NAME[p]}"] = int(cm[i, j])
    # step と rough だけの2クラス評価。θ は全 flat の窓から決める(flat はテストに入らない)。
    is_sr = (df["label"] != "flat").to_numpy()
    sr = df[is_sr]
    sr_static = df.loc[sr.index, static]
    if thr_feats:
        extra, _ = thr.matrix(axes, thr_feats, df.index[~is_sr])
        sr_static = pd.concat([sr_static, extra.loc[sr.index]], axis=1)
    sr_pred = np.empty(len(sr), dtype=object)
    g = sr["group"].to_numpy()
    for u in np.unique(g):
        test = g == u
        m = clone(model).fit(sr_static[~test], sr["label"][~test])
        sr_pred[test] = m.predict(sr_static[test])
    result["sr_bal_acc"] = balanced_accuracy_score(sr["label"], sr_pred)
    result["n_features"] = len(axes) * len(feats)
    result.update({f"theta_{a}": t for a, t in thetas.items()})
    return result


def log(base: str, config: str, model_name: str, r: dict) -> None:
    print(f"  {base:6s}{config:42s}{model_name:13s} n={r['n_features']:2d} bal_acc={r['bal_acc']:.3f} "
          f"flat/step/rough={r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f} "
          f"sr={r['sr_bal_acc']:.3f} step→rough={r['n_step_to_rough']} rough→step={r['n_rough_to_step']} "
          f"step→flat={r['n_step_to_flat']}", flush=True)


def run_single(windows: dict, out: Path) -> pd.DataFrame:
    rows = []
    for window_s, (df, thr) in windows.items():
        print(f"\n=== single 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
        for base, axes in BASES.items():
            configs = {"ベース": BASIC + SHAPE, **{f"+{g}": BASIC + SHAPE + f for g, f in GROUPS.items()}}
            for config, feats in configs.items():
                for model_name, model in models().items():
                    r = evaluate(df, thr, axes, feats, model)
                    rows.append({"window_s": window_s, "base": base, "config": config, "model": model_name, **r})
                    log(base, config, model_name, r)
    result = pd.DataFrame(rows)
    result.to_csv(out / "single_sweep.csv", index=False)
    return result


def cumulative_order(single: pd.DataFrame, base: str) -> list[str]:
    s = single[(single["window_s"] == 2.0) & (single["base"] == base)]
    gain = s.groupby("config")["bal_acc"].mean()
    gain = (gain.drop("ベース") - gain["ベース"]).sort_values(ascending=False)
    return [c.lstrip("+") for c in gain.index]


def run_cumulative(windows: dict, single: pd.DataFrame, out: Path) -> None:
    rows = []
    for base, axes in BASES.items():
        order = cumulative_order(single, base)
        print(f"\n=== cumulative {base} 順番: {order}", flush=True)
        for window_s, (df, thr) in windows.items():
            feats, names = BASIC + SHAPE, []
            for k, g in enumerate(order, start=1):
                feats, names = feats + GROUPS[g], names + [g]
                config = "ベース+" + "+".join(names)
                for model_name, model in models().items():
                    r = evaluate(df, thr, axes, feats, model)
                    rows.append({"window_s": window_s, "base": base, "step": k, "added": g,
                                 "config": config, "model": model_name, **r})
                    log(base, f"{window_s}s +{g}", model_name, r)
    pd.DataFrame(rows).to_csv(out / "cumulative_sweep.csv", index=False)


def run_noise(windows: dict, out: Path, seeds: int) -> None:
    rows = []
    for window_s, (df, thr) in windows.items():
        for base, axes in BASES.items():
            for seed in range(seeds):
                model = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=seed)
                r = evaluate(df, thr, axes, BASIC + SHAPE, model)
                rows.append({"window_s": window_s, "base": base, "seed": seed, **r})
            s = pd.DataFrame(rows).query("window_s == @window_s and base == @base")
            print(f"  noise {window_s}s {base}: RF bal_acc {s['bal_acc'].mean():.3f}±{s['bal_acc'].std():.3f} "
                  f"(min {s['bal_acc'].min():.3f}, max {s['bal_acc'].max():.3f}) "
                  f"sr {s['sr_bal_acc'].mean():.3f}±{s['sr_bal_acc'].std():.3f}", flush=True)
    pd.DataFrame(rows).to_csv(out / "rf_seed_noise.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="後ろ固定のみのセッションを並べたディレクトリ")
    parser.add_argument("--step", nargs="+", default=["single", "cumulative", "noise"],
                        choices=["single", "cumulative", "noise"])
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0, 1.0])
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--output-dir", default="data/analysis/20261017_added_features")
    args = parser.parse_args()

    run_dirs = sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    windows = {}
    for w in args.windows:
        df = load_windows(run_dirs, w)
        windows[w] = (df, ThresholdFeatures(df, w))
    if "single" in args.step:
        single = run_single(windows, out)
    else:
        single = pd.read_csv(out / "single_sweep.csv")
    if "cumulative" in args.step:
        run_cumulative(windows, single, out)
    if "noise" in args.step:
        run_noise(windows, out, args.seeds)


if __name__ == "__main__":
    main()
