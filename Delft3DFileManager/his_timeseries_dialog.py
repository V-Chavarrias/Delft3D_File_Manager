# -*- coding: utf-8 -*-
"""Dedicated Delft3D FM HIS timeseries explorer dialog."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    except Exception:
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    _HAS_MATPLOTLIB = True
except Exception:
    FigureCanvasQTAgg = object
    Figure = object
    _HAS_MATPLOTLIB = False


class _MatplotlibSeriesChartWidget(FigureCanvasQTAgg):
    """Matplotlib chart widget supporting multiple timeseries overlays."""

    def __init__(self, parent=None):
        self._figure = Figure(figsize=(6, 3.5), tight_layout=True)
        self._axes = self._figure.add_subplot(111)
        super().__init__(self._figure)
        self.setParent(parent)
        self._series = []
        self._x_axis_label = "time"
        self._y_axis_label = "value"
        self._title = "HIS Timeseries"
        self._message = ""

    def clear_series(self):
        self._series = []
        self._message = ""
        self._redraw()

    def set_message(self, message):
        self._message = str(message or "")
        self._redraw()

    def set_series(self, series_entries, x_axis_label, y_axis_label, title, append=False):
        if not append:
            self._series = []
        self._series.extend(list(series_entries or []))
        self._x_axis_label = str(x_axis_label or "time")
        self._y_axis_label = str(y_axis_label or "value")
        self._title = str(title or "HIS Timeseries")
        self._message = ""
        self._redraw()

    def _redraw(self):
        self._axes.clear()
        self._axes.set_title(self._title)
        self._axes.set_xlabel(self._x_axis_label)
        self._axes.set_ylabel(self._y_axis_label)
        self._axes.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)

        if not self._series:
            self._axes.text(
                0.5,
                0.5,
                self._message or "No series plotted.",
                ha="center",
                va="center",
                transform=self._axes.transAxes,
            )
            self.draw_idle()
            return

        for entry in self._series:
            x_values = entry.get("x", [])
            y_values = entry.get("y", [])
            label = entry.get("label", "series")
            self._axes.plot(x_values, y_values, linewidth=1.8, label=label)

        self._axes.legend(loc="best")
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


class _FallbackChartWidget(QWidget):
    """Fallback widget used when matplotlib is unavailable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel("Matplotlib is not available in this environment.")
        self._label.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def clear_series(self):
        self._label.setText("No series plotted.")

    def set_message(self, message):
        self._label.setText(str(message or ""))

    def set_series(self, series_entries, x_axis_label, y_axis_label, title, append=False):
        del series_entries, x_axis_label, y_axis_label, title, append
        self._label.setText("Matplotlib is not available in this environment.")


def _create_chart_widget(parent=None):
    if _HAS_MATPLOTLIB:
        try:
            return _MatplotlibSeriesChartWidget(parent)
        except (ImportError, RuntimeError):
            pass
    return _FallbackChartWidget(parent)


class HisTimeseriesDialog(QDialog):
    """Timeseries explorer driven by active selection and variable dropdowns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HIS Timeseries Explorer")
        self.resize(980, 560)

        self._on_controls_changed = None
        self._on_plot_requested = None
        self._on_refresh_requested = None
        self._plotted_labels = []

        self._title_label = QLabel("Delft3D FM HIS Timeseries")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self._source_combo = QComboBox()
        self._scope_combo = QComboBox()
        self._variable_combo = QComboBox()

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Source:"))
        controls_row.addWidget(self._source_combo, stretch=3)
        controls_row.addWidget(QLabel("Scope:"))
        controls_row.addWidget(self._scope_combo, stretch=2)
        controls_row.addWidget(QLabel("Variable:"))
        controls_row.addWidget(self._variable_combo, stretch=4)

        self._selection_label = QLabel("Selection: none")
        self._selection_label.setWordWrap(True)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet("color: #666666;")

        self._chart_widget = _create_chart_widget(self)

        self._series_list = QListWidget(self)
        self._series_list.setMinimumWidth(280)

        chart_and_series_row = QHBoxLayout()
        chart_and_series_row.addWidget(self._chart_widget, stretch=5)

        side_layout = QVBoxLayout()
        side_layout.addWidget(QLabel("Plotted series:"))
        side_layout.addWidget(self._series_list, stretch=1)
        chart_and_series_row.addLayout(side_layout, stretch=2)

        self._refresh_button = QPushButton("Refresh Selection")
        self._new_plot_button = QPushButton("New Plot")
        self._add_plot_button = QPushButton("Add To Plot")
        self._clear_plot_button = QPushButton("Clear Plot")

        actions_row = QHBoxLayout()
        actions_row.addWidget(self._refresh_button)
        actions_row.addStretch(1)
        actions_row.addWidget(self._new_plot_button)
        actions_row.addWidget(self._add_plot_button)
        actions_row.addWidget(self._clear_plot_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addLayout(controls_row)
        layout.addWidget(self._selection_label)
        layout.addLayout(chart_and_series_row)
        layout.addLayout(actions_row)
        layout.addWidget(self._message_label)

        self._source_combo.currentIndexChanged.connect(self._emit_controls_changed)
        self._scope_combo.currentIndexChanged.connect(self._emit_controls_changed)
        self._variable_combo.currentIndexChanged.connect(self._emit_controls_changed)
        self._refresh_button.clicked.connect(self._emit_refresh_requested)
        self._new_plot_button.clicked.connect(lambda: self._emit_plot_requested("new"))
        self._add_plot_button.clicked.connect(lambda: self._emit_plot_requested("add"))
        self._clear_plot_button.clicked.connect(self.clear_plot)

    def set_handlers(self, on_controls_changed=None, on_plot_requested=None, on_refresh_requested=None):
        self._on_controls_changed = on_controls_changed
        self._on_plot_requested = on_plot_requested
        self._on_refresh_requested = on_refresh_requested

    def _set_combo_options(self, combo, options, selected_value=None):
        options = list(options or [])
        combo.blockSignals(True)
        combo.clear()
        selected_index = 0

        for index, (value, label) in enumerate(options):
            combo.addItem(str(label), str(value))
            if selected_value is not None and str(value) == str(selected_value):
                selected_index = index

        if options:
            combo.setCurrentIndex(selected_index)
        combo.blockSignals(False)

    def set_source_options(self, options, selected_value=None):
        self._set_combo_options(self._source_combo, options, selected_value)

    def set_scope_options(self, options, selected_value=None):
        self._set_combo_options(self._scope_combo, options, selected_value)

    def set_variable_options(self, options, selected_value=None):
        self._set_combo_options(self._variable_combo, options, selected_value)

    def selected_source(self):
        return self._source_combo.currentData() if self._source_combo.count() else None

    def selected_scope(self):
        return self._scope_combo.currentData() if self._scope_combo.count() else None

    def selected_variable(self):
        return self._variable_combo.currentData() if self._variable_combo.count() else None

    def set_selection_text(self, text):
        self._selection_label.setText(str(text or "Selection: none"))

    def set_message(self, message):
        self._message_label.setText(str(message or ""))
        if not self._plotted_labels:
            self._chart_widget.set_message(message or "")

    def clear_plot(self):
        self._plotted_labels = []
        self._series_list.clear()
        self._chart_widget.clear_series()

    def apply_series(self, series_entries, x_axis_label, y_axis_label, title, append=False):
        entries = list(series_entries or [])
        if not append:
            self._plotted_labels = []
            self._series_list.clear()

        for entry in entries:
            label = str(entry.get("label", "series"))
            self._plotted_labels.append(label)
            self._series_list.addItem(label)

        self._chart_widget.set_series(entries, x_axis_label, y_axis_label, title, append=append)
        self._message_label.setText("")

    def _emit_controls_changed(self):
        if callable(self._on_controls_changed):
            self._on_controls_changed()

    def _emit_plot_requested(self, mode):
        if callable(self._on_plot_requested):
            self._on_plot_requested(mode)

    def _emit_refresh_requested(self):
        if callable(self._on_refresh_requested):
            self._on_refresh_requested()
