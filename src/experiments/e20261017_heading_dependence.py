"""世界座標系の x・y(東・北)が、車椅子の走る向きに依存していないかを調べる(後ろ固定のみ、10.3+10.4)。

1. 向きの確認(heading_stats.csv, heading_figure.png)
   - スマホの向き: rotation vector から、端末の y 軸を水平面に投影した方位(北から時計回り)。
     マウントで固定しているので、計測中は「車椅子の向き + 付け方で決まる一定のずれ」になる。
   - 水平の揺れの主な向き: 2 秒ごとに、世界座標系の x・y の共分散の第1主成分の方位(0〜180°)。
     揺れ(変動)の分散で重み付けした軸方向の平均と、その集中度(0〜1、1 なら全部同じ向き)。
2. 精度の確認(heading_eval.csv)
   - 特徴量セット: xyz18(今の構成)、z6、m6、zh12(z + 水平の大きさ √(x²+y²))、
     zuv18(z + 水平の揺れの主軸 u・それと直交する軸 v。主軸はセッションごとに、ラベルを使わずに決める)
   - 回転テスト: 学習はそのまま、テストのセッションだけ x・y を θ 回転させて予測する(別の向きに走った場合の想定)。
評価の枠組み(方針A、窓の1/4刻み、LOGO、モデル)は e20261005_burst_segment と同じ。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
from sklearn.base import clone
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix

from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.windows import build_run
from src.roadml.evaluation import summarize
from src.roadml.features import cols
from src.roadml.io import ROTATION_COLUMNS
from src.roadml.io import load_acc_dataframe
from src.roadml.io import transform_to_world_frame
from src.roadml.datasets import add_run_dir_args
from src.roadml.datasets import resolve_run_dirs

plt.rcParams["font.family"] = "Hiragino Sans"

FEATS = BASIC + SHAPE
ROTATE_DEG = [0, 45, 90, 180]
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}
SEG_S = 2.0


def axial_mean(deg: np.ndarray, weight: np.ndarray) -> tuple[float, float]:
    """0〜180° の軸方向のデータの平均と集中度(角度を2倍して平均する)。"""
    c = np.sum(weight * np.cos(np.radians(2 * deg)))
    s = np.sum(weight * np.sin(np.radians(2 * deg)))
    return float(np.degrees(np.arctan2(s, c)) / 2 % 180), float(np.hypot(c, s) / np.sum(weight))


def principal_axis(east: np.ndarray, north: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2 秒ごとの、水平の揺れの第1主成分の方位(北から時計回り、0〜180°)、分散、主/副の分散比。"""
    n = int(SEG_S * fs)
    az, var, ratio = [], [], []
    for s in range(0, len(east) - n, n // 2):
        e, w = east[s:s + n] - east[s:s + n].mean(), north[s:s + n] - north[s:s + n].mean()
        lam, vec = np.linalg.eigh(np.cov(e, w))
        az.append(np.degrees(np.arctan2(vec[0, 1], vec[1, 1])) % 180)
        var.append(lam.sum())
        ratio.append(lam[1] / max(lam[0], 1e-9))
    return np.array(az), np.array(var), np.array(ratio)


def session_heading(run_dir: Path) -> dict:
    acc = load_acc_dataframe(run_dir / "acc.csv")
    world = transform_to_world_frame(acc)
    ts = world["timestamp"].to_numpy(float)
    fs = 1000.0 / np.median(np.diff(ts))
    rot = Rotation.from_quat(acc[ROTATION_COLUMNS].to_numpy(float))
    dev_y = rot.apply([0.0, 1.0, 0.0])
    dev_z = rot.apply([0.0, 0.0, 1.0])
    heading = np.degrees(np.arctan2(dev_y[:, 0], dev_y[:, 1])) % 360
    east, north = world["accWorldX"].to_numpy(float), world["accWorldY"].to_numpy(float)
    az, var, ratio = principal_axis(east, north, fs)
    axis, conc = axial_mean(az, var)
    # 方位の中央値は、0/360° をまたぐ場合に備えて、単位ベクトルの平均の向きで出す
    hd = float(np.degrees(np.arctan2(np.mean(np.sin(np.radians(heading))), np.mean(np.cos(np.radians(heading))))) % 360)
    spread = np.abs((heading - hd + 180) % 360 - 180)
    return {"session": run_dir.name, "device_y_heading": hd, "heading_spread_p90": float(np.percentile(spread, 90)),
            "device_z_heading": float(np.degrees(np.arctan2(np.median(dev_z[:, 0]), np.median(dev_z[:, 1]))) % 360),
            "device_z_up": float(np.median(dev_z[:, 2])),
            "vib_axis": axis, "vib_axis_conc": conc, "vib_major_minor": float(np.median(ratio)),
            "_t": (ts - ts[0]) / 1000.0, "_heading": heading, "_az": az}


def plot_heading(rows: list[dict], labels: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
    for i, r in enumerate(rows):
        lab = labels.get(r["session"], "flat")
        color = {"flat": "#9e9e9e", "dansa": "#1f77b4", "dekobo": "#d62728"}[lab]
        day = "10.3" if r["session"].startswith("20261003") else "10.4"
        axes[0].plot(r["_t"][::50], r["_heading"][::50], ".", ms=2, color=color, alpha=0.6)
        axes[0].text(r["_t"][-1], r["device_y_heading"], r["session"][-6:], fontsize=7, color=color)
        axes[1].errorbar(i, r["vib_axis"], fmt="o" if day == "10.3" else "s", color=color, ms=7)
        axes[1].text(i, r["vib_axis"] + 5, f"{r['vib_axis_conc']:.2f}", ha="center", fontsize=7)
    axes[0].set_ylim(0, 360)
    axes[0].set_yticks([0, 90, 180, 270, 360], ["北 0", "東 90", "南 180", "西 270", "北 360"])
    axes[0].set_xlabel("時間 [s]")
    axes[0].set_title("スマホの y 軸の方位（計測中の変化）", fontsize=10)
    axes[1].set_xticks(range(len(rows)), [r["session"][4:] for r in rows], rotation=60, fontsize=7)
    axes[1].set_ylim(0, 180)
    axes[1].set_yticks([0, 45, 90, 135, 180], ["南北 0", "45", "東西 90", "135", "南北 180"])
    axes[1].set_title("水平の揺れの主な向き（○ 10.3、□ 10.4。数字は集中度）", fontsize=10)
    fig.suptitle("青 = step、赤 = rough、灰 = flat", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def extra_axes_factory(vib_axis: dict[str, float]):
    """build_run の extra_axes 用。水平の大きさ h、主軸 u・直交軸 v、x・y を θ 回転したもの。"""
    def extra(world: pd.DataFrame, session: str) -> dict[str, np.ndarray]:
        x, y = world["accWorldX"].to_numpy(float), world["accWorldY"].to_numpy(float)
        a = np.radians(vib_axis[session])  # 北から時計回り。単位ベクトルは (east, north) = (sin a, cos a)
        out = {"h": np.hypot(x, y), "u": x * np.sin(a) + y * np.cos(a), "v": x * np.cos(a) - y * np.sin(a)}
        for deg in ROTATE_DEG[1:]:
            t = np.radians(deg)
            out[f"rx{deg}"] = x * np.cos(t) - y * np.sin(t)
            out[f"ry{deg}"] = x * np.sin(t) + y * np.cos(t)
        return out
    return extra


def logo(df: pd.DataFrame, train_cols: list[str], test_cols: list[str], model) -> np.ndarray:
    """LOGO の予測。テスト側だけ別の列(回転した x・y)を、同じ並びで使う。"""
    pred = np.empty(len(df), dtype=object)
    groups = df["group"].to_numpy()
    for g in np.unique(groups):
        test = groups == g
        m = clone(model).fit(df.loc[~test, train_cols].to_numpy(), df["label"][~test])
        pred[test] = m.predict(df.loc[test, test_cols].to_numpy())
    return pred


def score(df: pd.DataFrame, train_cols: list[str], test_cols: list[str], model) -> dict:
    y = df["label"].to_numpy()
    pred = logo(df, train_cols, test_cols, model)
    r = summarize(y, pred)
    cm = confusion_matrix(y, pred, labels=LABELS)
    sr = df[df["label"] != "flat"]
    sr_pred = logo(sr, train_cols, test_cols, model)
    return {**r, "sr_bal_acc": balanced_accuracy_score(sr["label"], sr_pred),
            "n_step_to_rough": int(cm[1, 2]), "n_rough_to_step": int(cm[2, 1]), "n_step_to_flat": int(cm[1, 0])}


def main() -> None:
    parser = argparse.ArgumentParser()
    add_run_dir_args(parser)
    parser.add_argument("--windows", type=float, nargs="+", default=[2.0, 1.0])
    parser.add_argument("--output-dir", default="data/analysis/20261017_heading_dependence")
    args = parser.parse_args()

    run_dirs = resolve_run_dirs(args)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = [session_heading(d) for d in run_dirs]
    stats = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
    vib_axis = dict(zip(stats["session"], stats["vib_axis"]))

    result = []
    labels: dict[str, str] = {}
    extra = extra_axes_factory(vib_axis)
    for window_s in args.windows:
        df = pd.concat([build_run(d, window_s, 5, extra_axes=lambda w, s=d.name: extra(w, s)) for d in run_dirs],
                       ignore_index=True)
        labels.update(df.groupby("session")["label"].first().to_dict())
        print(f"\n=== 窓{window_s}s {dict(df['label'].value_counts())}", flush=True)
        sets = {"xyz18": cols("xyz", FEATS), "z6": cols("z", FEATS), "m6": cols("m", FEATS),
                "zh12": cols("zh", FEATS), "zuv18": cols("zuv", FEATS)}
        for name, c in sets.items():
            for model_name, model in models().items():
                r = score(df, c, c, model)
                result.append({"window_s": window_s, "features": name, "rotate_test_deg": 0, "model": model_name, **r})
                print(f"  {name:6s} {model_name:13s} bal={r['bal_acc']:.3f} sr={r['sr_bal_acc']:.3f} "
                      f"f/s/r={r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f}", flush=True)
        # 回転テスト: 学習は元の x・y、テストだけ x・y を θ 回転したもの
        base = cols("xyz", FEATS)
        for deg in ROTATE_DEG[1:]:
            rotated = [c.replace("x_", f"rx{deg}_", 1) if c.startswith("x_") else
                       c.replace("y_", f"ry{deg}_", 1) if c.startswith("y_") else c for c in base]
            for model_name, model in models().items():
                r = score(df, base, rotated, model)
                result.append({"window_s": window_s, "features": "xyz18", "rotate_test_deg": deg,
                               "model": model_name, **r})
                print(f"  xyz18 テストを{deg:3d}°回転 {model_name:13s} bal={r['bal_acc']:.3f} sr={r['sr_bal_acc']:.3f} "
                      f"f/s/r={r['r_flat']:.2f}/{r['r_step']:.2f}/{r['r_rough']:.2f}", flush=True)

    stats["label"] = stats["session"].map(lambda s: NAME[labels.get(s, "flat")])
    stats.to_csv(out / "heading_stats.csv", index=False)
    plot_heading(rows, labels, out / "heading_figure.png")
    pd.DataFrame(result).to_csv(out / "heading_eval.csv", index=False)
    pd.set_option("display.width", 250)
    print("\n", stats.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
