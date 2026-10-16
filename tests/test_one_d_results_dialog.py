from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
from matplotlib.figure import Figure  # noqa: E402

from Delft3DFileManager import one_d_results_dialog as module  # noqa: E402


def _chart():
    chart = module._ResultsChartWidget.__new__(module._ResultsChartWidget)
    chart._figure = Figure()
    chart._axes = chart._figure.add_subplot(111)
    chart._message = ""
    chart._colorbars = []
    chart._x_label = ""
    chart._x_is_datetime = False
    chart._x_position_callback = None
    chart._figure_position_callback = None
    chart.draw_idle = MagicMock()
    return chart


def test_chart_motion_reports_numeric_x_position_and_figure_position():
    chart = _chart()
    chart._x_label = " (distance)"
    text_callback = MagicMock()
    figure_callback = MagicMock()
    chart.set_x_position_callback(text_callback)
    chart.set_figure_position_callback(figure_callback)

    chart._on_motion(
        SimpleNamespace(inaxes=chart._axes, xdata=12.5)
    )

    text_callback.assert_called_once_with("x = 12.5 (distance)")
    figure_callback.assert_called_once_with(12.5, False)


def test_chart_heatmap_tracks_and_removes_colorbar():
    chart = _chart()
    chart.set_plot(
        {
            "plot_type": "heatmap",
            "values": [[1, 2], [3, 4]],
            "extent": [0, 2, 0, 2],
            "title": "Distance-time",
            "colorbar_label": "depth",
        }
    )

    assert len(chart._colorbars) == 1
    assert chart._axes.get_title() == "Distance-time"
    chart.clear_plot()
    assert chart._colorbars == []
    assert not chart._axes.images

