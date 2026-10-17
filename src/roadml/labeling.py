"""ボタンの区間と、窓のラベル付け(方針A)。

10.3 以降のデータは約 334Hz で、イベント(*_cont_start/stop)の elapsed_ms は acc.csv の elapsed と
基準時刻がずれる(アプリのグラフ描画スレッドの開始がセンサーの開始より遅い)。そのため、
壁時計の timestamp(ms)で窓とイベントの区間を突き合わせる。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

KINDS = ("dansa", "dekobo")
Interval = tuple[float, float]


def compute_overlap_ratio(
    *,
    window_start_ms: float,
    window_end_ms: float,
    intervals: list[Interval],
) -> float:
    window_duration = window_end_ms - window_start_ms
    if window_duration <= 0:
        raise ValueError("window_end_ms must be greater than window_start_ms")

    overlap_ms = 0.0
    for interval_start, interval_end in intervals:
        overlap_ms += max(
            0.0,
            min(window_end_ms, interval_end) - max(window_start_ms, interval_start),
        )

    return overlap_ms / window_duration


def build_intervals(run_dir: Path, pre_extension_ms: float) -> dict[str, list[Interval]]:
    """dansa/dekobo の start〜stop(通常・_cont とも)を timestamp_ms の区間にする。"""
    intervals: dict[str, list[Interval]] = {kind: [] for kind in KINDS}
    for kind in KINDS:
        path = run_dir / f"{kind}.csv"
        if not path.exists():
            continue
        events = pd.read_csv(path).sort_values("timestamp_ms")
        open_start: float | None = None
        for row in events.itertuples(index=False):
            name = str(row.event)
            if name.endswith("_start"):
                open_start = float(row.timestamp_ms)
            elif name.endswith("_stop") and open_start is not None:
                intervals[kind].append((open_start - pre_extension_ms, float(row.timestamp_ms)))
                open_start = None
    return intervals


def label_window(start_ms: float, end_ms: float, intervals, threshold: float) -> str:
    for kind in KINDS:  # 既存パイプライン同様、dansa を優先
        ratio = compute_overlap_ratio(
            window_start_ms=start_ms, window_end_ms=end_ms, intervals=intervals[kind]
        )
        if ratio >= threshold:
            return kind
    return "flat"
