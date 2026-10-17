"""World-frame vertical acceleration waveform plotting."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

EVENT_STYLES = {
    "dansa_start":  ("tab:red",  "--", "step_start"),
    "dansa_stop":   ("tab:red",  "-",  "step_stop"),
    "dekobo_start": ("magenta", "--", "rough_start"),
    "dekobo_stop":  ("magenta", "-",  "rough_stop"),
}
EVENT_INTERVAL_STYLES = {
    "step": ("dansa_start", "dansa_stop", "tab:red"),
    "rough": ("dekobo_start", "dekobo_stop", "magenta"),
}
EVENT_SHADE_ALPHA = 0.08
# スライドに貼る実寸（inch）に figsize を合わせることで、
# 以下の pt 指定がスライド上でもそのままの見た目になる。
CROP_FIGSIZE = (10.6, 3.71)
CROP_DPI = 200
CROP_LINEWIDTH = 1.6
CROP_EVENT_LINEWIDTH = 1.6
CROP_TITLE_FONTSIZE = 13
CROP_LABEL_FONTSIZE = 12
CROP_TICK_FONTSIZE = 11
CROP_LEGEND_FONTSIZE = 11
JAPANESE_FONT_CANDIDATES = (
    "Hiragino Sans",
    "YuGothic",
    "Noto Sans CJK JP",
    "IPAexGothic",
    "IPAGothic",
)


def find_japanese_font_family() -> str:
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    return next(
        (font for font in JAPANESE_FONT_CANDIDATES if font in available_fonts),
        "sans-serif",
    )


def load_world_dataframe(path: Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    for col in ("elapsed", "accWorldZ"):
        if col not in dataframe.columns:
            raise ValueError(f"Missing required column '{col}' in {path}")
    return dataframe


def load_event_dataframe(path: Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    for col in ("elapsed_ms", "event"):
        if col not in dataframe.columns:
            raise ValueError(f"Missing required column '{col}' in {path}")
    return dataframe


def build_event_frames(raw_run_dir: Path) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for filename in ("dansa.csv", "dekobo.csv"):
        path = raw_run_dir / filename
        if path.exists():
            frames.append(load_event_dataframe(path))
    return frames


def load_weight_kg(raw_run_dir: Path) -> float | None:
    result_path = raw_run_dir / "session_result.csv"
    if not result_path.exists():
        return None
    dataframe = pd.read_csv(result_path)
    if "weight_kg" not in dataframe.columns or dataframe.empty:
        return None
    value = dataframe["weight_kg"].iloc[0]
    return None if pd.isna(value) else float(value)


def iter_event_intervals(
    event_df: pd.DataFrame,
    *,
    start_event: str,
    stop_event: str,
):
    """Yield complete start/stop intervals in elapsed seconds."""
    events = event_df[event_df["event"].isin((start_event, stop_event))]
    events = events.sort_values("elapsed_ms")
    start_seconds: float | None = None

    for row in events.itertuples(index=False):
        event_name = str(row.event)
        event_seconds = float(row.elapsed_ms) / 1000.0
        if event_name == start_event:
            start_seconds = event_seconds
        elif start_seconds is not None and event_seconds > start_seconds:
            yield start_seconds, event_seconds
            start_seconds = None


def add_event_spans(axis, event_frames: list[pd.DataFrame]) -> None:
    for event_df in event_frames:
        for start_event, stop_event, color in EVENT_INTERVAL_STYLES.values():
            for start_seconds, stop_seconds in iter_event_intervals(
                event_df,
                start_event=start_event,
                stop_event=stop_event,
            ):
                axis.axvspan(
                    start_seconds,
                    stop_seconds,
                    color=color,
                    alpha=EVENT_SHADE_ALPHA,
                    linewidth=0,
                    zorder=0.5,
                )


def add_event_lines(
    axis,
    event_frames: list[pd.DataFrame],
    *,
    show_legend: bool = True,
    describe_boundaries: bool = False,
    legend_fontsize: float | None = None,
    linewidth: float = 1.0,
) -> None:
    labeled: set[str] = set()
    for event_df in event_frames:
        for row in event_df.itertuples(index=False):
            event_name = str(row.event)
            if event_name.endswith("_during"):
                continue
            if event_name not in EVENT_STYLES:
                continue
            color, linestyle, display_label = EVENT_STYLES[event_name]
            event_seconds = float(row.elapsed_ms) / 1000.0
            if describe_boundaries:
                display_label = (
                    "開始"
                    if event_name.endswith("_start")
                    else "終了"
                )
            label = display_label if event_name not in labeled else None
            axis.axvline(
                event_seconds,
                color=color,
                linestyle=linestyle,
                linewidth=linewidth,
                alpha=0.8,
                label=label,
            )
            labeled.add(event_name)
    if labeled and show_legend:
        legend_options = {"loc": "upper right"}
        if describe_boundaries:
            legend_options["prop"] = {"family": find_japanese_font_family()}
        if legend_fontsize is not None:
            legend_options.setdefault("prop", {})["size"] = legend_fontsize
        axis.legend(**legend_options)


def plot_world_z(
    run_name: str,
    world_df: pd.DataFrame,
    raw_run_dir: Path,
    output_dir: Path,
) -> Path:
    event_frames = build_event_frames(raw_run_dir)
    elapsed_seconds = world_df["elapsed"].to_numpy(dtype=float) / 1000.0

    figure, axis = plt.subplots(figsize=(14, 4), constrained_layout=True)

    axis.plot(elapsed_seconds, world_df["accWorldZ"], linewidth=1.0)
    axis.set_ylabel("world_z [m/s²]")
    axis.set_xlabel("elapsed [s]")
    axis.grid(True, alpha=0.3)

    add_event_spans(axis, event_frames)
    add_event_lines(axis, event_frames)

    weight_kg = load_weight_kg(raw_run_dir)
    title = (
        f"{run_name} world-z"
        if weight_kg is None
        else f"{run_name} world-z ({weight_kg:g}kg)"
    )
    filename_suffix = "" if weight_kg is None else f"_{weight_kg:g}kg"
    figure.suptitle(title)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_name}{filename_suffix}_world_z_plot.png"
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def plot_world_z_event_crop(
    run_name: str,
    world_df: pd.DataFrame,
    raw_run_dir: Path,
    output_dir: Path,
    *,
    event_kind: str,
    xlim: tuple[float, float],
) -> Path:
    """Plot a presentation crop without changing the underlying waveform."""
    if event_kind not in EVENT_INTERVAL_STYLES:
        choices = ", ".join(EVENT_INTERVAL_STYLES)
        raise ValueError(f"Unknown event kind '{event_kind}'; expected one of: {choices}")
    if xlim[0] >= xlim[1]:
        raise ValueError("Crop start must be earlier than crop stop")

    event_filename = "dansa.csv" if event_kind == "step" else "dekobo.csv"
    event_path = raw_run_dir / event_filename
    event_frames = [load_event_dataframe(event_path)] if event_path.exists() else []
    elapsed_seconds = world_df["elapsed"].to_numpy(dtype=float) / 1000.0

    figure, axis = plt.subplots(figsize=CROP_FIGSIZE, constrained_layout=True)
    axis.plot(elapsed_seconds, world_df["accWorldZ"], linewidth=CROP_LINEWIDTH)
    axis.set_xlim(xlim)
    axis.set_ylabel("world_z [m/s²]", fontsize=CROP_LABEL_FONTSIZE)
    axis.set_xlabel("elapsed [s]", fontsize=CROP_LABEL_FONTSIZE)
    axis.tick_params(axis="both", labelsize=CROP_TICK_FONTSIZE)
    axis.grid(True, alpha=0.3)
    add_event_spans(axis, event_frames)
    add_event_lines(
        axis,
        event_frames,
        describe_boundaries=True,
        legend_fontsize=CROP_LEGEND_FONTSIZE,
        linewidth=CROP_EVENT_LINEWIDTH,
    )
    axis.set_title(
        f"{run_name}  {event_kind} events",
        fontsize=CROP_TITLE_FONTSIZE,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_name}_{event_kind}_crop.png"
    figure.savefig(output_path, dpi=CROP_DPI)
    plt.close(figure)
    return output_path


def iter_world_csv_dirs(world_csv_dir: Path) -> list[tuple[str, Path]]:
    """world_csv_dir/<run_name>/acc_world.csv を列挙する。"""
    results = []
    for subdir in sorted(world_csv_dir.iterdir()):
        if not subdir.is_dir():
            continue
        csv_path = subdir / "acc_world.csv"
        if csv_path.exists():
            results.append((subdir.name, csv_path))
    return results
