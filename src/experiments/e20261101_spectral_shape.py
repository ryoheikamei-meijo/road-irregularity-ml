"""平坦路の揺れの「形」(周波数ごとの割合)は、路面より車椅子で決まるかを調べる(10.31 + 10.4)。

平坦路を基準にした補正で、基準から「大きさ」まで割ると、基準の路面の粗さに左右される
(docs/knowledge/2026-10-31/20261031_speed_weight_normalization_survey.md の 4 章)。
「形」だけで補正するには、形が路面ではなく車椅子(と人)で決まる必要がある。それを確かめる。

基準になりうる平坦路(z、世界座標系の鉛直):
  汎用: flat ②(20261031152608)、flat ①(20261031150048)、段差の手前の走行、凸凹の手前の走行
  従来: 10.4 の flat(20261004172306)、段差の手前の走行、凸凹の手前の走行
  手前の走行 = 各通過の START から 0.2〜0.9 秒(e20261031_chair_normalization と同じ)
形 = パワースペクトルを全体の和で割ったもの(dB)。大きさ = rms。
2 つの基準の形の違い = 帯域ごとの dB の差の絶対値の平均。

出力(data/analysis/20261101_spectral_shape/): references.csv、shape_distance.csv、shapes.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import welch

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261031_chair_normalization import BANDS_HZ
from src.experiments.e20261031_chair_normalization import NPERSEG
from src.experiments.e20261031_chair_normalization import calibration_psd
from src.experiments.e20261031_chair_normalization import segments

plt.rcParams["font.family"] = "Hiragino Sans"
ROOT = Path(__file__).resolve().parents[2]
D31 = "wheelchair_data/10.31/"
# (名前, 車椅子, 種類, セッション, 区間) 区間は (開始[s], 終了[s]) か "approach"(手前の走行)
REFERENCES = [
    ("汎用 flat ②", "standard", "flat", [D31 + "20261031152608"], (10.0, 25.0)),
    ("汎用 flat ①", "standard", "flat", [D31 + "20261031150048"], (10.0, 25.0)),
    ("汎用 段差の手前", "standard", "approach",
     [D31 + s for s in ("20261031142102", "20261031144423", "20261031145759", "20261031152930")], "approach"),
    ("汎用 凸凹の手前", "standard", "approach", [D31 + s for s in ("20261031143004", "20261031145017")], "approach"),
    ("従来 flat 10.4", "original", "flat", ["wheelchair_data/10.4/20261004172306"], (10.0, 25.0)),
    ("従来 段差の手前", "original", "approach",
     [D31 + s for s in ("20261031142344", "20261031142508", "20261031144130")], "approach"),
    ("従来 凸凹の手前", "original", "approach", [D31 + s for s in ("20261031142814", "20261031145240")], "approach"),
]


def reference_signal(paths: list[str], span) -> tuple[list[np.ndarray], float]:
    segs, fs = [], None
    for path in paths:
        sess = load_session(ROOT / path)
        fs = sess["fs"]
        ts = sess["ts"]
        if span == "approach":
            passes = load_passes(ROOT / path)
            mask = np.zeros(len(ts), bool)
            for start in passes.loc[~passes["cancelled"], "start_ms"]:
                mask |= (ts >= start + 200) & (ts < start + 900)
        else:
            t = (ts - ts[0]) / 1000.0
            mask = (t >= span[0]) & (t < span[1])
        segs += [sess["axes"]["z"][s] for s in segments(mask)]
    return segs, fs


def main() -> None:
    out = ROOT / "data/analysis/20261101_spectral_shape"
    out.mkdir(parents=True, exist_ok=True)
    rows, shapes = [], {}
    for name, chair, kind, paths, span in REFERENCES:
        segs, fs = reference_signal(paths, span)
        f, p = calibration_psd(segs, fs)
        band = np.array([p[(f >= lo) & (f < hi)].mean() for lo, hi in BANDS_HZ])
        shape_db = 10 * np.log10(band / band.sum())
        shapes[name] = (f, p / p.sum(), shape_db)
        rms = float(np.sqrt(np.mean(np.concatenate(segs) ** 2)))
        rows.append({"name": name, "wheelchair": chair, "kind": kind, "seconds": sum(map(len, segs)) / fs,
                     "z_rms": rms, **{f"shape_{lo:g}_{hi:g}_db": v for (lo, hi), v in zip(BANDS_HZ, shape_db)}})
    ref = pd.DataFrame(rows)
    ref.to_csv(out / "references.csv", index=False)

    dist = []
    names = list(shapes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ca, cb = ref.set_index("name").loc[[a, b], "wheelchair"]
            dist.append({"a": a, "b": b, "same_chair": ca == cb,
                         "shape_diff_db": float(np.mean(np.abs(shapes[a][2] - shapes[b][2]))),
                         "rms_ratio": float(ref.set_index("name").loc[a, "z_rms"] / ref.set_index("name").loc[b, "z_rms"])})
    dist = pd.DataFrame(dist)
    dist.to_csv(out / "shape_distance.csv", index=False)

    pd.set_option("display.width", 220)
    print(ref.round(2).to_string(index=False))
    print(dist.round(2).sort_values(["same_chair", "shape_diff_db"]).to_string(index=False))
    print("形の違い [dB] の平均: 同じ車椅子 {:.2f}、違う車椅子 {:.2f}".format(
        dist.loc[dist["same_chair"], "shape_diff_db"].mean(), dist.loc[~dist["same_chair"], "shape_diff_db"].mean()))

    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    for name, (f, p_norm, _) in shapes.items():
        style = "-" if name.startswith("汎用") else "--"
        axes[0].semilogy(f, p_norm, style, label=name)
    axes[0].set_xlim(0, 167)
    axes[0].set_xlabel("周波数 [Hz]")
    axes[0].set_title("揺れの形（パワースペクトル ÷ 全体の和）。実線 汎用、破線 従来")
    axes[0].legend(fontsize=8)
    x = np.arange(len(BANDS_HZ))
    for name, (_, _, shape_db) in shapes.items():
        axes[1].plot(x, shape_db, "o-" if name.startswith("汎用") else "s--", label=name)
    axes[1].set_xticks(x, [f"{lo:g}-{hi:g}" for lo, hi in BANDS_HZ])
    axes[1].set_xlabel("帯域 [Hz]")
    axes[1].set_ylabel("全体に占める割合 [dB]")
    axes[1].set_title("帯域ごとの形")
    fig.tight_layout()
    fig.savefig(out / "shapes.png", dpi=110)


if __name__ == "__main__":
    main()
