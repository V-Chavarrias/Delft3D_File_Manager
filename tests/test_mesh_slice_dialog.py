from unittest.mock import MagicMock

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
from matplotlib.figure import Figure  # noqa: E402

from Delft3DFileManager.cross_section_profile_dialog import (  # noqa: E402
    _MatplotlibProfileChartWidget,
)


def _chart():
    chart = _MatplotlibProfileChartWidget.__new__(_MatplotlibProfileChartWidget)
    chart._figure = Figure()
    chart._axes = chart._figure.add_subplot(111)
    chart._points = []
    chart._profiles = []
    chart._patch_data = None
    chart._default_points = []
    chart._message = ""
    chart._vertical_exaggeration = 1.0
    chart._x_axis_label = "x"
    chart._y_axis_label = "y"
    chart._colorbar = None
    chart._patch_mesh = None
    chart._y_limits = (None, None)
    chart._color_limits = (None, None)
    chart._auto_y_limits = None
    chart._auto_color_limits = None
    chart.draw_idle = MagicMock()
    return chart


def _patch_args():
    x_edges = np.array([0.0, 1.0, 2.0])
    elevations = np.array([[10.0, 10.0, 10.0], [9.0, 9.0, 9.0], [8.0, 8.0, 8.0]])
    values = np.array([[0.1, 0.2], [0.3, 0.4]])
    return x_edges, elevations, values


def test_clearing_patch_leaves_no_extra_colorbar():
    chart = _chart()
    chart.set_patch(*_patch_args(), colorbar_label="fraction")
    chart.set_axis_labels("chainage", "elevation")
    assert len(chart._figure.axes) == 2

    chart.set_axis_labels("y", "z")
    chart.set_profiles([], "")
    assert len(chart._figure.axes) == 1


def test_limits_apply_to_displayed_patch_without_redraw():
    chart = _chart()
    chart.set_patch(*_patch_args(), colorbar_label="fraction")
    mesh = chart._patch_mesh

    chart.set_y_limits(8.5, None)
    chart.set_color_limits(0.0, 1.0)

    assert chart._patch_mesh is mesh
    assert chart._axes.get_ylim() == (8.5, 10.0)
    assert mesh.get_clim() == (0.0, 1.0)

    chart.set_y_limits(None, None)
    chart.set_color_limits(None, None)
    assert chart._axes.get_ylim() == (8.0, 10.0)
    assert mesh.get_clim() == pytest.approx((0.1, 0.4))


def test_substrate_selection_redraws_patch_along_last_line(plugin):
    plugin._mesh_profile_map_tool = None
    plugin._mesh_profile_last_line = [(0.0, 0.0), (1.0, 1.0)]
    plugin._append_substrate_profile = MagicMock()
    plugin._start_substrate_patch_capture = MagicMock()

    plugin._on_substrate_selection_changed("volume", "Sediment1")

    plugin._append_substrate_profile.assert_called_once_with(
        [(0.0, 0.0), (1.0, 1.0)], "volume", "Sediment1"
    )
    plugin._start_substrate_patch_capture.assert_not_called()


def test_substrate_selection_without_line_starts_capture(plugin):
    plugin._mesh_profile_map_tool = None
    plugin._mesh_profile_last_line = None
    plugin._start_substrate_patch_capture = MagicMock()

    plugin._on_substrate_selection_changed("arithmetic", "")

    plugin._start_substrate_patch_capture.assert_called_once_with("arithmetic", "")


def test_substrate_selection_updates_active_capture(plugin):
    tool = object()
    plugin._mesh_profile_map_tool = tool
    plugin.iface.mapCanvas.return_value.mapTool.return_value = tool
    plugin._start_substrate_patch_capture = MagicMock()

    plugin._on_substrate_selection_changed("geometric", "")

    assert plugin._substrate_patch_requested is True
    assert plugin._substrate_patch_mode == "geometric"
    plugin._start_substrate_patch_capture.assert_not_called()


def test_mean_grain_size_without_sediment_file_asks_for_sed_file(plugin):
    plugin._mesh_profile_source_layers = [MagicMock()]
    plugin._sediment_records = []
    plugin._sediment_records_from_layers = MagicMock(return_value=[])
    plugin._show_mesh_profile_message = MagicMock()

    plugin._append_substrate_profile([(0.0, 0.0), (1.0, 1.0)], "arithmetic", "")

    message = plugin._show_mesh_profile_message.call_args.args[0]
    assert ".sed" in message


def test_mean_grain_size_with_sediment_file_does_not_require_fraction_dataset(plugin):
    plugin._mesh_profile_source_layers = [MagicMock()]
    plugin._sediment_records = [MagicMock()]
    plugin._mesh_profile_dataset_index = MagicMock(return_value=None)
    plugin._mesh_profile_edge_crossings = MagicMock(return_value=[])
    plugin._show_mesh_profile_message = MagicMock()

    plugin._append_substrate_profile([(0.0, 0.0), (1.0, 1.0)], "geometric", "")

    plugin._mesh_profile_edge_crossings.assert_called_once()
    message = plugin._show_mesh_profile_message.call_args.args[0]
    assert "substrate" not in message.lower()


def test_selected_lines_draw_substrate_patch_when_selected(plugin):
    feature = MagicMock()
    feature.id.return_value = 7
    layer = MagicMock()
    layer.getSelectedFeatures.return_value = [feature]
    line = [(0.0, 0.0), (1.0, 1.0)]
    dialog = MagicMock()
    dialog.substrate_patch_mode.return_value = "volume"
    dialog.substrate_fraction.return_value = "Sediment1"
    plugin._selected_mesh_profile_line_layer = MagicMock(return_value=layer)
    plugin._ensure_mesh_profile_dialog = MagicMock(return_value=dialog)
    plugin._extract_polylines = MagicMock(return_value=[line])
    plugin._append_substrate_profile = MagicMock()
    plugin._append_mesh_profile = MagicMock()

    plugin._add_selected_mesh_profiles()

    plugin._append_substrate_profile.assert_called_once_with(line, "volume", "Sediment1")
    plugin._append_mesh_profile.assert_not_called()
