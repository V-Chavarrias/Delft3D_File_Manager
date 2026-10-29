"""Non-modal window of the Large MAP / restart viewer."""

import os

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def step_index(current, count, delta):
    """Index after stepping ``delta`` within ``count`` items; ``None`` when out of range."""
    if count <= 0 or current is None or current < 0:
        return None
    target = int(current) + int(delta)
    if target < 0 or target >= count:
        return None
    return target


class _StepRow(QWidget):
    """◀ combo ▶ row used for time and extra dimensions."""

    def __init__(self, on_step, parent=None):
        super().__init__(parent)
        self.combo = QComboBox()
        self.combo.setMaxVisibleItems(15)
        self.previous_button = QPushButton("◀")
        self.next_button = QPushButton("▶")
        self.previous_button.setToolTip("Plot the previous entry")
        self.next_button.setToolTip("Plot the next entry")
        for button in (self.previous_button, self.next_button):
            button.setFixedWidth(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.next_button)
        self.previous_button.clicked.connect(lambda: on_step(self, -1))
        self.next_button.clicked.connect(lambda: on_step(self, 1))
        self.combo.currentIndexChanged.connect(lambda _index: self.update_buttons())

    def set_labels(self, labels, selected=0):
        self.combo.blockSignals(True)
        self.combo.clear()
        for label in labels:
            self.combo.addItem(str(label))
        if self.combo.count():
            self.combo.setCurrentIndex(min(max(int(selected or 0), 0), self.combo.count() - 1))
        self.combo.blockSignals(False)
        self.update_buttons()

    def update_buttons(self):
        enabled = self.isEnabled()
        index = self.combo.currentIndex()
        count = self.combo.count()
        self.previous_button.setEnabled(enabled and step_index(index, count, -1) is not None)
        self.next_button.setEnabled(enabled and step_index(index, count, 1) is not None)


class LargeMapDialog(QDialog):
    """File selection, variable/time/index selection and plotting controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Large MAP / Restart Viewer")
        self.setMinimumWidth(560)
        self._on_file_selected = None
        self._on_variable_changed = None
        self._on_plot_requested = None
        self._on_point_series_requested = None
        self._busy = False
        self._last_directory = ""
        self._point_series_enabled = False

        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Select a Delft3D FM MAP or restart file")
        self._browse_button = QPushButton("Browse...")
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("MAP/restart file:"))
        file_row.addWidget(self._path_edit, 1)
        file_row.addWidget(self._browse_button)

        self._info_label = QLabel("No file loaded.")
        self._info_label.setWordWrap(True)

        self._variable_combo = QComboBox()
        self._variable_combo.setMaxVisibleItems(20)
        self._time_row = _StepRow(self._step)
        self._extra_rows = []
        self._extra_labels = []

        self._grid = QGridLayout()
        self._grid.addWidget(QLabel("Variable:"), 0, 0)
        self._grid.addWidget(self._variable_combo, 0, 1)
        self._grid.addWidget(QLabel("Time:"), 1, 0)
        self._grid.addWidget(self._time_row, 1, 1)
        self._grid.setColumnStretch(1, 1)

        self._plot_button = QPushButton("Plot")
        self._plot_button.setDefault(True)
        self._point_series_button = QPushButton("Select Point Time Series")
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._point_series_button)
        actions.addWidget(self._plot_button)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(file_row)
        layout.addWidget(self._info_label)
        layout.addLayout(self._grid)
        layout.addLayout(actions)
        layout.addWidget(self._message_label)
        layout.addStretch(1)

        self._browse_button.clicked.connect(self._browse)
        self._variable_combo.currentIndexChanged.connect(self._emit_variable_changed)
        self._plot_button.clicked.connect(self._emit_plot_requested)
        self._point_series_button.clicked.connect(self._emit_point_series_requested)
        self.set_controls_enabled(False)

    # -------------------------------------------------------------- handlers
    def set_handlers(
        self,
        on_file_selected=None,
        on_variable_changed=None,
        on_plot_requested=None,
        on_point_series_requested=None,
    ):
        self._on_file_selected = on_file_selected
        self._on_variable_changed = on_variable_changed
        self._on_plot_requested = on_plot_requested
        self._on_point_series_requested = on_point_series_requested

    def _browse(self):
        start = os.path.dirname(self._path_edit.text()) or self._last_directory
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Delft3D FM MAP or restart file",
            start,
            "Delft3D FM MAP/restart files (*_map.nc *_rst.nc);;NetCDF files (*.nc);;All files (*)",
        )
        if not path:
            return
        self._last_directory = os.path.dirname(path)
        self._path_edit.setText(path)
        if callable(self._on_file_selected):
            self._on_file_selected(path)

    def _emit_variable_changed(self, _index=None):
        if callable(self._on_variable_changed):
            self._on_variable_changed(self.selected_variable())

    def _emit_plot_requested(self):
        if not self._busy and callable(self._on_plot_requested):
            self._on_plot_requested()

    def _emit_point_series_requested(self):
        if (
            not self._busy
            and self._point_series_enabled
            and callable(self._on_point_series_requested)
        ):
            self._on_point_series_requested()

    def _step(self, row, delta):
        if self._busy:
            return
        target = step_index(row.combo.currentIndex(), row.combo.count(), delta)
        if target is None:
            return
        row.combo.setCurrentIndex(target)
        self._emit_plot_requested()

    # ---------------------------------------------------------------- setters
    def set_path(self, path):
        self._path_edit.setText(str(path or ""))

    def set_info(self, text):
        self._info_label.setText(str(text or ""))

    def set_message(self, text):
        self._message_label.setText(str(text or ""))

    def set_variable_options(self, options, selected_key=None):
        self._variable_combo.blockSignals(True)
        self._variable_combo.clear()
        selected = 0
        for index, (key, label) in enumerate(options or []):
            self._variable_combo.addItem(str(label), key)
            if selected_key is not None and key == selected_key:
                selected = index
        if self._variable_combo.count():
            self._variable_combo.setCurrentIndex(selected)
        self._variable_combo.blockSignals(False)

    def set_time_labels(self, labels, selected=0):
        self._time_row.set_labels(labels, selected)

    def set_time_enabled(self, enabled):
        self._time_row.setEnabled(bool(enabled) and not self._busy)
        self._time_row.update_buttons()

    def set_point_series_enabled(self, enabled):
        self._point_series_enabled = bool(enabled)
        self._point_series_button.setEnabled(self._point_series_enabled and not self._busy)

    def set_extra_dimensions(self, dimensions, selected=None):
        """Rebuild the index rows; ``dimensions`` is a list of (title, labels)."""
        for row, label in zip(self._extra_rows, self._extra_labels):
            self._grid.removeWidget(row)
            self._grid.removeWidget(label)
            row.deleteLater()
            label.deleteLater()
        self._extra_rows = []
        self._extra_labels = []
        selected = list(selected or [])
        for position, (title, labels) in enumerate(dimensions or []):
            label = QLabel(f"{title}:")
            row = _StepRow(self._step)
            row.set_labels(labels, selected[position] if position < len(selected) else 0)
            self._grid.addWidget(label, 2 + position, 0)
            self._grid.addWidget(row, 2 + position, 1)
            row.setEnabled(not self._busy)
            self._extra_labels.append(label)
            self._extra_rows.append(row)

    def set_controls_enabled(self, enabled):
        enabled = bool(enabled)
        for widget in [
            self._variable_combo,
            self._plot_button,
            self._point_series_button,
            self._time_row,
            *self._extra_rows,
        ]:
            widget.setEnabled(enabled)
        self._point_series_button.setEnabled(enabled and self._point_series_enabled)
        self._time_row.update_buttons()
        for row in self._extra_rows:
            row.update_buttons()

    def set_busy(self, busy, has_time=True):
        self._busy = bool(busy)
        self._browse_button.setEnabled(not self._busy)
        self.set_controls_enabled(not self._busy)
        if not self._busy and not has_time:
            self.set_time_enabled(False)

    # ---------------------------------------------------------------- getters
    def selected_variable(self):
        return self._variable_combo.currentData() if self._variable_combo.count() else None

    def selected_time_index(self):
        return self._time_row.combo.currentIndex() if self._time_row.combo.count() else 0

    def selected_extra_indices(self):
        return [max(row.combo.currentIndex(), 0) for row in self._extra_rows]
