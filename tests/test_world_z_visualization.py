from __future__ import annotations

import pandas as pd
import pytest

from src.roadml.visualization.world_z import EVENT_SHADE_ALPHA
from src.roadml.visualization.world_z import add_event_lines
from src.roadml.visualization.world_z import add_event_spans
from src.roadml.visualization.world_z import iter_event_intervals


def test_iter_event_intervals_ignores_during_and_unmatched_events() -> None:
    event_df = pd.DataFrame(
        {
            "elapsed_ms": [100.0, 150.0, 400.0, 800.0],
            "event": [
                "dansa_start",
                "dansa_during",
                "dansa_stop",
                "dansa_start",
            ],
        }
    )

    intervals = list(
        iter_event_intervals(
            event_df,
            start_event="dansa_start",
            stop_event="dansa_stop",
        )
    )

    assert intervals == [(0.1, 0.4)]


def test_add_event_spans_shades_complete_interval() -> None:
    from matplotlib import pyplot as plt

    event_df = pd.DataFrame(
        {
            "elapsed_ms": [100.0, 400.0],
            "event": ["dansa_start", "dansa_stop"],
        }
    )
    _, axis = plt.subplots()

    add_event_spans(axis, [event_df])

    assert len(axis.patches) == 1
    assert axis.patches[0].get_alpha() == pytest.approx(EVENT_SHADE_ALPHA)
    plt.close(axis.figure)


def test_add_event_lines_can_describe_boundary_line_styles() -> None:
    from matplotlib import pyplot as plt

    event_df = pd.DataFrame(
        {
            "elapsed_ms": [100.0, 400.0],
            "event": ["dekobo_start", "dekobo_stop"],
        }
    )
    _, axis = plt.subplots()

    add_event_lines(axis, [event_df], describe_boundaries=True)

    legend = axis.get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == [
        "開始",
        "終了",
    ]
    plt.close(axis.figure)
