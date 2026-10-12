from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import Delft3DFileManager.Delft3DFileManager as plugin_module


def _point_layer(plugin, attributes):
    layer = MagicMock()
    layer.type.return_value = plugin_module.QgsMapLayerType.VectorLayer
    layer.geometryType.return_value = plugin_module.QgsWkbTypes.GeometryType.PointGeometry
    layer.fields.return_value = [
        SimpleNamespace(name=lambda name=name: name) for name in attributes
    ]
    plugin.iface.activeLayer.return_value = layer
    return layer


def _feature(attributes, coordinates):
    feature = MagicMock()
    feature.__getitem__.side_effect = attributes.__getitem__
    geometry = feature.geometry.return_value
    geometry.isEmpty.return_value = False
    points = []
    for x, y in coordinates:
        point = MagicMock()
        point.x.return_value = x
        point.y.return_value = y
        points.append(point)
    geometry.isMultipart.return_value = len(points) > 1
    geometry.asPoint.return_value = points[0]
    geometry.asMultiPoint.return_value = points
    return feature


@pytest.mark.parametrize("schema", ["xyn", "bridge", "weir", "both", "partial"])
def test_general_export_point_format_and_contents(plugin, tmp_path, schema):
    attributes = {"name": "station_a"}
    bridge = {"BRIDGE_NAME": "bridge_a", "Width": 2.5, "DRAG_CD": 1.0}
    weir = dict(zip(
        plugin._fixed_weir_field_names(),
        ["weir_a", 1.0, 0.0, 5.71, 10.0, 4.0, 4.0, 0.0],
    ))
    if schema in ("bridge", "both"):
        attributes.update(bridge)
    if schema in ("weir", "both"):
        attributes.update({key.upper(): value for key, value in weir.items()})
    if schema == "partial":
        attributes.update({"bridge_name": "unfinished", "width": 2.5})
    layer = _point_layer(plugin, attributes)
    layer.getFeatures.return_value = [
        _feature(attributes, [(120000.0, 450000.0), (120100.0, 450100.0)])
    ]
    output = tmp_path / "export"

    with patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=(str(output), "")):
        plugin.export_active_layer()

    if schema in ("weir", "both"):
        expected = (
            "weir_a:\n2 9\n"
            "120000.000000 450000.000000 1.000000 0.000000 5.710000 10.000000 4.000000 4.000000 0.000000\n"
            "120100.000000 450100.000000 1.000000 0.000000 5.710000 10.000000 4.000000 4.000000 0.000000\n"
        )
        extension = ".pliz"
    elif schema == "bridge":
        expected = (
            "bridge_a\n2 4\n"
            "120000.000000 450000.000000 2.500000 1.000000\n"
            "120100.000000 450100.000000 2.500000 1.000000\n"
        )
        extension = ".pliz"
    else:
        expected = (
            "120000.000000 450000.000000 station_a\n"
            "120100.000000 450100.000000 station_a\n"
        )
        extension = ".xyn"
    assert output.with_suffix(extension).read_text(encoding="ascii") == expected
    assert not output.with_suffix(".xyn" if extension == ".pliz" else ".pliz").exists()
    plugin.iface.messageBar().pushSuccess.assert_called_once()
    plugin.iface.messageBar().pushWarning.assert_not_called()


@pytest.mark.parametrize("names", [
    ["station_a", "station_b"],
    ["", None],
    ["station_\u00e9", "station_b"],
])
def test_general_xyn_export_names_and_coordinates(plugin, tmp_path, names):
    layer = _point_layer(plugin, {"x": 0, "y": 0, "NAME": ""})
    layer.getFeatures.return_value = [
        _feature({"x": 0, "y": 0, "NAME": name}, [(1.1234567 + index, 2.0)])
        for index, name in enumerate(names)
    ]
    output = tmp_path / "stations.XYN"
    with patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=(str(output), "")) as dialog:
        plugin.export_active_layer()

    expected_names = [
        name if name and name.isascii() else f"obs_{index + 1}"
        for index, name in enumerate(names)
    ]
    assert output.read_text(encoding="ascii").splitlines() == [
        f"{1.1234567 + index:.6f} 2.000000 {name}"
        for index, name in enumerate(expected_names)
    ]
    assert "x y name" in dialog.call_args.args[1]
    assert "XYN" in plugin.iface.messageBar().pushSuccess.call_args.args[1]


def test_general_xyn_export_cancelled(plugin, tmp_path):
    layer = _point_layer(plugin, {"name": ""})
    with patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=("", "")):
        plugin.export_active_layer()
    layer.getFeatures.assert_not_called()
    plugin.iface.messageBar().pushSuccess.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_general_xyn_export_empty_geometry_warns(plugin, tmp_path):
    layer = _point_layer(plugin, {"name": ""})
    feature = MagicMock()
    feature.geometry.return_value.isEmpty.return_value = True
    layer.getFeatures.return_value = [feature]
    output = tmp_path / "empty.xyn"
    with patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=(str(output), "")), \
         patch.object(plugin_module.QMessageBox, "warning") as warning:
        plugin.export_active_layer()
    warning.assert_called_once()
    plugin.iface.messageBar().pushSuccess.assert_not_called()


@pytest.mark.parametrize("schema", ["bridge", "weir"])
def test_general_export_invalid_specialized_values_do_not_fall_back_to_xyn(plugin, tmp_path, schema):
    if schema == "bridge":
        attributes = {"bridge_name": "bridge_a", "width": "invalid", "drag_cd": 1.0}
    else:
        attributes = dict(zip(
            plugin._fixed_weir_field_names(),
            ["weir_a", "invalid", 0.0, 5.71, 10.0, 4.0, 4.0, 0.0],
        ))
    layer = _point_layer(plugin, attributes)
    layer.getFeatures.return_value = [_feature(attributes, [(1.0, 2.0)])]
    output = tmp_path / "invalid"
    with patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=(str(output), "")), \
         patch.object(plugin_module.QMessageBox, "warning") as warning:
        plugin.export_active_layer()
    warning.assert_called_once()
    plugin.iface.messageBar().pushSuccess.assert_not_called()
    assert not list(tmp_path.iterdir())
