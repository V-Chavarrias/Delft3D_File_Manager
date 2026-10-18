from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from Delft3DFileManager import large_map_viewer as module


def test_default_variable_prefers_water_level_then_first_entry():
    entries = [
        SimpleNamespace(key="mesh:velocity", derived=False),
        SimpleNamespace(key="mesh:s1", derived=False),
    ]

    assert module.default_variable_key(entries) == "mesh:s1"
    assert module.default_variable_key([]) is None


def test_dataset_name_includes_time_and_extra_dimension_labels():
    entry = SimpleNamespace(
        key="mesh:velocity",
        derived=False,
        has_time=True,
    )

    assert (
        module.dataset_name(entry, "2020-01-01 00:00", ["Sediment 1"])
        == "mesh:velocity_2020-01-01_00:00_Sediment_1"
    )


def test_crs_from_info_uses_valid_epsg_then_wkt_then_default():
    valid_epsg = MagicMock()
    valid_epsg.isValid.return_value = True
    wkt_crs = MagicMock()
    wkt_crs.isValid.return_value = True
    default_crs = MagicMock()

    with patch.object(
        module,
        "QgsCoordinateReferenceSystem",
        side_effect=[valid_epsg, default_crs],
    ) as crs:
        crs.fromWkt.return_value = wkt_crs
        assert module.crs_from_info(4326, "wkt") is valid_epsg
        assert module.crs_from_info(None, "wkt") is wkt_crs
        assert module.crs_from_info(None, None) is default_crs
    assert crs.call_count == 2


def test_variable_change_updates_extra_dimensions_and_time_state():
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.dialog.selected_extra_indices.return_value = [1]
    viewer.entries = {
        "velocity": SimpleNamespace(
            has_time=True,
            extra_dims=[SimpleNamespace(name="sediment", labels=["A", "B"])],
        )
    }
    viewer.time_values = [0.0]
    viewer.time_labels = ["t0"]

    viewer.on_variable_changed("velocity")

    viewer.dialog.set_extra_dimensions.assert_called_once_with(
        [("sediment", ["A", "B"])], [1]
    )
    viewer.dialog.set_controls_enabled.assert_called_once_with(True)
    viewer.dialog.set_time_enabled.assert_called_once_with(True)
    viewer.dialog.set_point_series_enabled.assert_called_once_with(True)


def test_variable_change_disables_controls_for_unknown_variable():
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.entries = {}

    viewer.on_variable_changed("missing")

    viewer.dialog.set_extra_dimensions.assert_called_once_with([])
    viewer.dialog.set_controls_enabled.assert_called_once_with(False)
    viewer.dialog.set_point_series_enabled.assert_called_once_with(False)


def test_variable_change_keeps_point_action_available_for_static_message():
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.entries = {
        "node_z": SimpleNamespace(
            has_time=False,
            extra_dims=[],
        )
    }

    viewer.on_variable_changed("node_z")

    viewer.dialog.set_point_series_enabled.assert_called_once_with(True)


def test_plot_reports_missing_selection_and_layer_set():
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.dialog.selected_variable.return_value = "missing"
    viewer.entries = {}
    viewer.layer_set = MagicMock()

    assert viewer.plot() is False
    viewer.dialog.set_message.assert_called_once_with("Select a variable to plot.")


def test_plot_reads_values_updates_layers_and_refreshes_canvas():
    iface = MagicMock()
    viewer = module.LargeMapViewer(iface)
    viewer.dialog = MagicMock()
    viewer.dialog.selected_variable.return_value = "velocity"
    viewer.dialog.selected_time_index.return_value = 0
    viewer.dialog.selected_extra_indices.return_value = []
    viewer.entries = {
        "velocity": SimpleNamespace(
            key="velocity",
            label="Velocity",
            derived=False,
            has_time=True,
            extra_dims=[],
            location="face",
        )
    }
    viewer.time_labels = ["t0"]
    viewer.grids = [MagicMock()]
    viewer.layer_set = MagicMock()
    viewer.layer_set.plot.return_value = (1.0, 3.0)
    viewer.read_values = MagicMock(return_value=[[1.0, 2.0]])
    viewer._set_busy = MagicMock()

    assert viewer.plot() is True
    viewer.read_values.assert_called_once()
    viewer.layer_set.plot.assert_called_once()
    iface.mapCanvas.return_value.refresh.assert_called_once_with()
    assert "Plotted Velocity" in viewer.dialog.set_message.call_args.args[0]


def test_point_series_reads_all_times_and_opens_separate_chart(monkeypatch):
    from Delft3DFileManager import mesh_profile_sampler

    viewer = module.LargeMapViewer(MagicMock(), plugin=SimpleNamespace(_sediment_records=[]))
    viewer.dialog = MagicMock()
    viewer.entries = {
        "velocity": SimpleNamespace(
            key="velocity",
            label="Velocity",
            has_time=True,
            location=module.reader.FACE,
            extra_dims=[],
        )
    }
    viewer.time_values = [0.0, 1.0, 2.0]
    viewer.grids = [SimpleNamespace(face_index=[17], node_index=[3])]
    viewer.layer_set = SimpleNamespace(layers=[MagicMock()])
    viewer._point_in_mesh_crs = MagicMock(
        return_value=SimpleNamespace(x=lambda: 10.0, y=lambda: 20.0)
    )
    viewer._set_busy = MagicMock()
    chart = MagicMock()
    viewer._ensure_point_series_dialog = MagicMock(return_value=chart)
    nearest = MagicMock(return_value=[(0, 0, (10.0, 20.0))])
    read_series = MagicMock(return_value=[2.0, 3.0, 4.0])
    monkeypatch.setattr(mesh_profile_sampler, "nearest_mesh_sample_candidates", nearest)
    monkeypatch.setattr(module.reader, "read_point_series", read_series)

    assert viewer.plot_point_series((10.0, 20.0), "velocity") is True

    nearest.assert_called_once_with(viewer.grids, (10.0, 20.0), module.reader.FACE)
    read_series.assert_called_once_with(
        viewer.grids[0],
        viewer.entries["velocity"],
        17,
        [],
        [],
    )
    chart.set_profile.assert_called_once_with(
        [(0.0, 2.0), (1.0, 3.0), (2.0, 4.0)],
        "Velocity at (10, 20)",
        {"x_axis_label": "time", "y_axis_label": "Velocity"},
        message="",
    )
    chart.show.assert_called_once_with()
    viewer._set_busy.assert_any_call(True)
    viewer._set_busy.assert_any_call(False)


def test_point_series_rejects_static_variable_with_clear_message():
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.entries = {
        "node_z": SimpleNamespace(key="node_z", label="Bed elevation", has_time=False)
    }
    viewer.time_values = [0.0, 1.0]
    viewer.layer_set = MagicMock()

    assert viewer.plot_point_series((0.0, 0.0), "node_z") is False
    viewer.dialog.set_message.assert_called_once_with(
        "The selected variable has no temporal samples."
    )


def test_point_series_action_uses_one_map_click(monkeypatch):
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.dialog.selected_variable.return_value = "water_level"
    viewer.dialog.selected_extra_indices.return_value = [1]
    viewer.entries = {
        "water_level": SimpleNamespace(
            key="water_level",
            label="Water level",
            has_time=True,
        )
    }
    viewer.time_values = [0.0, 1.0]
    canvas = MagicMock()
    previous_tool = object()
    canvas.mapTool.return_value = previous_tool
    point = SimpleNamespace(x=lambda: 5.0, y=lambda: 6.0)
    canvas.getCoordinateTransform.return_value.toMapCoordinates.return_value = point
    viewer.iface.mapCanvas.return_value = canvas
    viewer.plot_point_series = MagicMock()
    monkeypatch.setattr(module, "Qt", SimpleNamespace(LeftButton=1))

    assert viewer.start_point_series_capture() is True
    tool = viewer._point_map_tool
    canvas.mapTool.return_value = tool
    event = MagicMock()
    event.button.return_value = 1
    event.pos.return_value.x.return_value = 10
    event.pos.return_value.y.return_value = 12

    tool.canvasPressEvent(event)

    viewer.plot_point_series.assert_called_once_with(
        point,
        "water_level",
        [1],
    )
    assert viewer._point_map_tool is None
    canvas.setMapTool.assert_called_with(previous_tool)


def test_large_map_point_is_transformed_to_grid_crs(monkeypatch):
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
            return _Point(point.x() - 3, point.y() + 8)

    canvas_crs = MagicMock()
    canvas_crs.isValid.return_value = True
    mesh_crs = MagicMock()
    mesh_crs.isValid.return_value = True
    viewer = module.LargeMapViewer(MagicMock())
    viewer.layer_set = SimpleNamespace(layers=[SimpleNamespace(crs=lambda: mesh_crs)])
    viewer.iface.mapCanvas.return_value.mapSettings.return_value.destinationCrs.return_value = canvas_crs
    monkeypatch.setattr(qgis_core, "QgsPointXY", _Point, raising=False)
    monkeypatch.setattr(module, "QgsCoordinateTransform", _Transform)
    monkeypatch.setattr(module, "QgsProject", SimpleNamespace(instance=lambda: object()))

    transformed = viewer._point_in_mesh_crs(_Point(10, 20))

    assert (transformed.x(), transformed.y()) == (7, 28)
