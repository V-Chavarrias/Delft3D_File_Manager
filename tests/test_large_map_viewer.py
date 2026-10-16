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
    viewer.time_labels = ["t0"]

    viewer.on_variable_changed("velocity")

    viewer.dialog.set_extra_dimensions.assert_called_once_with(
        [("sediment", ["A", "B"])], [1]
    )
    viewer.dialog.set_controls_enabled.assert_called_once_with(True)
    viewer.dialog.set_time_enabled.assert_called_once_with(True)


def test_variable_change_disables_controls_for_unknown_variable():
    viewer = module.LargeMapViewer(MagicMock())
    viewer.dialog = MagicMock()
    viewer.entries = {}

    viewer.on_variable_changed("missing")

    viewer.dialog.set_extra_dimensions.assert_called_once_with([])
    viewer.dialog.set_controls_enabled.assert_called_once_with(False)


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
