"""スマホ固定位置(後ろ/前)だけが違う同種セッションの world 加速度波形を、上下に並べて描く。

上段が後ろ固定(デフォルト)、下段が前固定。縦軸は共通。event 区間は薄く塗る。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.roadml.labeling import build_intervals
from src.roadml.io import load_acc_dataframe
from src.roadml.io import transform_to_world_frame
from src.roadml.io import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"

PAIRS = {
    "step": ("20261004170739", "20261004171104"),
    "rough": ("20261004171557", "20261004171723"),
}


def load_axis(run_dir: Path, axis_key: str) -> tuple[pd.Series, pd.Series, float]:
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    t0 = float(world["timestamp"].iloc[0])
    seconds = (world["timestamp"] - t0) / 1000.0
    offset = GRAVITY_MPS2 if axis_key == "z" else 0.0
    return seconds, world[f"accWorld{axis_key.upper()}"] - offset, t0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="10.4 のディレクトリ")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--width", type=float, default=40.0)
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind, (rear, front) in PAIRS.items():
        runs = [("後ろ固定", Path(args.data_dir) / rear), ("前固定", Path(args.data_dir) / front)]
        for axis_key in ("x", "y", "z"):
            data = {label: load_axis(path, axis_key) for label, path in runs}
            limit = max(float(abs(v).max()) for _, v, _ in data.values()) * 1.05
            fig, axes = plt.subplots(2, 1, figsize=(args.width, 6.5), sharey=True)
            for ax, (label, path) in zip(axes, runs, strict=True):
                seconds, values, t0 = data[label]
                ax.plot(seconds, values, linewidth=0.4, color="tab:blue" if label == "後ろ固定" else "tab:orange")
                for intervals in build_intervals(path, 0.0).values():
                    for start, end in intervals:
                        ax.axvspan((start - t0) / 1000.0, (end - t0) / 1000.0, color="tab:red", alpha=0.10)
                ax.axhline(0, color="gray", linewidth=0.5)
                ax.set_ylim(-limit, limit)
                ax.set_xlim(0, seconds.iloc[-1])
                ax.set_ylabel(f"{label}\n[m/s²]")
                ax.set_title(f"{label}: {path.name}   std={values.std():.2f}  |max|={abs(values).max():.1f}", loc="left", fontsize=10)
                ax.grid(alpha=0.3)
                rows.append({"kind": kind, "axis": axis_key, "position": label, "session": path.name,
                             "std": values.std(), "rms": (values**2).mean() ** 0.5,
                             "abs_max": abs(values).max(), "p99_abs": values.abs().quantile(0.99)})
            axes[-1].set_xlabel("時間 [s]  (赤の塗り = event 区間)")
            fig.suptitle(f"{kind}: world {axis_key} 加速度" + ("(重力除去)" if axis_key == "z" else "") + " 後ろ vs 前(縦軸共通)")
            fig.tight_layout()
            fig.savefig(out / f"rear_vs_front_{kind}_{axis_key}.png", dpi=100)
            plt.close(fig)
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "rear_vs_front_summary.csv", index=False)
    print(summary.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
