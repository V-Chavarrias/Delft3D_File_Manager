from unittest.mock import MagicMock

import pytest

from tests.dialog_test_support import (
    FakeTextControl,
    FakeToggleButton,
    load_dialog_module,
    new_widget_instance,
)
from tests.fixtures_qgis_fakes import FakeComboBox


pytestmark = pytest.mark.unit


@pytest.fixture
def dialog_module(monkeypatch):
    return load_dialog_module(
        monkeypatch,
        "one_d_results_dialog.py",
        "one_d_results_dialog_state",
    )


def _dialog(module):
    dialog = new_widget_instance(module.OneDResultsDialog)
    dialog._point_button = FakeToggleButton(checked=True)
    dialog._track_button = FakeToggleButton()
    dialog._variable_combo = FakeComboBox()
    dialog._time_combo = FakeComboBox()
    dialog._time_expression = FakeTextControl("  1:4, 8  ")
    dialog._plot_type_combo = FakeComboBox()
    dialog._plot_type_combo.addItem("Distance lines", "lines")
    dialog._plot_type_combo.addItem("Distance-time heatmap", "heatmap")
    dialog._source_label = FakeTextControl()
    dialog._selection_label = FakeTextControl()
    dialog._coordinate_label = FakeTextControl()
    dialog._message_label = FakeTextControl()
    dialog._chart = MagicMock()
    dialog._on_mode_requested = None
    dialog._on_variable_requested = None
    dialog._on_plot_requested = None
    dialog._on_refresh_requested = None
    return dialog


def test_dialog_options_and_selected_control_values(dialog_module):
    dialog = _dialog(dialog_module)
    dialog.set_variable_options([("mesh1d:u", "Velocity"), ("mesh1d:s1", "Water")], "mesh1d:s1")
    dialog.set_time_options([(0, "t0"), (1, "t1")], 1)

    assert dialog.selected_variable() == "mesh1d:s1"
    assert dialog.selected_time_value() == 1
    assert dialog.time_expression() == "1:4, 8"
    assert dialog.selected_mode() == "point"
    assert dialog.selected_plot_type() == "lines"

    dialog._track_button.setChecked(True)
    dialog._plot_type_combo.setCurrentIndex(1)
    assert dialog.selected_mode() == "track"
    assert dialog.selected_plot_type() == "heatmap"

    dialog.set_variable_options([])
    dialog.set_time_options([])
    assert dialog.selected_variable() is None
    assert dialog.selected_time_value() is None


def test_dialog_labels_messages_and_plot_actions(dialog_module):
    dialog = _dialog(dialog_module)
    dialog.set_source_label(None)
    dialog.set_selection_text(None)
    assert dialog._source_label.text() == "Source: none"
    assert dialog._selection_label.text() == "Selection: none"

    dialog.set_message("Select a mesh node.")
    assert dialog._message_label.text() == "Select a mesh node."
    dialog._chart.set_message.assert_not_called()

    dialog.set_message("")
    dialog._chart.set_message.assert_called_once_with("")

    plot_data = {"plot_type": "lines", "series": []}
    dialog.apply_plot(plot_data, append=True)
    dialog._chart.set_plot.assert_called_once_with(plot_data, append=True)
    assert dialog._message_label.text() == ""

    dialog.clear_plot()
    dialog._chart.clear_plot.assert_called_once_with()


def test_dialog_callbacks_mode_and_figure_position(dialog_module):
    dialog = _dialog(dialog_module)
    mode_requested = MagicMock()
    variable_requested = MagicMock()
    plot_requested = MagicMock()
    refresh_requested = MagicMock()
    figure_position = MagicMock()
    dialog.set_handlers(
        mode_requested,
        variable_requested,
        plot_requested,
        refresh_requested,
        figure_position,
    )

    dialog._emit_mode_requested("track")
    dialog._emit_variable_requested(2)
    dialog._emit_plot_requested("add")
    dialog._emit_refresh_requested()
    dialog._set_x_position("x = 12.5")

    assert dialog._point_button.isChecked() is False
    assert dialog._track_button.isChecked() is True
    mode_requested.assert_called_once_with("track")
    variable_requested.assert_called_once_with()
    plot_requested.assert_called_once_with("add")
    refresh_requested.assert_called_once_with()
    dialog._chart.set_figure_position_callback.assert_called_once_with(figure_position)
    assert dialog._coordinate_label.text() == "Figure position: x = 12.5"

    dialog.set_handlers()
    dialog._emit_mode_requested("point")
    dialog._emit_variable_requested(0)
    dialog._emit_plot_requested("new")
    dialog._emit_refresh_requested()
