# -*- coding: utf-8 -*-
"""Profile chart dialog for Delft3D FM cross-section features."""

import math

from PyQt5.QtCore import Qt
from qgis.PyQt.QtGui import QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    _HAS_MATPLOTLIB = True
except Exception:
    FigureCanvasQTAgg = object
    Figure = object
    _HAS_MATPLOTLIB = False


class _ProfileChartWidget(QWidget):
    """Simple custom-painted profile chart."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []
        self._message = ""
        self._vertical_exaggeration = 1.0
        self._default_points = []
        self.setMinimumHeight(260)

    def set_profile(self, points, message=""):
        self._points = list(points or [])
        self._default_points = list(self._points)
        self._message = message or ""
        self.update()

    def set_vertical_exaggeration(self, factor):
        self._vertical_exaggeration = max(0.1, float(factor))
        self.update()

    def reset_view(self):
        self._points = list(self._default_points)
        self._vertical_exaggeration = 1.0
        self.update()

    def paintEvent(self, event):
        del event

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, Qt.white)

        margin_left = 52
        margin_right = 20
        margin_top = 20
        margin_bottom = 40

        plot_left = rect.left() + margin_left
        plot_right = rect.right() - margin_right
        plot_top = rect.top() + margin_top
        plot_bottom = rect.bottom() - margin_bottom

        if plot_right <= plot_left or plot_bottom <= plot_top:
            return

        painter.setPen(QPen(Qt.gray, 1))
        painter.drawRect(plot_left, plot_top, plot_right - plot_left, plot_bottom - plot_top)

        if not self._points:
            painter.setPen(QPen(Qt.darkGray, 1))
            text = self._message or "No profile available."
            painter.drawText(
                plot_left,
                plot_top,
                plot_right - plot_left,
                plot_bottom - plot_top,
                Qt.AlignCenter,
                text,
            )
            return

        x_values = [pt[0] for pt in self._points]
        y_values = [pt[1] * self._vertical_exaggeration for pt in self._points]

        x_min = min(x_values)
        x_max = max(x_values)
        y_min = min(y_values)
        y_max = max(y_values)

        if math.isclose(x_min, x_max):
            x_min -= 1.0
            x_max += 1.0
        if math.isclose(y_min, y_max):
            y_min -= 1.0
            y_max += 1.0

        def _map_x(x_val):
            return plot_left + (x_val - x_min) * (plot_right - plot_left) / (x_max - x_min)

        def _map_y(y_val):
            return plot_bottom - (y_val - y_min) * (plot_bottom - plot_top) / (y_max - y_min)

        painter.setPen(QPen(Qt.black, 1))
        painter.drawLine(plot_left, plot_bottom, plot_right, plot_bottom)
        painter.drawLine(plot_left, plot_top, plot_left, plot_bottom)

        painter.setPen(QPen(Qt.darkGreen, 2))
        for idx in range(1, len(self._points)):
            x0 = _map_x(self._points[idx - 1][0])
            y0 = _map_y(self._points[idx - 1][1] * self._vertical_exaggeration)
            x1 = _map_x(self._points[idx][0])
            y1 = _map_y(self._points[idx][1] * self._vertical_exaggeration)
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        painter.setPen(QPen(Qt.darkGray, 1))
        painter.drawText(plot_left, plot_bottom + 20, "y [m]")
        painter.save()
        painter.translate(plot_left - 28, plot_top + (plot_bottom - plot_top) / 2)
        painter.rotate(-90)
        painter.drawText(0, 0, "z [m]")
        painter.restore()


class _MatplotlibProfileChartWidget(FigureCanvasQTAgg):
    """Matplotlib-based profile chart widget."""

    def __init__(self, parent=None):
        self._figure = Figure(figsize=(5, 3), tight_layout=True)
        self._axes = self._figure.add_subplot(111)
        super().__init__(self._figure)
        self.setParent(parent)

        self._points = []
        self._default_points = []
        self._message = ""
        self._vertical_exaggeration = 1.0
        self.setMinimumHeight(260)

    def set_profile(self, points, message=""):
        self._points = list(points or [])
        self._default_points = list(self._points)
        self._message = message or ""
        self._redraw()

    def set_vertical_exaggeration(self, factor):
        self._vertical_exaggeration = max(0.1, float(factor))
        self._redraw()

    def reset_view(self):
        self._points = list(self._default_points)
        self._vertical_exaggeration = 1.0
        self._redraw()

    def _redraw(self):
        self._axes.clear()
        self._axes.set_xlabel("y [m]")
        self._axes.set_ylabel("z [m]")
        self._axes.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)

        if not self._points:
            self._axes.text(
                0.5,
                0.5,
                self._message or "No profile available.",
                ha="center",
                va="center",
                transform=self._axes.transAxes,
            )
            self.draw_idle()
            return

        x_vals = [point[0] for point in self._points]
        y_vals = [point[1] * self._vertical_exaggeration for point in self._points]
        self._axes.plot(x_vals, y_vals, color="#2e7d32", linewidth=2.0)
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


def _create_chart_widget(parent=None):
    """Return preferred chart widget implementation for this environment."""
    if _HAS_MATPLOTLIB:
        try:
            return _MatplotlibProfileChartWidget(parent)
        except Exception:
            pass
    return _ProfileChartWidget(parent)


class CrossSectionProfileDialog(QDialog):
    """Separate profile chart window for cross-section features."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cross-Section Profile")
        self.resize(780, 460)

        self._title_label = QLabel("Cross-Section Profile")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self._meta_label = QLabel("")
        self._meta_label.setWordWrap(True)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet("color: #666666;")

        self._chart_widget = _create_chart_widget(self)

        self._ve_spin = QDoubleSpinBox()
        self._ve_spin.setMinimum(0.1)
        self._ve_spin.setMaximum(20.0)
        self._ve_spin.setSingleStep(0.1)
        self._ve_spin.setValue(1.0)
        self._ve_spin.valueChanged.connect(self._chart_widget.set_vertical_exaggeration)

        self._reset_button = QPushButton("Reset View")
        self._reset_button.clicked.connect(self._on_reset)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Vertical exaggeration:"))
        control_layout.addWidget(self._ve_spin)
        control_layout.addStretch(1)
        control_layout.addWidget(self._reset_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._meta_label)
        layout.addLayout(control_layout)
        layout.addWidget(self._chart_widget)
        layout.addWidget(self._message_label)

    def _on_reset(self):
        self._ve_spin.setValue(1.0)
        self._chart_widget.reset_view()

    def set_profile(self, points, title, metadata, message=""):
        """Update chart, title, metadata and status message."""
        self._title_label.setText(title or "Cross-Section Profile")

        metadata = metadata or {}
        parts = []
        for key in ("id", "definitionId", "def_type"):
            value = metadata.get(key)
            if value not in (None, ""):
                parts.append(f"{key}: {value}")
        self._meta_label.setText(" | ".join(parts))

        self._message_label.setText(message or "")
        self._chart_widget.set_profile(points, message)
