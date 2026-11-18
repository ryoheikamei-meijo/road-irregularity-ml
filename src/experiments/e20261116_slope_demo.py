"""デモ: 平らな道から長い坂に入ったとき、判定モデル(v2_20261117)がどう判定するか。

坂道の実データは無いので、flat のセッション(実データ)の途中で、スマホの姿勢だけを傾けて「坂に入った」ことにする。
  - 姿勢(rotation vector)に、端末から見た軸まわりの回転(坂の角度)を足す(坂をまっすぐ上る想定)。加速度は、世界座標系で見た値が元と同じになるように
    端末座標に戻す。つまり z・h(揺れ)は元のまま、傾き(tilt)だけが坂の分だけ変わる
  - 坂への入り方: ENTER_S 秒で、移る時間(ramp)をかけて角度を 0 → 坂の角度にし、EXIT_S 秒で同じように 0 に戻す
限界: 実際の坂では、入り口でキャスターがぶつかる揺れや、速さの変化、坂の上での揺れの向きの変化もある。ここでは傾きだけを見る。
flat のセッションは学習に使っているので、元のデータではほとんど flat になる(比べる基準として使う)。

出力: data/analysis/20261116_slope_demo/(summary.csv、timeline.png)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import onnxruntime as ort
import pandas as pd
from scipy.spatial.transform import Rotation

from src.roadml.core_model import CORE
from src.roadml.core_model import core_features
from src.roadml.core_model import load_raw
from src.roadml.core_model import signals

plt.rcParams["font.family"] = "Hiragino Sans"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261116_slope_demo"
MODEL = ROOT / "apps/detector-android/models/v2_20261117/core_svm.onnx"
TILT_REF = "mean30"  # v2_20261117 と同じ
SESSION, DAY = "20261031150048", "10.31"  # flat、約 138 秒
ENTER_S, EXIT_S = 40.0, 100.0
SLOPES = {"1/12（4.8 度）": np.degrees(np.arctan(1 / 12)), "1/20（2.9 度）": np.degrees(np.arctan(1 / 20))}
RAMPS_S = [0.5, 1.0, 2.0]
NAME = {"flat": "flat", "dansa": "step", "dekobo": "rough"}


def with_slope(raw: dict, deg: float, ramp_s: float) -> dict:
    t = (raw["ts"] - raw["ts"][0]) / 1000.0
    angle = deg * np.clip((t - ENTER_S) / ramp_s, 0, 1) * np.clip((EXIT_S + ramp_s - t) / ramp_s, 0, 1)
    rot = Rotation.from_quat(raw["quat"])
    world = rot.apply(raw["acc"])
    # 車椅子(端末)から見た軸まわりに傾ける。向きを変えても、車椅子から見て同じだけ傾いている(坂をまっすぐ上る)ことにする。
    # 地面に固定した軸で傾けると、元のセッションで向きを変えるたびに傾きの向きも変わってしまう(坂の上で曲がるのと同じ)
    tilted = rot * Rotation.from_rotvec(np.radians(angle)[:, None] * np.array([1.0, 0.0, 0.0]))
    return {"ts": raw["ts"], "acc": tilted.inv().apply(world), "quat": tilted.as_quat(), "angle": angle}


def judge(raw: dict, sess: ort.InferenceSession) -> pd.DataFrame:
    f = core_features(signals(raw, TILT_REF), 2.0, TILT_REF)
    f["pred"] = sess.run(None, {"features": f[CORE].to_numpy(np.float32)})[0]
    f["t_mid"] = (f["start_ms"] - raw["ts"][0]) / 1000.0 + 1.0  # 窓の中心の時刻
    return f


def phase(t_mid: float, ramp_s: float) -> str:
    if abs(t_mid - (ENTER_S + ramp_s / 2)) <= 1.0 + ramp_s / 2 + 0.01:
        return "入り口"
    if abs(t_mid - (EXIT_S + ramp_s / 2)) <= 1.0 + ramp_s / 2 + 0.01:
        return "出口"
    if ENTER_S < t_mid < EXIT_S:
        return "坂の途中"
    return "平らな所"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    raw = load_raw(ROOT / "wheelchair_data" / DAY / SESSION)
    base = judge(raw, sess)
    rows, curves = [], {}
    for slope, deg in SLOPES.items():
        for ramp in RAMPS_S:
            mod = with_slope(raw, deg, ramp)
            res = judge(mod, sess)
            assert np.allclose(res[["z_rms", "z_kurt", "h_std", "h_crest"]], base[["z_rms", "z_kurt", "h_std", "h_crest"]])
            res["phase"] = [phase(x, ramp) for x in res["t_mid"]]
            res["base_pred"] = base["pred"].to_numpy()
            for ph, g in res.groupby("phase"):
                rows.append({"slope": slope, "ramp_s": ramp, "phase": ph, "n": len(g),
                             **{NAME[k]: int((g["pred"] == k).sum()) for k in NAME},
                             "base_not_flat": int((g["base_pred"] != "flat").sum()),
                             "tilt_range_max": round(float(g["tilt_range"].max()), 2),
                             "tilt_range_median": round(float(g["tilt_range"].median()), 2)})
            curves[(slope, ramp)] = (mod, res)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "summary.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"元の flat のデータ: {base['pred'].map(NAME).value_counts().to_dict()}  tilt_range の中央値 {base['tilt_range'].median():.2f} 度")
    print(df.to_string(index=False))

    # 図: 1/12・移る時間 1 秒
    mod, res = curves[("1/12（4.8 度）", 1.0)]
    t = (raw["ts"] - raw["ts"][0]) / 1000.0
    fig, (a0, a1, a2) = plt.subplots(3, 1, figsize=(11, 6.2), sharex=True, gridspec_kw={"height_ratios": [1, 1, 0.5]})
    a0.plot(t, mod["angle"], color="#52514e", lw=1.2, label="足した坂の角度")
    a0.plot(t, signals(mod, TILT_REF)["tilt"], color="#eb6834", lw=0.6, label="測る傾き（基準からのずれ）")
    a0.set_ylabel("角度 [度]")
    a0.legend(loc="upper right", frameon=False, fontsize=9)
    a0.set_title("デモ：flat の実データに、1/12 の坂（4.8 度、1 秒で入る）を足したときの判定", fontsize=11)
    a1.plot(res["t_mid"], res["tilt_range"], color="#eb6834", lw=1.2, marker="o", ms=2.5)
    a1.axhline(7.0, color="#52514e", lw=0.8, ls=":")
    a1.text(1, 7.2, "段差の tilt_range の中央値（約 7 度）", fontsize=8, color="#52514e")
    a1.set_ylabel("tilt_range [度]")
    color = {"flat": "#2a78d6", "dansa": "#eb6834", "dekobo": "#1baf7a"}
    for x, p in zip(res["t_mid"], res["pred"]):
        a2.barh(0, 0.5, left=x - 0.25, height=0.8, color=color[p], lw=0)
    a2.set_yticks([0], ["判定"])
    a2.set_xlabel("時間 [s]")
    from matplotlib.patches import Patch
    a2.legend(handles=[Patch(color=color[k], label=NAME[k]) for k in color], ncol=3, frameon=False,
              loc="upper center", bbox_to_anchor=(0.5, -0.9), fontsize=9)
    for ax in (a0, a1, a2):
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "timeline.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
