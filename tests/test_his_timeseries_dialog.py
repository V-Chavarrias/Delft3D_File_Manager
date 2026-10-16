from unittest.mock import MagicMock

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
from matplotlib.figure import Figure  # noqa: E402

from Delft3DFileManager import his_timeseries_dialog as module  # noqa: E402


def _chart():
    chart = module._MatplotlibSeriesChartWidget.__new__(
        module._MatplotlibSeriesChartWidget
    )
    chart._figure = Figure()
    chart._axes = chart._figure.add_subplot(111)
    chart._series = []
    chart._x_axis_label = "time"
    chart._y_axis_label = "value"
    chart._title = "HIS Time Series"
    chart._message = ""
    chart.draw_idle = MagicMock()
    return chart


def test_chart_replaces_and_appends_series():
    chart = _chart()
    chart.set_series(
        [{"x": [0, 1], "y": [2, 3], "label": "first"}],
        "time",
        "level",
        "Levels",
    )
    chart.set_series(
        [{"x": [0, 1], "y": [4, 5], "label": "second"}],
        "time",
        "level",
        "Levels",
        append=True,
    )

    assert [entry["label"] for entry in chart._series] == ["first", "second"]
    assert chart._axes.get_xlabel() == "time"
    assert chart._axes.get_ylabel() == "level"
    assert len(chart._axes.lines) == 2


def test_chart_clear_series_displays_message():
    chart = _chart()
    chart.set_series([{"x": [0], "y": [1], "label": "series"}], "x", "y", "title")
    chart.clear_series()

    assert chart._series == []
    assert chart._axes.texts[0].get_text() == "No series plotted."

