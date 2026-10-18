from types import SimpleNamespace
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
    crs = MagicMock()
    crs.isValid.return_value = True
    layer.crs.return_value = crs
    plugin.iface.mapCanvas.return_value.mapSettings.return_value.destinationCrs.return_value = crs
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


def test_selected_point_features_append_named_point_series(plugin):
    first = MagicMock()
    first.id.return_value = 7
    first_point = MagicMock()
    first.geometry.return_value.vertices.return_value = [first_point]
    second = MagicMock()
    second.id.return_value = 8
    second_points = [MagicMock(), MagicMock()]
    second.geometry.return_value.vertices.return_value = second_points
    layer = MagicMock()
    layer.getSelectedFeatures.return_value = [first, second]
    plugin._selected_mesh_profile_point_layer = MagicMock(return_value=layer)
    plugin._mesh_profile_display_points = MagicMock(
        side_effect=lambda _layer, points: points
    )
    plugin._append_mesh_point_series = MagicMock()

    plugin._add_selected_mesh_point_series()

    plugin._append_mesh_point_series.assert_called_once_with(
        [first_point, *second_points],
        ["Feature 7", "Feature 8 point 1", "Feature 8 point 2"],
    )


def test_append_mesh_point_series_replaces_chart_with_temporal_profiles(plugin, monkeypatch):
    import qgis.core

    class _DatasetValue:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

    point = SimpleNamespace(x=lambda: 0.0, y=lambda: 0.0)
    grid = SimpleNamespace(
        node_x=np.asarray([0.0, 1.0]),
        node_y=np.asarray([0.0, 0.0]),
        faces=np.asarray([[0, 1, 1]]),
    )
    layer = SimpleNamespace(
        datasetValue=lambda dataset_index, _point: _DatasetValue(
            {(2, 0): 1.5, (2, 1): 2.5}[tuple(dataset_index)]
        )
    )
    metadata = SimpleNamespace(
        name=lambda: "Water level",
        extraOptions=lambda: {"units": "m"},
    )
    dialog = MagicMock()
    plugin._mesh_profile_source_layers = [layer]
    plugin._mesh_profile_temporal_group = MagicMock(
        return_value=(2, metadata, [(2, 0), (2, 1)], [0.0, 1.0], "node")
    )
    plugin._mesh_profile_point_in_mesh_crs = MagicMock(return_value=point)
    plugin._mesh_profile_point_sample_grids = MagicMock(return_value=[grid])
    plugin._prepare_mesh_profile_layers = MagicMock()
    plugin._ensure_mesh_profile_dialog = MagicMock(return_value=dialog)
    monkeypatch.setattr(qgis.core, "QgsPointXY", lambda x, y: (x, y))

    plugin._append_mesh_point_series([point], ["Map point"])

    dialog.set_profiles.assert_called_once_with(
        [{"points": [(0.0, 1.5), (1.0, 2.5)], "label": "Map point"}],
        "Point time series",
        {"x_axis_label": "time [h]", "y_axis_label": "Water level [m]"},
        message="",
    )
    dialog.reset_view.assert_called_once_with()


def test_mesh_profile_temporal_group_reports_static_data(plugin, monkeypatch):
    import qgis.core

    class _DatasetIndex:
        def __init__(self, group, dataset=0):
            self.group = group
            self.dataset = dataset

    class _GroupMetadata:
        DataOnVertices = 1
        DataOnFaces = 2

        def isTemporal(self):
            return False

    class _DatasetGroupMetadata:
        DataOnVertices = 1
        DataOnFaces = 2

    metadata = _GroupMetadata()
    layer = SimpleNamespace(
        activeScalarDatasetGroup=lambda: 2,
        datasetGroupMetadata=lambda _index: metadata,
        datasetCount=lambda _index: 1,
    )
    plugin._show_mesh_profile_message = MagicMock()
    monkeypatch.setattr(qgis.core, "QgsMeshDatasetIndex", _DatasetIndex, raising=False)
    monkeypatch.setattr(
        qgis.core,
        "QgsMeshDatasetGroupMetadata",
        _DatasetGroupMetadata,
        raising=False,
    )

    assert plugin._mesh_profile_temporal_group(layer) is None
    assert "static" in plugin._show_mesh_profile_message.call_args.args[0].lower()


def test_mesh_point_capture_samples_after_one_canvas_click(plugin, monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    canvas = MagicMock()
    previous_tool = object()
    canvas.mapTool.return_value = previous_tool
    point = SimpleNamespace(x=lambda: 3.0, y=lambda: 4.0)
    canvas.getCoordinateTransform.return_value.toMapCoordinates.return_value = point
    plugin.iface.mapCanvas.return_value = canvas
    plugin._mesh_profile_source_layers = [MagicMock()]
    plugin._ensure_mesh_profile_dialog = MagicMock(return_value=MagicMock())
    plugin._append_mesh_point_series = MagicMock()
    monkeypatch.setattr(plugin_module, "_left_mouse_button_value", lambda: 1, raising=False)

    plugin._start_mesh_point_capture()
    tool = plugin._mesh_point_map_tool
    canvas.mapTool.return_value = tool
    event = MagicMock()
    event.button.return_value = 1
    event.pos.return_value.x.return_value = 6
    event.pos.return_value.y.return_value = 8

    tool.canvasPressEvent(event)

    plugin._append_mesh_point_series.assert_called_once_with([point], ["Map point"])
    assert plugin._mesh_point_map_tool is None
    canvas.setMapTool.assert_called_with(previous_tool)


def test_mesh_profile_point_is_transformed_from_canvas_to_mesh_crs(plugin, monkeypatch):
    import sys

    qgis_core = sys.modules["qgis.core"]

    class _Point:
        def __init__(self, x, y):
            self._x = x
            self._y = y

        def x(self):
            return self._x

        def y(self):
            return self._y

    class _Transform:
        def __init__(self, *_args):
            pass

        def transform(self, point):
            return _Point(point.x() + 10, point.y() - 5)

    canvas_crs = MagicMock()
    canvas_crs.isValid.return_value = True
    mesh_crs = MagicMock()
    mesh_crs.isValid.return_value = True
    plugin.iface.mapCanvas.return_value.mapSettings.return_value.destinationCrs.return_value = canvas_crs
    layer = MagicMock()
    layer.crs.return_value = mesh_crs
    monkeypatch.setattr(qgis_core, "QgsPointXY", _Point, raising=False)
    monkeypatch.setattr(qgis_core, "QgsCoordinateTransform", _Transform, raising=False)
    monkeypatch.setattr(
        qgis_core,
        "QgsProject",
        SimpleNamespace(instance=lambda: object()),
        raising=False,
    )

    transformed = plugin._mesh_profile_point_in_mesh_crs(_Point(2, 7), layer)

    assert (transformed.x(), transformed.y()) == (12, 2)
