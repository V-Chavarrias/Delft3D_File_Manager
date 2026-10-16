from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.dialog_test_support import load_dialog_module
from tests.fixtures_qgis_fakes import FakeComboBox, FakeSignal


pytestmark = pytest.mark.unit


class _ComboBox(FakeComboBox):
    def setMaxVisibleItems(self, count):
        self.max_visible_items = count


class _Button:
    def __init__(self, text=""):
        self.text = text
        self.clicked = FakeSignal()
        self.enabled = True

    def setToolTip(self, text):
        self.tool_tip = text

    def setFixedWidth(self, width):
        self.fixed_width = width

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setDefault(self, is_default):
        self.is_default = bool(is_default)


class _Layout:
    def __init__(self, *_args):
        self.widgets = []

    def addWidget(self, widget, *_args):
        self.widgets.append(widget)

    def addLayout(self, *_args):
        pass

    def addStretch(self, *_args):
        pass

    def setContentsMargins(self, *_args):
        pass

    def setColumnStretch(self, *_args):
        pass


class _TextControl:
    def __init__(self, text=""):
        self.value = text

    def text(self):
        return self.value

    def setText(self, value):
        self.value = value


@pytest.fixture
def dialog_module(monkeypatch):
    module = load_dialog_module(
        monkeypatch,
        "large_map_dialog.py",
        "large_map_dialog",
    )
    monkeypatch.setattr(module, "QComboBox", _ComboBox)
    monkeypatch.setattr(module, "QPushButton", _Button)
    monkeypatch.setattr(module, "QHBoxLayout", _Layout)
    monkeypatch.setattr(module, "QGridLayout", _Layout)
    monkeypatch.setattr(module, "QVBoxLayout", _Layout)
    return module


def test_step_index_rejects_invalid_and_out_of_range_positions(dialog_module):
    assert dialog_module.step_index(1, 3, -1) == 0
    assert dialog_module.step_index(1, 3, 1) == 2
    assert dialog_module.step_index(0, 0, 1) is None
    assert dialog_module.step_index(None, 3, 1) is None
    assert dialog_module.step_index(-1, 3, 1) is None
    assert dialog_module.step_index(0, 3, -1) is None
    assert dialog_module.step_index(2, 3, 1) is None


def test_step_row_clamps_selection_updates_buttons_and_emits_steps(dialog_module):
    steps = []
    row = dialog_module._StepRow(lambda source, delta: steps.append((source, delta)))

    row.set_labels(["t0", "t1", "t2"], selected=20)

    assert row.combo.currentIndex() == 2
    assert row.previous_button.enabled is True
    assert row.next_button.enabled is False

    row.combo.setCurrentIndex(0)
    assert row.previous_button.enabled is False
    assert row.next_button.enabled is True

    row.next_button.clicked.emit()
    assert steps == [(row, 1)]

    row.setEnabled(False)
    row.update_buttons()
    assert row.previous_button.enabled is False
    assert row.next_button.enabled is False


def test_dialog_constructor_wires_controls_and_starts_disabled(dialog_module):
    dialog = dialog_module.LargeMapDialog()

    assert dialog._busy is False
    assert dialog._last_directory == ""
    assert dialog._on_file_selected is None
    assert dialog._on_variable_changed is None
    assert dialog._on_plot_requested is None
    assert dialog._variable_combo.isEnabled() is False
    assert dialog._plot_button.enabled is False
    assert dialog._time_row.isEnabled() is False


def test_browse_uses_current_directory_and_ignores_cancel(dialog_module, monkeypatch):
    dialog = dialog_module.LargeMapDialog()
    dialog._path_edit = _TextControl(r"C:\models\old_map.nc")
    on_file_selected = MagicMock()
    dialog.set_handlers(on_file_selected=on_file_selected)
    selected = []
    monkeypatch.setattr(
        dialog_module,
        "QFileDialog",
        SimpleNamespace(
            getOpenFileName=lambda *_args: ("", ""),
        ),
    )

    dialog._browse()

    assert dialog._path_edit.text() == r"C:\models\old_map.nc"
    on_file_selected.assert_not_called()

    monkeypatch.setattr(
        dialog_module,
        "QFileDialog",
        SimpleNamespace(
            getOpenFileName=lambda _parent, _title, start, _filter: (
                selected.append(start) or r"C:\results\new_map.nc",
                "",
            ),
        ),
    )
    dialog._browse()

    assert selected == [r"C:\models"]
    assert dialog._last_directory == r"C:\results"
    assert dialog._path_edit.text() == r"C:\results\new_map.nc"
    on_file_selected.assert_called_once_with(r"C:\results\new_map.nc")


def test_variable_time_and_extra_dimension_selections(dialog_module):
    dialog = dialog_module.LargeMapDialog()
    dialog._variable_combo = _ComboBox()
    dialog._time_row = dialog_module._StepRow(lambda *_args: None)
    dialog.set_variable_options(
        [("s1", "Water level"), ("ucx", "Velocity")],
        selected_key="ucx",
    )
    dialog.set_time_labels(["t0", "t1"], selected=1)

    dialog.set_extra_dimensions(
        [("sediment", ["A", "B"]), ("layer", ["top", "bottom"])],
        selected=[1, 0],
    )

    assert dialog.selected_variable() == "ucx"
    assert dialog.selected_time_index() == 1
    assert dialog.selected_extra_indices() == [1, 0]
    assert dialog._time_row.combo.currentText() == "t1"

    dialog.set_variable_options([])
    dialog.set_time_labels([])
    assert dialog.selected_variable() is None
    assert dialog.selected_time_index() == 0


def test_rebuilding_extra_dimensions_deletes_old_rows(dialog_module):
    dialog = dialog_module.LargeMapDialog()
    dialog._grid = MagicMock()
    old_row = dialog_module._StepRow(lambda *_args: None)
    old_label = MagicMock()
    dialog._extra_rows = [old_row]
    dialog._extra_labels = [old_label]

    dialog.set_extra_dimensions([("class", ["fine", "coarse"])])

    assert old_row._deleted is True
    old_label.deleteLater.assert_called_once_with()
    assert len(dialog._extra_rows) == 1
    assert dialog._extra_rows[0].combo.count() == 2
    assert dialog._grid.addWidget.call_count == 2


def test_busy_and_control_state_blocks_plot_and_step_requests(dialog_module):
    dialog = dialog_module.LargeMapDialog()
    on_plot = MagicMock()
    dialog.set_handlers(on_plot_requested=on_plot)
    row = dialog._time_row
    row.set_labels(["t0", "t1"])

    dialog._step(row, 1)
    assert row.combo.currentIndex() == 1
    on_plot.assert_called_once_with()

    dialog.set_busy(True)
    dialog._step(row, -1)
    dialog._emit_plot_requested()
    assert row.combo.currentIndex() == 1
    on_plot.assert_called_once_with()
    assert dialog._browse_button.enabled is False

    dialog.set_busy(False, has_time=False)
    assert dialog._browse_button.enabled is True
    assert row.isEnabled() is False


def test_setters_emit_handlers_and_handle_missing_callbacks(dialog_module):
    dialog = dialog_module.LargeMapDialog()
    dialog._path_edit = _TextControl()
    dialog._info_label = _TextControl()
    dialog._message_label = _TextControl()
    dialog._variable_combo = _ComboBox()
    on_file_selected = MagicMock()
    on_variable_changed = MagicMock()
    on_plot_requested = MagicMock()
    dialog.set_handlers(
        on_file_selected=on_file_selected,
        on_variable_changed=on_variable_changed,
        on_plot_requested=on_plot_requested,
    )

    dialog.set_path(None)
    dialog.set_info(None)
    dialog.set_message(None)
    dialog.set_variable_options([("s1", "Water level")])
    dialog._emit_variable_changed()
    dialog._emit_plot_requested()

    assert dialog._path_edit.text() == ""
    assert dialog._info_label.value == ""
    assert dialog._message_label.value == ""
    on_variable_changed.assert_called_once_with("s1")
    on_plot_requested.assert_called_once_with()

    dialog._on_variable_changed = None
    dialog._on_plot_requested = None
    dialog._emit_variable_changed()
    dialog._emit_plot_requested()
