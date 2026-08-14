# -*- coding: utf-8 -*-
"""Profile chart dialog for Delft3D FM cross-section features."""

import math

from qgis.PyQt.QtCore import Qt
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


def _qt_color(name):
    """Return Qt color enum value across Qt5/Qt6."""
    value = getattr(Qt, name, None)
    if value is not None:
        return value
    return getattr(getattr(Qt, "GlobalColor", None), name, None)


def _qt_alignment_flag(name):
    """Return Qt alignment enum value across Qt5/Qt6."""
    value = getattr(Qt, name, None)
    if value is not None:
        return value
    return getattr(getattr(Qt, "AlignmentFlag", None), name, None)


def _qpainter_render_hint(name):
    """Return QPainter render hint enum value across Qt5/Qt6."""
    value = getattr(QPainter, name, None)
    if value is not None:
        return value
    return getattr(getattr(QPainter, "RenderHint", None), name, None)

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


class _ProfileChartWidget(QWidget):
    """Simple custom-painted profile chart."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []
        self._profiles = []
        self._message = ""
        self._vertical_exaggeration = 1.0
        self._default_points = []
        self._x_axis_label = "y [m]"
        self._y_axis_label = "z [m]"
        self.setMinimumHeight(260)

    def set_profile(self, points, message=""):
        self._points = list(points or [])
        self._profiles = [{"points": self._points, "label": "Profile"}]
        self._default_points = list(self._points)
        self._message = message or ""
        self.update()

    def set_profiles(self, profiles, message=""):
        self._profiles = list(profiles or [])
        self._points = list(self._profiles[0].get("points", []) if self._profiles else [])
        self._default_points = list(self._points)
        self._message = message or ""
        self.update()

    def set_vertical_exaggeration(self, factor):
        self._vertical_exaggeration = max(0.1, float(factor))
        self.update()

    def set_axis_labels(self, x_label, y_label):
        self._x_axis_label = str(x_label or "y [m]")
        self._y_axis_label = str(y_label or "z [m]")
        self.update()

    def reset_view(self):
        self._points = list(self._default_points)
        self._vertical_exaggeration = 1.0
        self.update()

    def paintEvent(self, event):
        del event

        painter = QPainter(self)
        painter.setRenderHint(_qpainter_render_hint("Antialiasing"), True)

        rect = self.rect()
        painter.fillRect(rect, _qt_color("white"))

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

        painter.setPen(QPen(_qt_color("gray"), 1))
        painter.drawRect(plot_left, plot_top, plot_right - plot_left, plot_bottom - plot_top)

        valid_points = [point for point in self._points if point[1] is not None]
        if not valid_points:
            painter.setPen(QPen(_qt_color("darkGray"), 1))
            text = self._message or "No profile available."
            painter.drawText(
                plot_left,
                plot_top,
                plot_right - plot_left,
                plot_bottom - plot_top,
                _qt_alignment_flag("AlignCenter"),
                text,
            )
            return

        x_values = [pt[0] for pt in valid_points]
        y_values = [pt[1] * self._vertical_exaggeration for pt in valid_points]

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

        painter.setPen(QPen(_qt_color("black"), 1))
        painter.drawLine(plot_left, plot_bottom, plot_right, plot_bottom)
        painter.drawLine(plot_left, plot_top, plot_left, plot_bottom)

        colors = ("darkGreen", "darkBlue", "darkRed", "darkCyan", "darkMagenta")
        for profile_index, profile in enumerate(self._profiles or [{"points": self._points}]):
            painter.setPen(QPen(_qt_color(colors[profile_index % len(colors)]), 2))
            previous = None
            for point in profile.get("points", []):
                if point[1] is None:
                    previous = None
                    continue
                if previous is not None:
                    painter.drawLine(
                        int(_map_x(previous[0])),
                        int(_map_y(previous[1] * self._vertical_exaggeration)),
                        int(_map_x(point[0])),
                        int(_map_y(point[1] * self._vertical_exaggeration)),
                    )
                previous = point

        painter.setPen(QPen(_qt_color("darkGray"), 1))
        painter.drawText(plot_left, plot_bottom + 20, self._x_axis_label)
        painter.save()
        painter.translate(plot_left - 28, plot_top + (plot_bottom - plot_top) / 2)
        painter.rotate(-90)
        painter.drawText(0, 0, self._y_axis_label)
        painter.restore()


class _MatplotlibProfileChartWidget(FigureCanvasQTAgg):
    """Matplotlib-based profile chart widget."""

    def __init__(self, parent=None):
        self._figure = Figure(figsize=(5, 3), tight_layout=True)
        self._axes = self._figure.add_subplot(111)
        super().__init__(self._figure)
        self.setParent(parent)

        self._points = []
        self._profiles = []
        self._default_points = []
        self._message = ""
        self._vertical_exaggeration = 1.0
        self._x_axis_label = "y [m]"
        self._y_axis_label = "z [m]"
        self.setMinimumHeight(260)

    def set_profile(self, points, message=""):
        self._points = list(points or [])
        self._profiles = [{"points": self._points, "label": "Profile"}]
        self._default_points = list(self._points)
        self._message = message or ""
        self._redraw()

    def set_profiles(self, profiles, message=""):
        self._profiles = list(profiles or [])
        self._points = list(self._profiles[0].get("points", []) if self._profiles else [])
        self._default_points = list(self._points)
        self._message = message or ""
        self._redraw()

    def set_vertical_exaggeration(self, factor):
        self._vertical_exaggeration = max(0.1, float(factor))
        self._redraw()

    def set_axis_labels(self, x_label, y_label):
        self._x_axis_label = str(x_label or "y [m]")
        self._y_axis_label = str(y_label or "z [m]")
        self._redraw()

    def reset_view(self):
        self._points = list(self._default_points)
        self._vertical_exaggeration = 1.0
        self._redraw()

    def _redraw(self):
        self._axes.clear()
        self._axes.set_xlabel(self._x_axis_label)
        self._axes.set_ylabel(self._y_axis_label)
        self._axes.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)

        if not any(point[1] is not None for profile in self._profiles for point in profile.get("points", [])):
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

        colors = ("#2e7d32", "#1565c0", "#c62828", "#00838f", "#6a1b9a")
        for profile_index, profile in enumerate(self._profiles):
            segment_x = []
            segment_y = []
            for point in profile.get("points", []):
                if point[1] is None:
                    if segment_x:
                        self._axes.plot(segment_x, segment_y, color=colors[profile_index % len(colors)], linewidth=2.0, label=profile.get("label", "Profile"))
                        segment_x, segment_y = [], []
                    continue
                segment_x.append(point[0])
                segment_y.append(point[1] * self._vertical_exaggeration)
            if segment_x:
                self._axes.plot(segment_x, segment_y, color=colors[profile_index % len(colors)], linewidth=2.0, label=profile.get("label", "Profile"))
        if len(self._profiles) > 1:
            self._axes.legend()
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


def _create_chart_widget(parent=None):
    """Return preferred chart widget implementation for this environment."""
    if _HAS_MATPLOTLIB:
        try:
            return _MatplotlibProfileChartWidget(parent)
        except (ImportError, RuntimeError):
            pass
    return _ProfileChartWidget(parent)


class CrossSectionProfileDialog(QDialog):
    """Separate chart window for FM profiles or mesh dataset slices."""

    def __init__(self, parent=None, mesh_mode=False):
        super().__init__(parent)
        self._mesh_mode = bool(mesh_mode)
        self.setWindowTitle("Mesh Dataset Slicer" if self._mesh_mode else "FM Cross-Section / Boundary Timeseries")
        self.resize(780, 460)

        self._title_label = QLabel(
            "Mesh Dataset Slicer" if self._mesh_mode else "FM Cross-Section / Boundary Timeseries"
        )
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self._meta_label = QLabel("")
        self._meta_label.setWordWrap(True)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet("color: #666666;")

        self._chart_widget = _create_chart_widget(self)
        self._on_draw_requested = None
        self._on_selected_lines_requested = None

        self._ve_spin = QDoubleSpinBox()
        self._ve_spin.setMinimum(0.1)
        self._ve_spin.setMaximum(20.0)
        self._ve_spin.setSingleStep(0.1)
        self._ve_spin.setValue(1.0)
        self._ve_spin.valueChanged.connect(self._chart_widget.set_vertical_exaggeration)

        self._reset_button = QPushButton("Reset View")
        self._reset_button.clicked.connect(self._on_reset)

        self._clear_button = QPushButton("Clear Slices")
        self._clear_button.clicked.connect(self.clear_profiles)

        self._draw_button = QPushButton("Draw Dataset Slice")
        self._draw_button.clicked.connect(self._draw_profile)
        self._selected_lines_button = QPushButton("Add Selected Line Slices")
        self._selected_lines_button.clicked.connect(self._add_selected_lines)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Vertical exaggeration:"))
        control_layout.addWidget(self._ve_spin)
        control_layout.addStretch(1)
        control_layout.addWidget(self._reset_button)
        if self._mesh_mode:
            control_layout.addWidget(self._clear_button)
            control_layout.addWidget(self._draw_button)
            control_layout.addWidget(self._selected_lines_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._meta_label)
        layout.addLayout(control_layout)
        layout.addWidget(self._chart_widget)
        layout.addWidget(self._message_label)

    def set_mesh_handlers(self, on_draw_requested=None, on_selected_lines_requested=None):
        """Set callbacks used by the mesh profile capture controls."""
        self._on_draw_requested = on_draw_requested
        self._on_selected_lines_requested = on_selected_lines_requested

    def _draw_profile(self):
        if callable(self._on_draw_requested):
            self._on_draw_requested()

    def _add_selected_lines(self):
        if callable(self._on_selected_lines_requested):
            self._on_selected_lines_requested()

    def set_status_message(self, message):
        """Update the non-modal status text without changing the chart."""
        self._message_label.setText(str(message or ""))

    def _on_reset(self):
        self._ve_spin.setValue(1.0)
        self._chart_widget.reset_view()

    def set_profile(self, points, title, metadata, message=""):
        """Update chart, title, metadata and status message."""
        self.set_profiles(
            [{"points": points or [], "label": title or "Profile", "metadata": metadata or {}}],
            title,
            metadata,
            message,
        )

    def add_profile(self, points, title, metadata=None, message=""):
        """Append a captured profile without changing existing curves."""
        profiles = list(getattr(self, "_profiles", []))
        profiles.append({"points": list(points or []), "label": title or "Profile", "metadata": metadata or {}})
        self.set_profiles(profiles, title, metadata, message)

    def clear_profiles(self):
        """Remove all captured mesh profiles."""
        self.set_profiles([], "Profile / Timeseries", {}, "")

    def set_profiles(self, profiles, title, metadata, message=""):
        """Render one or more named profiles."""
        self._profiles = list(profiles or [])
        self._title_label.setText(title or "Cross-Section Profile")

        metadata = metadata or {}
        x_axis_label = metadata.get("x_axis_label") or "y [m]"
        y_axis_label = metadata.get("y_axis_label") or "z [m]"
        if hasattr(self._chart_widget, "set_axis_labels"):
            self._chart_widget.set_axis_labels(x_axis_label, y_axis_label)

        parts = []
        for key in ("id", "definitionId", "def_type"):
            value = metadata.get(key)
            if value not in (None, ""):
                parts.append(f"{key}: {value}")
        self._meta_label.setText(" | ".join(parts))

        self._message_label.setText(message or "")
        if hasattr(self._chart_widget, "set_profiles"):
            self._chart_widget.set_profiles(profiles, message)
        else:
            first = profiles[0].get("points", []) if profiles else []
            self._chart_widget.set_profile(first, message)
