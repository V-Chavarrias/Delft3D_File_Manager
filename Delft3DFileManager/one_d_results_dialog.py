"""Panel for exploring time-dependent Delft3D mesh1d results."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
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


def _qt_value(container, name, nested=None):
    value = getattr(container, name, None)
    if value is not None:
        return value
    return getattr(getattr(container, nested or name, None), name, None)


class _ResultsChartWidget(FigureCanvasQTAgg):
    def __init__(self, parent=None):
        self._figure = Figure(figsize=(7, 4), tight_layout=True)
        self._axes = self._figure.add_subplot(111)
        super().__init__(self._figure)
        self.setParent(parent)
        self._message = ""
        self._colorbars = []

    def clear_plot(self):
        self._message = ""
        self._remove_colorbars()
        self._axes.clear()
        self.draw_idle()

    def save_figure(self, parent=None):
        filename, _ = QFileDialog.getSaveFileName(
            parent or self,
            "Save Figure",
            "",
            "PNG image (*.png)",
        )
        if not filename:
            return False
        if not filename.lower().endswith(".png"):
            filename += ".png"
        self._figure.savefig(filename, format="png", dpi=300)
        return True

    def set_message(self, message):
        self._message = str(message or "")
        self._redraw()

    def set_plot(self, plot_data, append=False):
        if not append:
            self._remove_colorbars()
            self._axes.clear()
        plot_type = plot_data.get("plot_type")
        if plot_type == "heatmap":
            image = self._axes.imshow(
                plot_data["values"],
                aspect="auto",
                origin="lower",
                extent=plot_data["extent"],
            )
            colorbar = self._axes.figure.colorbar(image, ax=self._axes)
            colorbar.set_label(plot_data.get("colorbar_label", ""))
            self._colorbars.append(colorbar)
            if plot_data.get("time_is_datetime"):
                try:
                    from matplotlib import dates as mdates
                    self._axes.yaxis_date()
                    self._axes.yaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
                except (ImportError, AttributeError, ValueError):
                    pass
        else:
            for entry in plot_data.get("series", []):
                self._axes.plot(entry["x"], entry["y"], linewidth=1.8, label=entry["label"])
            if plot_data.get("series"):
                self._axes.legend(loc="best")
        self._axes.set_title(plot_data.get("title", "1D Results"))
        self._axes.set_xlabel(plot_data.get("x_label", ""))
        self._axes.set_ylabel(plot_data.get("y_label", ""))
        self._axes.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
        self._message = ""
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()

    def _remove_colorbars(self):
        for colorbar in self._colorbars:
            try:
                colorbar.remove()
            except (AttributeError, RuntimeError, ValueError):
                pass
        self._colorbars = []

    def _redraw(self):
        self._axes.clear()
        self._axes.text(
            0.5,
            0.5,
            self._message or "No plot available.",
            ha="center",
            va="center",
            transform=self._axes.transAxes,
        )
        self.draw_idle()


class _FallbackChartWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(_qt_value(Qt, "AlignCenter", "AlignmentFlag"))
        self.setText("Matplotlib is not available in this environment.")

    def clear_plot(self):
        self.setText("No plot available.")

    def set_message(self, message):
        self.setText(str(message or ""))

    def set_plot(self, plot_data, append=False):
        del plot_data, append

    def save_figure(self, parent=None):
        del parent
        return False
        self.setText("Matplotlib is not available in this environment.")


class OneDResultsDialog(QDialog):
    """Interactive controls for mesh1d point and track results plots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("1D Results Visualizer")
        self.setMinimumSize(820, 520)
        self.resize(1080, 680)
        expanding = _qt_value(QSizePolicy, "Expanding", "Policy")
        if expanding is not None:
            self.setSizePolicy(expanding, expanding)

        self._on_mode_requested = None
        self._on_plot_requested = None
        self._on_refresh_requested = None
        self._source_label = QLabel("Source: none")
        self._selection_label = QLabel("Selection: none")
        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)

        self._point_button = QPushButton("Point")
        self._track_button = QPushButton("Track")
        for button in (self._point_button, self._track_button):
            button.setCheckable(True)
        self._point_button.setChecked(True)

        self._variable_combo = QComboBox()
        self._time_combo = QComboBox()
        self._time_combo.setMaxVisibleItems(10)
        self._time_expression = QLineEdit()
        self._time_expression.setPlaceholderText("Indices, e.g. 1:10,20:25")
        self._plot_type_combo = QComboBox()
        self._plot_type_combo.addItem("Distance lines", "lines")
        self._plot_type_combo.addItem("Distance-time heatmap", "heatmap")

        controls = QHBoxLayout()
        controls.addWidget(self._point_button)
        controls.addWidget(self._track_button)
        controls.addWidget(QLabel("Variable:"))
        controls.addWidget(self._variable_combo, 2)
        controls.addWidget(QLabel("Times:"))
        controls.addWidget(self._time_combo, 2)
        controls.addWidget(self._time_expression, 2)
        controls.addWidget(QLabel("Track plot:"))
        controls.addWidget(self._plot_type_combo, 2)

        self._chart = _ResultsChartWidget(self) if _HAS_MATPLOTLIB else _FallbackChartWidget(self)
        if expanding is not None:
            self._chart.setSizePolicy(expanding, expanding)

        refresh_button = QPushButton("Refresh Active Mesh")
        new_button = QPushButton("New Plot")
        add_button = QPushButton("Add To Plot")
        clear_button = QPushButton("Clear Plot")
        print_button = QPushButton("Save Figure PNG")
        actions = QHBoxLayout()
        actions.addWidget(refresh_button)
        actions.addStretch(1)
        actions.addWidget(new_button)
        actions.addWidget(add_button)
        actions.addWidget(clear_button)
        actions.addWidget(print_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Delft3D 1D Results"))
        layout.addWidget(self._source_label)
        layout.addLayout(controls)
        layout.addWidget(self._selection_label)
        layout.addWidget(self._chart, 1)
        layout.addLayout(actions)
        layout.addWidget(self._message_label)

        self._point_button.clicked.connect(lambda: self._emit_mode_requested("point"))
        self._track_button.clicked.connect(lambda: self._emit_mode_requested("track"))
        refresh_button.clicked.connect(self._emit_refresh_requested)
        new_button.clicked.connect(lambda: self._emit_plot_requested("new"))
        add_button.clicked.connect(lambda: self._emit_plot_requested("add"))
        clear_button.clicked.connect(self.clear_plot)
        print_button.clicked.connect(lambda: self._chart.save_figure(self))

    def set_handlers(self, on_mode_requested=None, on_plot_requested=None, on_refresh_requested=None):
        self._on_mode_requested = on_mode_requested
        self._on_plot_requested = on_plot_requested
        self._on_refresh_requested = on_refresh_requested

    def _set_options(self, combo, options, selected_value=None):
        combo.blockSignals(True)
        combo.clear()
        selected_index = 0
        for index, (value, label) in enumerate(options or []):
            combo.addItem(str(label), value)
            if selected_value is not None and str(value) == str(selected_value):
                selected_index = index
        if combo.count():
            combo.setCurrentIndex(selected_index)
        combo.blockSignals(False)

    def set_source_label(self, text):
        self._source_label.setText(str(text or "Source: none"))

    def set_variable_options(self, options, selected_value=None):
        self._set_options(self._variable_combo, options, selected_value)

    def set_time_options(self, options, selected_value=None):
        self._set_options(self._time_combo, options, selected_value)

    def selected_variable(self):
        return self._variable_combo.currentData() if self._variable_combo.count() else None

    def selected_time_value(self):
        return self._time_combo.currentData() if self._time_combo.count() else None

    def time_expression(self):
        return self._time_expression.text().strip()

    def selected_mode(self):
        return "track" if self._track_button.isChecked() else "point"

    def selected_plot_type(self):
        return self._plot_type_combo.currentData()

    def set_selection_text(self, text):
        self._selection_label.setText(str(text or "Selection: none"))

    def set_message(self, message):
        self._message_label.setText(str(message or ""))
        if not message:
            self._chart.set_message("")

    def apply_plot(self, plot_data, append=False):
        self._chart.set_plot(plot_data, append=append)
        self._message_label.setText("")

    def clear_plot(self):
        self._chart.clear_plot()

    def _emit_mode_requested(self, mode):
        self._point_button.setChecked(mode == "point")
        self._track_button.setChecked(mode == "track")
        if callable(self._on_mode_requested):
            self._on_mode_requested(mode)

    def _emit_plot_requested(self, mode):
        if callable(self._on_plot_requested):
            self._on_plot_requested(mode)

    def _emit_refresh_requested(self):
        if callable(self._on_refresh_requested):
            self._on_refresh_requested()