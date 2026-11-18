"""g_low_high(傾きの速さ g の、低い周波数 ÷ 高い周波数のパワー)を使う根拠を確かめる。

g_low_high は 2026-11-01 に「段差はゆっくり大きく傾く」という見立てで足したが、境目(5 Hz 未満・10 Hz 超)と、
5〜10 Hz を除く理由を調べていなかった(ゼミ資料 131-017 では外した)。ここでは次を調べる。

  1. g のパワースペクトルの形(全体のパワーで割った相対値)を、クラスごとに比べる。
     比べるため、加速度の上下 z も同じように計算する。
  2. 境目を変えた g_low_high(低い帯域 f < a、高い帯域 f > b)で、
     段差と凸凹をどれだけ分けられるか(AUC)と、ゼミで発表した core に足したときの精度を見る。
  3. 1 の傾向が、境目を決めるのに使っていない 51 kg の人のデータでも同じかを見る。

条件は e20261101_gyro_features と同じ(10.31 汎用 + 11.1 の 68〜69 kg、16 セッション、use=yes、方針A、
START を 1 秒ずらす、SVM、セッション単位の LOGO)。51 kg の人の 6 セッションは、確認と体重のテストだけに使う。

出力(data/analysis/20261104_g_low_high_rationale/):
  psd_class.csv     : クラスごとの相対パワースペクトル(窓ごとの値の中央値・四分位)
  band_session.csv  : セッションごとの、g の帯域ごとのパワーの割合と g_low_high の中央値
  variants.csv      : 境目ごとの AUC と、core に足したときの再現率
  transfer.csv      : 体重のテスト(68〜69 kg ⇄ 51 kg)の再現率
  g_spectrum.png、g_low_high_session.png、g_waveform.png(docs/knowledge/2026-11-04/images/ にも保存)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import periodogram
from scipy.signal import welch
from sklearn.metrics import confusion_matrix
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.experiments.e20261031_button_lag import label_windows
from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_button_lag import window_features
from src.experiments.e20261101_combined_eval import intervals
from src.experiments.e20261101_combined_eval import load_meta
from src.experiments.e20261101_gyro_features import add_gyro
from src.experiments.e20261101_gyro_features import gyro_window_features
from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
DOC_IMAGES = ROOT / "docs/knowledge/2026-11-04/images"
SHIFT_S = 1.0
NPERSEG = 256  # g_low_high と同じ(約 334 Hz で 1.3 Hz ごと)
FREQ_GRID = np.arange(0.5, 100.01, 0.5)  # 図のための、窓 1 本の periodogram を並べる周波数
LOWS = [2.0, 3.0, 5.0, 7.0, 10.0]
HIGHS = [None, 5.0, 10.0, 15.0, 20.0, 30.0]  # None = 低い帯域の上限と同じ(すき間なし)
CORE = ["z_rms", "z_kurt", "h_std", "h_crest", "tilt_range"]  # ゼミ資料 131-017 の core(暫定)
CORE5_BASE = ["z_rms", "z_kurt", "tilt_range", "g_over_z"]  # 研究メモの core5 から g_low_high を除いたもの

INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"
CLASS_COLOR = {"flat": "#1baf7a", "dansa": "#2a78d6", "dekobo": "#eb6834"}
CLASS_NAME = {"flat": "flat", "dansa": "段差", "dekobo": "凸凹"}


def load_windows(meta: pd.DataFrame, window_s: float) -> tuple[pd.DataFrame, dict, np.ndarray, np.ndarray]:
    """窓ごとの特徴量とラベル、g・z の welch のスペクトル、g・z の相対パワースペクトル(FREQ_GRID 上)。"""
    frames, welch_p, rel_g, rel_z = [], {"g": [], "z": []}, [], []
    for s, d, k, w in zip(meta["session_id"], meta["day"], meta["kind"], meta["weight_kg"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        sess["axes"]["h"] = np.hypot(sess["axes"]["x"], sess["axes"]["y"])
        add_gyro(sess, run_dir)
        win = window_features(sess, window_s)
        win = win.merge(gyro_window_features(sess, win["start_ms"].to_numpy(), window_s), on="start_ms")
        if k == "flat":
            iv, dr = {}, []
        else:
            iv, dr = intervals(load_passes(run_dir), SHIFT_S)
        win = win.assign(label=label_windows(win, window_s, k, iv, dr), group=s, day=d, weight=w)
        win = win.dropna(subset=["label"]).reset_index(drop=True)
        ts, fs = sess["ts"], sess["fs"]
        for start in win["start_ms"]:
            lo, hi = np.searchsorted(ts, [start, start + window_s * 1000.0])
            g, z = sess["axes"]["g"][lo:hi], sess["axes"]["z"][lo:hi]
            for key, sig in (("g", g), ("z", z)):
                f, p = welch(sig - sig.mean(), fs=fs, nperseg=min(NPERSEG, len(sig)))
                welch_p[key].append(np.interp(WELCH_F, f, p))
            for sig, out in ((g, rel_g), (z, rel_z)):
                fp, pp = periodogram(sig - sig.mean(), fs=fs, window="hann")
                out.append(np.interp(FREQ_GRID, fp, pp) / pp[fp > 0].sum())
        frames.append(win)
    return (pd.concat(frames, ignore_index=True), {k: np.array(v) for k, v in welch_p.items()},
            np.array(rel_g), np.array(rel_z))


WELCH_F = np.arange(NPERSEG // 2 + 1) * 334.37 / NPERSEG  # 全セッションでほぼ同じ fs(334.37 Hz)


def low_high(p: np.ndarray, low: float, high: float) -> np.ndarray:
    """g_low_high と同じ計算(log10(f < low のパワーの和 ÷ f > high のパワーの和))。"""
    lo = p[:, (WELCH_F > 0) & (WELCH_F < low)].sum(axis=1)
    hi = p[:, WELCH_F > high].sum(axis=1)
    return np.log10((lo + 1e-12) / (hi + 1e-12))


def evaluate(df: pd.DataFrame, features: list[str], train: np.ndarray | None = None) -> dict:
    """SVM のクラスごとの再現率と、段差 ↔ 凸凹の取り違え。train を渡すと、train で学習して残りでテスト。"""
    model = models()["SVM"]
    if train is None:
        y, pred = df["label"], cross_val_predict(model, df[features], df["label"], groups=df["group"],
                                                 cv=LeaveOneGroupOut())
    else:
        model.fit(df.loc[train, features], df.loc[train, "label"])
        y, pred = df.loc[~train, "label"], model.predict(df.loc[~train, features])
    m = confusion_matrix(y, pred, labels=LABELS)
    out = {f"r_{DISPLAY[k]}": float(m[i, i] / m[i].sum()) for i, k in enumerate(LABELS)}
    out["step_rough"] = int(m[1, 2] + m[2, 1])
    return out


def auc(df: pd.DataFrame, col: str, pos: str, neg: str) -> float:
    sub = df[df["label"].isin([pos, neg])]
    return float(roc_auc_score(sub["label"] == pos, sub[col]))


def style(ax) -> None:
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)


def plot_spectrum(psd: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, sig, title in ((axes[0], "g", "傾きの速さ g（ジャイロ）"), (axes[1], "z", "上下の加速度 z")):
        ax.axvspan(0.5, 5, color="#2a78d6", alpha=0.07, lw=0)
        ax.axvspan(10, 100, color="#eb6834", alpha=0.07, lw=0)
        for label in LABELS:
            q = psd[(psd["signal"] == sig) & (psd["label"] == label) & (psd["weight"] == "68-69")]
            ax.plot(q["freq"], q["median"], color=CLASS_COLOR[label], lw=1.8, label=CLASS_NAME[label])
            ax.fill_between(q["freq"], q["q25"], q["q75"], color=CLASS_COLOR[label], alpha=0.12, lw=0)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(0.5, 100)
        ax.set_xticks([1, 2, 5, 10, 20, 50, 100], ["1", "2", "5", "10", "20", "50", "100"])
        ax.xaxis.set_minor_formatter(plt.NullFormatter())
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        ax.set_xlabel("周波数 [Hz]", color=MUTED, fontsize=9)
        ax.text(np.sqrt(0.5 * 5), 0.25, "低い帯域\n（5 Hz 未満）", ha="center", va="top", fontsize=8, color="#184f95")
        ax.text(np.sqrt(10 * 100), 0.25, "高い帯域（10 Hz 超）", ha="center", va="top", fontsize=8, color="#a8471d")
        style(ax)
    axes[0].set_ylabel("相対パワー（窓の全体を 1）", color=MUTED, fontsize=9)
    axes[0].set_ylim(1e-5, 0.3)
    axes[1].legend(loc="lower left", frameon=False, fontsize=9)
    fig.text(0.01, 0.005, "汎用の車椅子・68〜69 kg・2.0 秒窓。線は窓ごとの値の中央値、帯は四分位範囲", fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_sessions(by_session: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    order = ["dansa", "dekobo", "flat"]
    rng = np.random.default_rng(0)
    for i, label in enumerate(order):
        q = by_session[by_session["label"] == label]
        for heavy, marker, name in ((True, "o", "68〜69 kg（評価の 16 セッション）"), (False, "^", "51 kg（評価に使っていない）")):
            r = q[q["heavy"] == heavy]
            x = i + (-0.12 if heavy else 0.12) + rng.uniform(-0.05, 0.05, len(r))
            ax.scatter(x, r["g_low_high"], s=36, marker=marker, color=CLASS_COLOR[label],
                       edgecolor="white", lw=0.6, label=name if i == 0 else None)
    ax.axhline(0, color=MUTED, lw=0.8, ls=":")
    ax.set_xticks(range(3), [CLASS_NAME[k] for k in order])
    ax.set_ylabel("g_low_high（セッションの中央値）", color=MUTED, fontsize=9)
    ax.set_title("傾きの速さの「低い ÷ 高い」は、段差で高く凸凹・flat で低い", fontsize=11, color=INK, loc="left")
    leg = ax.legend(loc="upper right", frameon=False, fontsize=8)
    for h in leg.legend_handles:
        h.set_color(MUTED)
    style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_waveform(meta: pd.DataFrame, path: Path) -> None:
    """段差と凸凹の通過 1 回ずつの、g と傾きの波形(同じ人・同じ日)。"""
    picks = [("dansa", "20261101140700"), ("dekobo", "20261101141730")]
    fig, axes = plt.subplots(2, 2, figsize=(10, 4.6), sharex=True, sharey="row")
    for col, (label, s) in enumerate(picks):
        d = meta.loc[meta["session_id"] == s, "day"].iloc[0]
        run_dir = ROOT / "wheelchair_data" / d / s
        sess = load_session(run_dir)
        add_gyro(sess, run_dir)
        iv, _ = intervals(load_passes(run_dir), SHIFT_S)
        a, b = iv[label][0]
        mid = (a + b) / 2.0
        ts = sess["ts"]
        sel = (ts >= mid - 2000.0) & (ts < mid + 2000.0)
        t = (ts[sel] - mid) / 1000.0
        axes[0, col].plot(t, sess["axes"]["g"][sel], color=CLASS_COLOR[label], lw=0.8)
        tilt = sess["tilt"][sel]
        axes[1, col].plot(t, tilt - np.median(tilt), color=CLASS_COLOR[label], lw=1.2)
        axes[0, col].set_title(f"{CLASS_NAME[label]}（{s}、1 回目の通過の中央 ±2 秒）", fontsize=10, color=INK, loc="left")
        axes[1, col].set_xlabel("時間 [秒]", color=MUTED, fontsize=9)
        for ax in axes[:, col]:
            style(ax)
    axes[0, 0].set_ylabel("傾きの速さ g [rad/s]", color=MUTED, fontsize=9)
    axes[1, 0].set_ylabel("傾き [度]（中央値からのずれ）", color=MUTED, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/analysis/20261104_g_low_high_rationale")
    args = parser.parse_args()
    out = ROOT / args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    DOC_IMAGES.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = ["Hiragino Sans", "YuGothic", "sans-serif"]
    pd.set_option("display.width", 220)

    meta = load_meta(["10.31", "11.1"], "standard", [51, 68, 69])
    print("使うセッション:", meta.groupby(["weight_kg", "kind"]).size().to_dict())

    psd_rows, variant_rows, transfer_rows, session_frames = [], [], [], []
    for window_s in [2.0, 1.0]:
        df, welch_p, rel_g, rel_z = load_windows(meta, window_s)
        welch_g = welch_p["g"]
        heavy = df["weight"].isin([68, 69]).to_numpy()
        print(f"\n== 窓 {window_s:.1f} 秒  窓数:", df[heavy].groupby("label").size().to_dict(),
              " 51 kg:", df[~heavy].groupby("label").size().to_dict())

        # 1. 相対パワースペクトル(クラスごとの中央値・四分位)
        if window_s == 2.0:
            for sig, rel in (("g", rel_g), ("z", rel_z)):
                for wname, mask in (("68-69", heavy), ("51", ~heavy)):
                    for label in LABELS:
                        r = rel[mask & (df["label"] == label).to_numpy()]
                        q25, med, q75 = np.percentile(r, [25, 50, 75], axis=0)
                        psd_rows.append(pd.DataFrame({"signal": sig, "weight": wname, "label": label,
                                                      "freq": FREQ_GRID, "median": med, "q25": q25, "q75": q75}))
            # 帯域ごとのパワーの割合(welch、g_low_high と同じスペクトル)
            total = welch_g[:, WELCH_F > 0].sum(axis=1)
            df["g_frac_low"] = welch_g[:, (WELCH_F > 0) & (WELCH_F < 5)].sum(axis=1) / total
            df["g_frac_mid"] = welch_g[:, (WELCH_F >= 5) & (WELCH_F <= 10)].sum(axis=1) / total
            df["g_frac_high"] = welch_g[:, WELCH_F > 10].sum(axis=1) / total
            sess = (df.groupby(["group", "day", "weight", "label"])
                    [["g_frac_low", "g_frac_mid", "g_frac_high", "g_low_high", "tilt_range"]].median().reset_index())
            session_frames.append(sess.assign(heavy=sess["weight"].isin([68, 69])))
            print("\n帯域ごとの g のパワーの割合(窓ごとの中央値):")
            print(df.assign(w=np.where(heavy, "68-69", "51")).groupby(["w", "label"])
                  [["g_frac_low", "g_frac_mid", "g_frac_high", "g_low_high"]].median().round(3))
            # 確認: 再計算した (5, 10) が、gyro_window_features の g_low_high と一致するか
            diff = np.abs(low_high(welch_g, 5.0, 10.0) - df["g_low_high"].to_numpy())
            print("g_low_high の再計算との差(最大):", float(diff.max()))

        # 2. 境目を変える(学習・評価は 68〜69 kg の 16 セッションだけ)
        dh = df[heavy].reset_index(drop=True)
        wg, wz = welch_g[heavy], welch_p["z"][heavy]
        base = {"window_s": window_s}
        variant_rows.append({**base, "low": np.nan, "high": np.nan, "features": "core",
                             **evaluate(dh, CORE)})
        variant_rows.append({**base, "low": np.nan, "high": np.nan, "features": "core5-g_low_high",
                             **evaluate(dh, CORE5_BASE)})
        for low in LOWS:
            for high in HIGHS:
                high_v = low if high is None else high
                if high_v < low or (high is not None and high == low):  # すき間なしは None の 1 回だけ
                    continue
                dh["glh"] = low_high(wg, low, high_v)
                dh["zlh"] = low_high(wz, low, high_v)  # 加速度 z の同じ比(比べるため)
                row = {**base, "low": low, "high": high_v,
                       "auc_step_rough": auc(dh, "glh", "dansa", "dekobo"),
                       "auc_step_rough_z": auc(dh, "zlh", "dansa", "dekobo"),
                       "auc_step_flat": auc(dh, "glh", "dansa", "flat"),
                       "auc_rough_flat": auc(dh, "glh", "dekobo", "flat")}
                variant_rows.append({**row, "features": "core+glh", **evaluate(dh, CORE + ["glh"])})
                variant_rows.append({**row, "features": "core5", **evaluate(dh, CORE5_BASE + ["glh"])})
        print(pd.DataFrame([r for r in variant_rows if r["window_s"] == window_s])
              .round(3).to_string(index=False))

        # 3. 体重のテスト(境目は 5・10 のまま)
        df["glh"] = df["g_low_high"]
        for name, train in (("heavy2light", heavy), ("light2heavy", ~heavy)):
            for fname, feats in (("core", CORE), ("core+g_low_high", CORE + ["glh"])):
                transfer_rows.append({"window_s": window_s, "test": name, "features": fname,
                                      **evaluate(df, feats, train)})
        print(pd.DataFrame([r for r in transfer_rows if r["window_s"] == window_s]).round(3).to_string(index=False))

    psd = pd.concat(psd_rows, ignore_index=True)
    by_session = pd.concat(session_frames, ignore_index=True)
    psd.to_csv(out / "psd_class.csv", index=False)
    by_session.to_csv(out / "band_session.csv", index=False)
    pd.DataFrame(variant_rows).to_csv(out / "variants.csv", index=False)
    pd.DataFrame(transfer_rows).to_csv(out / "transfer.csv", index=False)
    print("\nセッションごと:")
    print(by_session.sort_values(["label", "weight"]).round(3).to_string(index=False))

    for name, fn in (("g_spectrum.png", lambda p: plot_spectrum(psd, p)),
                     ("g_low_high_session.png", lambda p: plot_sessions(by_session, p)),
                     ("g_waveform.png", lambda p: plot_waveform(meta, p))):
        fn(out / name)
        fn(DOC_IMAGES / name)


if __name__ == "__main__":
    main()
