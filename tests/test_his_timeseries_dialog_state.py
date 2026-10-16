from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.dialog_test_support import (
    FakeListWidget,
    FakeTextControl,
    load_dialog_module,
    new_widget_instance,
)
from tests.fixtures_qgis_fakes import FakeComboBox


pytestmark = pytest.mark.unit


@pytest.fixture
def dialog_module(monkeypatch):
    return load_dialog_module(
        monkeypatch,
        "his_timeseries_dialog.py",
        "his_timeseries_dialog_state",
    )


def _dialog(module):
    dialog = new_widget_instance(module.HisTimeseriesDialog)
    dialog._source_combo = FakeComboBox()
    dialog._scope_combo = FakeComboBox()
    dialog._variable_combo = FakeComboBox()
    dialog._selection_label = FakeTextControl()
    dialog._message_label = FakeTextControl()
    dialog._chart_widget = MagicMock()
    dialog._series_list = FakeListWidget()
    dialog._plotted_labels = []
    dialog._on_controls_changed = None
    dialog._on_plot_requested = None
    dialog._on_refresh_requested = None
    return dialog


def test_dialog_options_select_and_report_values(dialog_module):
    dialog = _dialog(dialog_module)
    dialog.set_source_options([("his", "History"), ("map", "Map")], "map")
    dialog.set_scope_options([("all", "All"), ("selected", "Selected")], "selected")
    dialog.set_variable_options([("waterlevel", "Water level")], "missing")

    assert dialog.selected_source() == "map"
    assert dialog.selected_scope() == "selected"
    assert dialog.selected_variable() == "waterlevel"
    assert dialog._variable_combo.currentText() == "Water level"

    dialog.set_source_options([])
    dialog.set_scope_options([])
    dialog.set_variable_options([])
    assert dialog.selected_source() is None
    assert dialog.selected_scope() is None
    assert dialog.selected_variable() is None


def test_dialog_message_series_append_and_clear_state(dialog_module):
    dialog = _dialog(dialog_module)
    dialog.set_message("Choose a selection.")
    assert dialog._message_label.text() == "Choose a selection."
    dialog._chart_widget.set_message.assert_called_once_with("Choose a selection.")

    first = [{"label": "Water level", "x": [0], "y": [1]}]
    second = [{"label": "Discharge", "x": [0], "y": [2]}]
    dialog.apply_series(first, "time", "level", "Results")

    assert dialog._plotted_labels == ["Water level"]
    assert dialog._series_list.items == ["Water level"]
    dialog._chart_widget.set_series.assert_called_once_with(
        first,
        "time",
        "level",
        "Results",
        append=False,
    )
    assert dialog._message_label.text() == ""

    dialog.apply_series(second, "time", "flow", "Results", append=True)
    assert dialog._plotted_labels == ["Water level", "Discharge"]
    assert dialog._series_list.items == ["Water level", "Discharge"]
    dialog._chart_widget.set_series.assert_called_with(
        second,
        "time",
        "flow",
        "Results",
        append=True,
    )

    dialog.set_message("Showing two series.")
    assert dialog._chart_widget.set_message.call_count == 1
    dialog.clear_plot()
    assert dialog._plotted_labels == []
    assert dialog._series_list.items == []
    dialog._chart_widget.clear_series.assert_called_once_with()


def test_dialog_handlers_and_selection_text(dialog_module):
    dialog = _dialog(dialog_module)
    controls_changed = MagicMock()
    plot_requested = MagicMock()
    refresh_requested = MagicMock()
    dialog.set_handlers(controls_changed, plot_requested, refresh_requested)

    dialog._emit_controls_changed()
    dialog._emit_plot_requested("add")
    dialog._emit_refresh_requested()
    dialog.set_selection_text(None)

    controls_changed.assert_called_once_with()
    plot_requested.assert_called_once_with("add")
    refresh_requested.assert_called_once_with()
    assert dialog._selection_label.text() == "Selection: none"

    dialog.set_handlers()
    dialog._emit_controls_changed()
    dialog._emit_plot_requested("new")
    dialog._emit_refresh_requested()


def test_widget_factories_and_qt_enum_compatibility(dialog_module, monkeypatch):
    fallback = object()
    monkeypatch.setattr(dialog_module, "_HAS_MATPLOTLIB", True)

    class UnavailableChart:
        def __init__(self, _parent):
            raise RuntimeError("Qt Matplotlib backend is unavailable")

    monkeypatch.setattr(dialog_module, "_MatplotlibSeriesChartWidget", UnavailableChart)
    monkeypatch.setattr(dialog_module, "_FallbackChartWidget", lambda parent: (parent, fallback))
    assert dialog_module._create_chart_widget("parent") == ("parent", fallback)

    monkeypatch.setattr(
        dialog_module,
        "Qt",
        SimpleNamespace(AlignmentFlag=SimpleNamespace(AlignCenter=7)),
    )
    assert dialog_module._qt_alignment_flag("AlignCenter") == 7

    monkeypatch.setattr(
        dialog_module,
        "QSizePolicy",
        SimpleNamespace(Policy=SimpleNamespace(Expanding=9)),
    )
    assert dialog_module._qsizepolicy_value("Expanding") == 9
