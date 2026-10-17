"""1セッションの world 座標の加速度(z は重力除去)と速度を、横長の1枚に描く。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.visualization.world_frame import load_acc_dataframe
from src.visualization.world_frame import transform_to_world_frame
from src.wheelchair_pipeline import GRAVITY_MPS2

plt.rcParams["font.family"] = "Hiragino Sans"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--axis", choices=("x", "y", "z"), default="z")
    parser.add_argument("--width", type=float, default=48.0, help="図の横幅[inch]")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    world = transform_to_world_frame(load_acc_dataframe(run_dir / "acc.csv"))
    seconds = (world["timestamp"] - world["timestamp"].iloc[0]) / 1000.0
    # x/y は水平方向のため重力補正なし(既存パイプラインと同じ)
    z = world[f"accWorld{args.axis.upper()}"] - (GRAVITY_MPS2 if args.axis == "z" else 0.0)

    fig, (ax_z, ax_v) = plt.subplots(
        2, 1, figsize=(args.width, 7), sharex=True, gridspec_kw={"height_ratios": [4, 1]}
    )
    ax_z.plot(seconds, z, linewidth=0.5, color="tab:blue")
    ax_z.axhline(0, color="gray", linewidth=0.6)
    ax_z.set_ylabel(f"world {args.axis} 加速度" + ("(重力除去)" if args.axis == "z" else "") + " [m/s²]")
    ax_z.grid(alpha=0.3)
    ax_v.plot(seconds, world["speedMps"], linewidth=0.8, color="tab:green")
    ax_v.set_ylabel("速度 [m/s]")
    ax_v.set_xlabel("時間 [s]")
    ax_v.grid(alpha=0.3)
    ax_v.set_xlim(0, seconds.iloc[-1])
    ax_v.set_xticks(range(0, int(seconds.iloc[-1]) + 1, 5))
    fig.suptitle(f"{run_dir.name}  {args.axis}軸波形 (n={len(z)}, {seconds.iloc[-1]:.1f}s)")
    fig.tight_layout()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=100)
    print(f"z range: {z.min():.1f} .. {z.max():.1f}, std {z.std():.2f}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
