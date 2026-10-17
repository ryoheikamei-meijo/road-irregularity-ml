"""flat / step / rough の代表セッションの world 加速度波形を、同じ縦軸で並べて描く(軸ごとに1枚)。

event 区間(*_start〜*_stop)は薄く塗る。flat セッションには区間が無い。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.roadml.labeling import build_intervals
from src.roadml.io import load_acc_dataframe
from src.roadml.io import transform_to_world_frame
from src.roadml.io import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flat", required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("--rough", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--width", type=float, default=40.0)
    args = parser.parse_args()

    sessions = [("flat", Path(args.flat)), ("step", Path(args.step)), ("rough", Path(args.rough))]
    worlds = {
        name: transform_to_world_frame(load_acc_dataframe(path / "acc.csv"))
        for name, path in sessions
    }
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for axis_key in ("x", "y", "z"):
        offset = GRAVITY_MPS2 if axis_key == "z" else 0.0
        values = {n: w[f"accWorld{axis_key.upper()}"] - offset for n, w in worlds.items()}
        limit = max(float(abs(v).max()) for v in values.values()) * 1.05
        fig, axes = plt.subplots(3, 1, figsize=(args.width, 9), sharey=True)
        for ax, (name, path) in zip(axes, sessions, strict=True):
            world = worlds[name]
            t0 = world["timestamp"].iloc[0]
            seconds = (world["timestamp"] - t0) / 1000.0
            ax.plot(seconds, values[name], linewidth=0.4, color="tab:blue")
            for kind, intervals in build_intervals(path, 0.0).items():
                for start, end in intervals:
                    ax.axvspan((start - t0) / 1000.0, (end - t0) / 1000.0, color="tab:red", alpha=0.10)
            ax.axhline(0, color="gray", linewidth=0.5)
            ax.set_ylim(-limit, limit)
            ax.set_xlim(0, seconds.iloc[-1])
            ax.set_ylabel(f"{name}\n[m/s²]")
            ax.set_title(f"{name}: {path.name}   std={values[name].std():.2f}  |max|={abs(values[name]).max():.1f}", loc="left", fontsize=10)
            ax.grid(alpha=0.3)
        axes[-1].set_xlabel("時間 [s]  (赤の塗り = event 区間)")
        fig.suptitle(f"world {axis_key} 加速度" + ("(重力除去)" if axis_key == "z" else "") + " の比較(縦軸共通)")
        fig.tight_layout()
        fig.savefig(out / f"comparison_{axis_key}.png", dpi=100)
        plt.close(fig)
        print({n: round(float(v.std()), 2) for n, v in values.items()}, axis_key)


if __name__ == "__main__":
    main()
