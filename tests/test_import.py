import sys
import pathlib
import shutil
from datetime import datetime
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
FXW_01 = DATA_DIR / "fxw_01.pliz"
PLI_01 = DATA_DIR / "pli_01.pli"
XYZ_01 = DATA_DIR / "xyz_01.xyz"
CSL_01 = DATA_DIR / "csl.ini"
CSD_01 = DATA_DIR / "csd.ini"
GRID_01 = DATA_DIR / "grd_net.nc"
MORPHO_01 = DATA_DIR / "morpho_small.nc"
MIXED_1D2D_01 = DATA_DIR / "mixed_1d2d_small.nc"
BRIDGES_01 = DATA_DIR / "bridges.pliz"
MODEL_01_DIMR = DATA_DIR / "model_01" / "dimr_config.xml"

# Access the explicitly registered qgis.core stub directly.
_qgis_core = sys.modules["qgis.core"]


def _add_map_layer_mock():
    """Return the consistent addMapLayer mock from the qgis.core stub."""
    return _qgis_core.QgsProject.instance.return_value.addMapLayer


# ---------------------------------------------------------------------------
# Extension routing tests (load_file_by_extension)
# ---------------------------------------------------------------------------

def test_route_fxw(plugin):
    plugin.load_fixed_weir_file = MagicMock()
    plugin.load_polyline_file = MagicMock()
    plugin.load_xyn_file = MagicMock()

    plugin.load_file_by_extension("/fake/file.fxw")

    plugin.load_fixed_weir_file.assert_called_once_with("/fake/file.fxw")
    plugin.load_polyline_file.assert_not_called()
    plugin.load_xyn_file.assert_not_called()


def test_route_pli(plugin):
    plugin.load_fixed_weir_file = MagicMock()
    plugin.load_polyline_file = MagicMock()

    plugin.load_file_by_extension(str(PLI_01))

    plugin.load_polyline_file.assert_called_once_with(str(PLI_01))
    plugin.load_fixed_weir_file.assert_not_called()


def test_route_ldb(plugin):
    plugin.load_polyline_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.ldb")
    plugin.load_polyline_file.assert_called_once_with("/fake/file.ldb")


def test_route_pol(plugin):
    plugin.load_polyline_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.pol")
    plugin.load_polyline_file.assert_called_once_with("/fake/file.pol")


def test_route_pliz_fixed_weir(plugin):
    plugin.load_fixed_weir_file = MagicMock()
    plugin.load_polyline_file = MagicMock()

    plugin.load_file_by_extension(str(FXW_01))

    plugin.load_fixed_weir_file.assert_called_once_with(str(FXW_01))
    plugin.load_polyline_file.assert_not_called()


def test_route_pliz_polyline(plugin):
    plugin.load_fixed_weir_file = MagicMock()
    plugin.load_polyline_file = MagicMock()
    plugin.load_bridge_file = MagicMock()

    with patch.object(plugin, "_pliz_column_count", return_value=2):
        plugin.load_file_by_extension("/fake/file.pliz")

    plugin.load_polyline_file.assert_called_once_with("/fake/file.pliz")
    plugin.load_fixed_weir_file.assert_not_called()
    plugin.load_bridge_file.assert_not_called()


def test_route_pliz_bridge(plugin):
    plugin.load_fixed_weir_file = MagicMock()
    plugin.load_polyline_file = MagicMock()
    plugin.load_bridge_file = MagicMock()

    with patch.object(plugin, "_pliz_column_count", return_value=4):
        plugin.load_file_by_extension("/fake/file.pliz")

    plugin.load_bridge_file.assert_called_once_with("/fake/file.pliz")
    plugin.load_fixed_weir_file.assert_not_called()
    plugin.load_polyline_file.assert_not_called()


def test_route_xyn(plugin):
    plugin.load_xyn_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.xyn")
    plugin.load_xyn_file.assert_called_once_with("/fake/file.xyn")


def test_route_xyz(plugin):
    plugin.load_xyz_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.xyz")
    plugin.load_xyz_file.assert_called_once_with("/fake/file.xyz")


def test_close_progress_dialog_survives_partial_cleanup_failures(plugin):
    class _Dialog:
        def __init__(self):
            self.closed = False
            self.hidden = False
            self.reset_called = False
            self.deleted = False

        def setValue(self, value):
            raise RuntimeError("simulated Qt error")

        def reset(self):
            self.reset_called = True

        def hide(self):
            self.hidden = True

        def close(self):
            self.closed = True

        def deleteLater(self):
            self.deleted = True

    dialog = _Dialog()
    plugin._active_progress_dialog = dialog

    plugin._close_progress_dialog(dialog)

    assert dialog.reset_called is True
    assert dialog.hidden is True
    assert dialog.closed is True
    assert dialog.deleted is True
    assert plugin._active_progress_dialog is None


def test_route_csl(plugin):
    plugin.load_cross_sections_from_selection = MagicMock()
    plugin.load_file_by_extension("/fake/file.csl")
    plugin.load_cross_sections_from_selection.assert_called_once_with("/fake/file.csl")


def test_route_csd(plugin):
    plugin.load_cross_sections_from_selection = MagicMock()
    plugin.load_file_by_extension("/fake/file.csd")
    plugin.load_cross_sections_from_selection.assert_called_once_with("/fake/file.csd")


def test_route_dimr_config_xml(plugin):
    plugin.load_dimr_config_file = MagicMock()

    plugin.load_file_by_extension("/fake/dimr_config.xml")

    plugin.load_dimr_config_file.assert_called_once_with("/fake/dimr_config.xml", spatial_grid_path=None)


def test_route_mdu(plugin):
    plugin.load_fm_mdu_file = MagicMock()

    plugin.load_file_by_extension("/fake/model.mdu")

    plugin.load_fm_mdu_file.assert_called_once_with("/fake/model.mdu", import_referenced=True, spatial_grid_path=None)


def test_route_ext(plugin):
    plugin.load_ext_file = MagicMock()

    plugin.load_file_by_extension("/fake/forcing.ext")

    plugin.load_ext_file.assert_called_once_with("/fake/forcing.ext", grid_path=None)


def test_route_bc(plugin):
    plugin.load_bc_file = MagicMock()

    plugin.load_file_by_extension("/fake/forcing.bc")

    plugin.load_bc_file.assert_called_once_with("/fake/forcing.bc")


def test_route_ini_extforce(plugin):
    plugin.load_ext_file = MagicMock()
    plugin.load_ini_table_file = MagicMock()

    with patch.object(plugin, "_detect_ini_file_type", return_value="extforce"):
        plugin.load_file_by_extension("/fake/forcing.ini")

    plugin.load_ext_file.assert_called_once_with("/fake/forcing.ini", grid_path=None)
    plugin.load_ini_table_file.assert_not_called()


def test_route_ini_generic_table(plugin):
    plugin.load_roughness_spatial_file = MagicMock()

    with patch.object(plugin, "_detect_ini_file_type", return_value="roughness"):
        plugin.load_file_by_extension("/fake/roughness.ini")

    plugin.load_roughness_spatial_file.assert_called_once_with("/fake/roughness.ini", grid_path=None)


def test_route_ini_structure(plugin):
    plugin.load_structures_spatial_file = MagicMock()

    with patch.object(plugin, "_detect_ini_file_type", return_value="structure"):
        plugin.load_file_by_extension("/fake/structures.ini")

    plugin.load_structures_spatial_file.assert_called_once_with("/fake/structures.ini", grid_path=None)


def test_route_ini_inifield(plugin):
    plugin.load_ini_field_spatial_file = MagicMock()

    with patch.object(plugin, "_detect_ini_file_type", return_value="inifield"):
        plugin.load_file_by_extension("/fake/initialFields.ini")

    plugin.load_ini_field_spatial_file.assert_called_once_with("/fake/initialFields.ini", grid_path=None)


def test_route_ini_1dfield(plugin):
    plugin.load_1d_field_spatial_file = MagicMock()

    with patch.object(plugin, "_detect_ini_file_type", return_value="1dfield"):
        plugin.load_file_by_extension("/fake/InitialWaterLevel.ini")

    plugin.load_1d_field_spatial_file.assert_called_once_with("/fake/InitialWaterLevel.ini", grid_path=None)


def test_route_unknown(plugin):
    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_file_by_extension("/fake/file.abc")
    mock_mb.warning.assert_called_once()


def test_export_active_layer_uses_bridge_export_for_bridge_point_layer(plugin):
    point_layer = MagicMock()
    point_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    point_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.PointGeometry
    plugin.iface.activeLayer.return_value = point_layer

    with patch.object(plugin, "_is_fixed_weir_point_layer", return_value=False), \
         patch.object(plugin, "_is_bridge_point_layer", return_value=True), \
         patch.object(plugin, "export_bridge_pliz") as bridge_export_mock, \
         patch.object(plugin, "export_fixed_weir_pliz") as fixed_weir_export_mock:
        plugin.export_active_layer()

    bridge_export_mock.assert_called_once_with(point_layer)
    fixed_weir_export_mock.assert_not_called()


def test_export_active_layer_line_layer_uses_polyline_export(plugin):
    line_layer = MagicMock()
    line_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    line_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    plugin.iface.activeLayer.return_value = line_layer

    with patch.object(plugin, "export_bridge_pliz") as bridge_export_mock, \
         patch.object(plugin, "export_lines") as export_lines_mock:
        plugin.export_active_layer()

    bridge_export_mock.assert_not_called()
    export_lines_mock.assert_called_once()


def test_export_active_layer_falls_back_to_line_export_without_bridge_companion(plugin):
    line_layer = MagicMock()
    line_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    line_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    plugin.iface.activeLayer.return_value = line_layer

    with patch.object(plugin, "export_bridge_pliz") as bridge_export_mock, \
         patch.object(plugin, "export_lines") as export_lines_mock:
        plugin.export_active_layer()

    bridge_export_mock.assert_not_called()
    export_lines_mock.assert_called_once()


def test_create_bridge_points_from_polyline_requires_line_layer(plugin):
    active_layer = MagicMock()
    active_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    active_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.PointGeometry
    plugin.iface.activeLayer.return_value = active_layer

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.create_bridge_points_from_polyline()

    mock_mb.warning.assert_called_once()


def test_create_bridge_points_from_polyline_cancelled_dialog(plugin):
    active_layer = MagicMock()
    active_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    active_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    plugin.iface.activeLayer.return_value = active_layer

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch("Delft3DFileManager.Delft3DFileManager.QInputDialog") as mock_dialog:
        mock_dialog.getDouble.return_value = (0.0, False)
        plugin.create_bridge_points_from_polyline()

    add_map_layer.assert_not_called()


def test_create_bridge_points_from_polyline_creates_points(plugin):
    feature = MagicMock()
    feature.id.return_value = 1
    feature.__getitem__.return_value = "bridge_a"
    feature.geometry.return_value.isEmpty.return_value = False

    active_layer = MagicMock()
    active_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    active_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    active_layer.getFeatures.return_value = [feature]
    active_layer.name.return_value = "bridges"
    active_layer.crs.return_value.isValid.return_value = False
    plugin.iface.activeLayer.return_value = active_layer

    p1, p2, p3 = MagicMock(), MagicMock(), MagicMock()
    p1.x.return_value, p1.y.return_value = 100.0, 200.0
    p2.x.return_value, p2.y.return_value = 110.0, 210.0
    p3.x.return_value, p3.y.return_value = 120.0, 220.0

    point_layer = MagicMock()
    provider = MagicMock()
    point_layer.dataProvider.return_value = provider
    point_layer.fields.return_value = MagicMock()

    created_features = [MagicMock(), MagicMock(), MagicMock()]

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_extract_polylines", return_value=[[p1, p2, p3]]), \
         patch("Delft3DFileManager.Delft3DFileManager.QInputDialog") as mock_dialog, \
         patch("Delft3DFileManager.Delft3DFileManager.QgsVectorLayer", return_value=point_layer) as mock_vec_layer, \
         patch("Delft3DFileManager.Delft3DFileManager.QgsFeature", side_effect=created_features):
        mock_dialog.getDouble.side_effect = [(2.5, True), (1.0, True)]
        plugin.create_bridge_points_from_polyline()

    mock_vec_layer.assert_called_once_with("Point?crs=EPSG:28992", "bridges_points", "memory")
    provider.addFeatures.assert_called_once()
    exported_features = provider.addFeatures.call_args[0][0]
    assert len(exported_features) == 3
    created_features[0].setAttributes.assert_called_once_with(["bridges", 2.5, 1.0])
    add_map_layer.assert_called_once_with(point_layer)
    plugin.iface.messageBar.return_value.pushSuccess.assert_called_once()


def test_create_fixed_weir_points_from_polyline_requires_line_layer(plugin):
    active_layer = MagicMock()
    active_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    active_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.PointGeometry
    plugin.iface.activeLayer.return_value = active_layer

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.create_fixed_weir_points_from_polyline()

    mock_mb.warning.assert_called_once()


def test_create_fixed_weir_points_from_polyline_cancelled_dialog(plugin):
    active_layer = MagicMock()
    active_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    active_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    plugin.iface.activeLayer.return_value = active_layer

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch("Delft3DFileManager.Delft3DFileManager.QInputDialog") as mock_dialog:
        mock_dialog.getDouble.return_value = (0.0, False)
        plugin.create_fixed_weir_points_from_polyline()

    add_map_layer.assert_not_called()


def test_create_fixed_weir_points_from_polyline_creates_points(plugin):
    feature = MagicMock()
    feature.id.return_value = 1
    feature.__getitem__.return_value = "weir_a"
    feature.geometry.return_value.isEmpty.return_value = False

    active_layer = MagicMock()
    active_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    active_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    active_layer.getFeatures.return_value = [feature]
    active_layer.name.return_value = "weirs"
    active_layer.crs.return_value.isValid.return_value = False
    plugin.iface.activeLayer.return_value = active_layer

    p1, p2 = MagicMock(), MagicMock()
    p1.x.return_value, p1.y.return_value = 100.0, 200.0
    p2.x.return_value, p2.y.return_value = 110.0, 210.0

    point_layer = MagicMock()
    provider = MagicMock()
    point_layer.dataProvider.return_value = provider
    point_layer.fields.return_value = MagicMock()

    created_features = [MagicMock(), MagicMock()]

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_extract_polylines", return_value=[[p1, p2]]), \
         patch("Delft3DFileManager.Delft3DFileManager.QInputDialog") as mock_dialog, \
         patch("Delft3DFileManager.Delft3DFileManager.QgsVectorLayer", return_value=point_layer) as mock_vec_layer, \
         patch("Delft3DFileManager.Delft3DFileManager.QgsFeature", side_effect=created_features):
        mock_dialog.getDouble.side_effect = [
            (1.0, True),
            (0.0, True),
            (0.0, True),
            (10.0, True),
            (4.0, True),
            (4.0, True),
            (0.0, True),
        ]
        plugin.create_fixed_weir_points_from_polyline()

    mock_vec_layer.assert_called_once_with("Point?crs=EPSG:28992", "weirs_weir_points", "memory")
    provider.addFeatures.assert_called_once()
    exported_features = provider.addFeatures.call_args[0][0]
    assert len(exported_features) == 2
    created_features[0].setAttributes.assert_called_once_with(["weirs", 1.0, 0.0, 0.0, 10.0, 4.0, 4.0, 0.0])
    add_map_layer.assert_called_once_with(point_layer)
    plugin.iface.messageBar.return_value.pushSuccess.assert_called_once()


def test_load_bridge_file_adds_line_and_point_layers(plugin, tmp_path):
    src_path = tmp_path / "bridges.pliz"
    shutil.copyfile(BRIDGES_01, src_path)

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    plugin.load_bridge_file(str(src_path))

    assert add_map_layer.call_count == 2


def test_export_bridge_pliz_from_selected_layers(plugin, tmp_path):
    out = str(tmp_path / "bridges_out.pliz")

    line_layer = MagicMock()
    line_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    line_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    line_layer.name.return_value = "bridges"

    line_feature = MagicMock()
    line_feature.id.return_value = 1
    line_feature.__getitem__.return_value = "bridge_a"
    line_feature.geometry.return_value.isEmpty.return_value = False
    line_layer.getFeatures.return_value = [line_feature]

    p1 = MagicMock()
    p1.x.return_value = 120000.0
    p1.y.return_value = 450000.0
    p2 = MagicMock()
    p2.x.return_value = 120100.0
    p2.y.return_value = 450100.0

    point_layer = MagicMock()
    point_layer.name.return_value = "bridges_points"
    point_layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    point_layer.geometryType.return_value = _qgis_core.QgsWkbTypes.PointGeometry
    point_layer.fields.return_value = [
        SimpleNamespace(name=lambda: "bridge_name"),
        SimpleNamespace(name=lambda: "width"),
        SimpleNamespace(name=lambda: "drag_cd"),
    ]

    pf1 = MagicMock()
    pf1.geometry.return_value.isEmpty.return_value = False
    pf1.__getitem__.side_effect = lambda k: {"bridge_name": "bridge_a", "width": 2.5, "drag_cd": 1.0}[k]
    pf2 = MagicMock()
    pf2.geometry.return_value.isEmpty.return_value = False
    pf2.__getitem__.side_effect = lambda k: {"bridge_name": "bridge_a", "width": 2.5, "drag_cd": 1.0}[k]
    point_layer.getFeatures.return_value = [pf1, pf2]

    _qgis_core.QgsProject.instance.return_value.mapLayers.return_value = {"p": point_layer}

    with patch.object(plugin, "_selected_bridge_line_layers", return_value=[line_layer]), \
            patch.object(plugin, "_get_name_field", return_value="bridge_name"), \
         patch.object(plugin, "_extract_polylines", return_value=[[p1, p2]]), \
         patch.object(plugin, "_extract_points", side_effect=[[p1], [p2]]), \
         patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg:
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_bridge_pliz_from_selected_layers()

    lines = pathlib.Path(out).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "bridge_a"
    assert lines[1] == "2 4"
    assert lines[2] == "120000.000000 450000.000000 2.500000 1.000000"
    assert lines[3] == "120100.000000 450100.000000 2.500000 1.000000"


def test_export_bridge_pliz_from_point_layer(plugin, tmp_path):
    out = str(tmp_path / "bridges_from_points.pliz")

    layer = MagicMock()
    layer.fields.return_value = [
        SimpleNamespace(name=lambda: "bridge_name"),
        SimpleNamespace(name=lambda: "width"),
        SimpleNamespace(name=lambda: "drag_cd"),
    ]

    feature = MagicMock()
    feature.id.return_value = 1
    feature.geometry.return_value.isEmpty.return_value = False
    feature.__getitem__.side_effect = lambda k: {
        "bridge_name": "bridge_a",
        "width": 2.5,
        "drag_cd": 1.0,
    }[k]
    layer.getFeatures.return_value = [feature]

    p1 = MagicMock()
    p1.x.return_value = 120000.0
    p1.y.return_value = 450000.0
    p2 = MagicMock()
    p2.x.return_value = 120100.0
    p2.y.return_value = 450100.0

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", return_value=[p1, p2]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_bridge_pliz(layer)

    lines = pathlib.Path(out).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "bridge_a"
    assert lines[1] == "2 4"
    assert lines[2] == "120000.000000 450000.000000 2.500000 1.000000"
    assert lines[3] == "120100.000000 450100.000000 2.500000 1.000000"


def test_export_bridge_pliz_from_point_layer_multiple_groups(plugin, tmp_path):
    out = str(tmp_path / "bridges_grouped.pliz")

    layer = MagicMock()
    layer.fields.return_value = [
        SimpleNamespace(name=lambda: "bridge_name"),
        SimpleNamespace(name=lambda: "width"),
        SimpleNamespace(name=lambda: "drag_cd"),
    ]

    feature_a1 = MagicMock()
    feature_a1.id.return_value = 1
    feature_a1.geometry.return_value.isEmpty.return_value = False
    feature_a1.__getitem__.side_effect = lambda k: {
        "bridge_name": "bridge_a",
        "width": 2.5,
        "drag_cd": 1.0,
    }[k]

    feature_b1 = MagicMock()
    feature_b1.id.return_value = 2
    feature_b1.geometry.return_value.isEmpty.return_value = False
    feature_b1.__getitem__.side_effect = lambda k: {
        "bridge_name": "bridge_b",
        "width": 3.0,
        "drag_cd": 1.2,
    }[k]

    feature_a2 = MagicMock()
    feature_a2.id.return_value = 3
    feature_a2.geometry.return_value.isEmpty.return_value = False
    feature_a2.__getitem__.side_effect = lambda k: {
        "bridge_name": "bridge_a",
        "width": 2.5,
        "drag_cd": 1.0,
    }[k]

    layer.getFeatures.return_value = [feature_a1, feature_b1, feature_a2]

    p1 = MagicMock()
    p1.x.return_value = 120000.0
    p1.y.return_value = 450000.0
    p2 = MagicMock()
    p2.x.return_value = 120050.0
    p2.y.return_value = 450050.0
    p3 = MagicMock()
    p3.x.return_value = 130000.0
    p3.y.return_value = 460000.0
    p4 = MagicMock()
    p4.x.return_value = 120100.0
    p4.y.return_value = 450100.0

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", side_effect=[[p1], [p2, p3], [p4]]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_bridge_pliz(layer)

    lines = pathlib.Path(out).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "bridge_a"
    assert lines[1] == "2 4"
    assert lines[2] == "120000.000000 450000.000000 2.500000 1.000000"
    assert lines[3] == "120100.000000 450100.000000 2.500000 1.000000"
    assert lines[4] == "bridge_b"
    assert lines[5] == "2 4"
    assert lines[6] == "120050.000000 450050.000000 3.000000 1.200000"
    assert lines[7] == "130000.000000 460000.000000 3.000000 1.200000"


def test_export_bridge_pliz_from_point_layer_case_insensitive_fields(plugin, tmp_path):
    out = str(tmp_path / "bridges_case_insensitive.pliz")

    layer = MagicMock()
    layer.fields.return_value = [
        SimpleNamespace(name=lambda: "BRIDGE_NAME"),
        SimpleNamespace(name=lambda: "Width"),
        SimpleNamespace(name=lambda: "DRAG_CD"),
    ]

    feature = MagicMock()
    feature.id.return_value = 1
    feature.geometry.return_value.isEmpty.return_value = False
    feature.__getitem__.side_effect = lambda k: {
        "BRIDGE_NAME": "bridge_caps",
        "Width": 2.75,
        "DRAG_CD": 0.95,
    }[k]
    layer.getFeatures.return_value = [feature]

    p1 = MagicMock()
    p1.x.return_value = 120000.0
    p1.y.return_value = 450000.0
    p2 = MagicMock()
    p2.x.return_value = 120010.0
    p2.y.return_value = 450010.0

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", return_value=[p1, p2]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_bridge_pliz(layer)

    lines = pathlib.Path(out).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "bridge_caps"
    assert lines[1] == "2 4"
    assert lines[2] == "120000.000000 450000.000000 2.750000 0.950000"
    assert lines[3] == "120010.000000 450010.000000 2.750000 0.950000"


def test_load_fixed_weir_file_invalid_column_count_warns(plugin, tmp_path):
    bad = tmp_path / "bad_fixed_weir.pliz"
    bad.write_text("weir_a:\n2 8\n0 0 1 0 0 10 4 4\n1 1 1 0 0 10 4 4\n", encoding="utf-8")

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_fixed_weir_file(str(bad))

    mock_mb.warning.assert_called_once()


def test_load_ugrid_mesh_file_morphodynamic_flattens_selected_variables(plugin, tmp_path):
    netcdf4 = pytest.importorskip("netCDF4")

    src_path = tmp_path / "morpho_small.nc"
    shutil.copyfile(MORPHO_01, src_path)

    with patch.object(plugin, "_prompt_for_morphodynamic_variables", return_value=["sedfrac"]) as prompt_mock, \
         patch.object(plugin, "_load_mesh2d_layer") as load_mesh2d_mock:
        plugin.load_ugrid_mesh_file(str(src_path))

    prompt_mock.assert_called_once()
    load_mesh2d_mock.assert_called_once()

    loaded_mesh_path = pathlib.Path(load_mesh2d_mock.call_args[0][0])
    assert loaded_mesh_path.name == "morpho_small_qgis_flat.nc"
    assert loaded_mesh_path.exists()

    with netcdf4.Dataset(str(loaded_mesh_path), "r") as ds:
        flattened = [name for name in ds.variables.keys() if name.startswith("sedfrac_")]
        assert len(flattened) == 2
        for variable_name in flattened:
            assert len(ds.variables[variable_name].dimensions) <= 2


def test_load_ugrid_mesh_file_mixed_1d2d_regression(plugin, tmp_path):
    pytest.importorskip("netCDF4")

    src_path = tmp_path / "mixed_1d2d_small.nc"
    shutil.copyfile(MIXED_1D2D_01, src_path)

    with patch.object(plugin, "_prompt_for_morphodynamic_variables") as prompt_mock, \
         patch.object(plugin, "_load_mesh2d_layer") as load_mesh2d_mock, \
         patch.object(plugin, "_load_mesh1d_branches_layer") as load_mesh1d_mock:
        plugin.load_ugrid_mesh_file(str(src_path))

    prompt_mock.assert_not_called()
    load_mesh2d_mock.assert_called_once()
    load_mesh1d_mock.assert_called_once()

    node_x = load_mesh1d_mock.call_args[0][0]
    edges = load_mesh1d_mock.call_args[0][2]
    assert len(node_x) == 4
    assert len(edges) == 3


def test_load_ugrid_mesh_file_updates_status_messages(plugin, tmp_path):
    pytest.importorskip("netCDF4")

    src_path = tmp_path / "morpho_small.nc"
    shutil.copyfile(MORPHO_01, src_path)

    with patch.object(plugin, "_prompt_for_morphodynamic_variables", return_value=["sedfrac"]), \
         patch.object(plugin, "_load_mesh2d_layer"):
        plugin.load_ugrid_mesh_file(str(src_path))

    status_bar = plugin.iface.statusBarIface.return_value
    assert status_bar.showMessage.call_count > 0
    status_bar.clearMessage.assert_called()


def test_load_ugrid_mesh_file_clears_status_on_cancel(plugin, tmp_path):
    pytest.importorskip("netCDF4")

    src_path = tmp_path / "morpho_small.nc"
    shutil.copyfile(MORPHO_01, src_path)

    with patch.object(plugin, "_prompt_for_morphodynamic_variables", return_value=None):
        plugin.load_ugrid_mesh_file(str(src_path))

    status_bar = plugin.iface.statusBarIface.return_value
    status_bar.clearMessage.assert_called()


def test_load_ugrid_mesh_file_detects_lowercase_mesh2d_topology(plugin, tmp_path):
    netcdf4 = pytest.importorskip("netCDF4")

    src_path = tmp_path / "lowercase_mesh2d.nc"
    with netcdf4.Dataset(str(src_path), "w") as ds:
        ds.createDimension("mesh2d_nNodes", 3)
        ds.createDimension("mesh2d_nFaces", 1)
        ds.createDimension("nNodesPerFace", 3)
        ds.createDimension("time", 1)
        ds.createDimension("nSedTot", 2)

        mesh2d = ds.createVariable("mesh2d", "i4")
        mesh2d.cf_role = "mesh_topology"
        mesh2d.topology_dimension = 2
        mesh2d.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        mesh2d.face_node_connectivity = "mesh2d_face_nodes"

        node_x = ds.createVariable("mesh2d_node_x", "f8", ("mesh2d_nNodes",))
        node_y = ds.createVariable("mesh2d_node_y", "f8", ("mesh2d_nNodes",))
        face_nodes = ds.createVariable("mesh2d_face_nodes", "i4", ("mesh2d_nFaces", "nNodesPerFace"))
        sedfrac = ds.createVariable("mesh2d_frac", "f4", ("time", "mesh2d_nFaces", "nSedTot"))
        crs = ds.createVariable("projected_coordinate_system", "i4")

        node_x[:] = [0.0, 1.0, 0.0]
        node_y[:] = [0.0, 0.0, 1.0]
        face_nodes[:] = [[1, 2, 3]]
        sedfrac[:] = [[[0.7, 0.3]]]
        crs.EPSG_code = 28992

    with patch.object(plugin, "_prompt_for_morphodynamic_variables", return_value=["mesh2d_frac"]) as prompt_mock, \
         patch.object(plugin, "_load_mesh2d_layer") as load_mesh2d_mock:
        plugin.load_ugrid_mesh_file(str(src_path))

    prompt_mock.assert_called_once()
    load_mesh2d_mock.assert_called_once()

    loaded_path = pathlib.Path(load_mesh2d_mock.call_args[0][0])
    assert loaded_path.name.endswith("_qgis_flat.nc")


def test_load_ugrid_mesh_file_preserves_referenced_topology_variables(plugin, tmp_path):
    netcdf4 = pytest.importorskip("netCDF4")

    src_path = tmp_path / "referenced_topology.nc"
    with netcdf4.Dataset(str(src_path), "w") as ds:
        ds.createDimension("my_nodes", 3)
        ds.createDimension("my_faces", 1)
        ds.createDimension("nNodesPerFace", 3)
        ds.createDimension("time", 1)
        ds.createDimension("nSedTot", 2)

        mesh2d = ds.createVariable("mesh2d", "i4")
        mesh2d.cf_role = "mesh_topology"
        mesh2d.topology_dimension = 2
        mesh2d.node_coordinates = "my_node_x my_node_y"
        mesh2d.face_coordinates = "my_face_x my_face_y"
        mesh2d.face_node_connectivity = "my_face_nodes"

        node_x = ds.createVariable("my_node_x", "f8", ("my_nodes",))
        node_y = ds.createVariable("my_node_y", "f8", ("my_nodes",))
        face_x = ds.createVariable("my_face_x", "f8", ("my_faces",))
        face_y = ds.createVariable("my_face_y", "f8", ("my_faces",))
        face_nodes = ds.createVariable("my_face_nodes", "i4", ("my_faces", "nNodesPerFace"))
        sedfrac = ds.createVariable("my_sedfrac", "f4", ("time", "my_faces", "nSedTot"))

        sedfrac.mesh = "mesh2d"
        sedfrac.location = "face"
        sedfrac.coordinates = "my_face_x my_face_y"

        node_x[:] = [120000.0, 121000.0, 120500.0]
        node_y[:] = [425000.0, 425000.0, 426000.0]
        face_x[:] = [120500.0]
        face_y[:] = [425333.0]
        face_nodes[:] = [[1, 2, 3]]
        sedfrac[:] = [[[0.7, 0.3]]]

    with patch.object(plugin, "_prompt_for_morphodynamic_variables", return_value=["my_sedfrac"]), \
         patch.object(plugin, "_load_mesh2d_layer") as load_mesh2d_mock:
        plugin.load_ugrid_mesh_file(str(src_path))

    loaded_path = pathlib.Path(load_mesh2d_mock.call_args[0][0])
    with netcdf4.Dataset(str(loaded_path), "r") as ds:
        assert "mesh2d" in ds.variables
        assert "my_node_x" in ds.variables
        assert "my_node_y" in ds.variables
        assert "my_face_nodes" in ds.variables
        flattened = [name for name in ds.variables if name.startswith("my_sedfrac_")]
        assert len(flattened) == 2
        first_flattened = ds.variables[flattened[0]]
        assert getattr(first_flattened, "mesh", None) == "mesh2d"
        assert getattr(first_flattened, "location", None) == "face"
        assert "my_face_x" in str(getattr(first_flattened, "coordinates", ""))
        assert float(ds.variables["my_node_x"][:].min()) > 100000.0
        assert float(ds.variables["my_node_y"][:].min()) > 400000.0


def test_find_mesh2d_topology_names_prefers_cf_role_mesh_topology(plugin, tmp_path):
    netcdf4 = pytest.importorskip("netCDF4")

    src_path = tmp_path / "topology_names.nc"
    with netcdf4.Dataset(str(src_path), "w") as ds:
        ds.createDimension("mesh2d_nNodes", 3)
        ds.createDimension("mesh2d_nFaces", 1)
        ds.createDimension("nNodesPerFace", 3)

        topo = ds.createVariable("my_mesh", "i4")
        topo.cf_role = "mesh_topology"
        topo.topology_dimension = 2
        topo.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        topo.face_node_connectivity = "mesh2d_face_nodes"

        node_x = ds.createVariable("mesh2d_node_x", "f8", ("mesh2d_nNodes",))
        node_y = ds.createVariable("mesh2d_node_y", "f8", ("mesh2d_nNodes",))
        face_nodes = ds.createVariable("mesh2d_face_nodes", "i4", ("mesh2d_nFaces", "nNodesPerFace"))

        node_x[:] = [0.0, 1.0, 0.0]
        node_y[:] = [0.0, 0.0, 1.0]
        face_nodes[:] = [[1, 2, 3]]

    with netcdf4.Dataset(str(src_path), "r") as ds:
        topology_names = plugin._find_mesh2d_topology_names(ds)

    assert topology_names[0] == "my_mesh"
    assert topology_names == ["my_mesh"]


def test_load_ugrid_mesh_file_passes_topology_names_to_loader(plugin, tmp_path):
    netcdf4 = pytest.importorskip("netCDF4")

    src_path = tmp_path / "topology_passthrough.nc"
    with netcdf4.Dataset(str(src_path), "w") as ds:
        ds.createDimension("my_nodes", 3)
        ds.createDimension("my_faces", 1)
        ds.createDimension("nNodesPerFace", 3)
        ds.createDimension("time", 1)

        topo = ds.createVariable("topo2d", "i4")
        topo.cf_role = "mesh_topology"
        topo.topology_dimension = 2
        topo.node_coordinates = "my_node_x my_node_y"
        topo.face_node_connectivity = "my_face_nodes"

        node_x = ds.createVariable("my_node_x", "f8", ("my_nodes",))
        node_y = ds.createVariable("my_node_y", "f8", ("my_nodes",))
        face_nodes = ds.createVariable("my_face_nodes", "i4", ("my_faces", "nNodesPerFace"))
        depth = ds.createVariable("waterdepth", "f4", ("time", "my_faces"))

        depth.mesh = "topo2d"
        depth.location = "face"

        node_x[:] = [120000.0, 121000.0, 120500.0]
        node_y[:] = [425000.0, 425000.0, 426000.0]
        face_nodes[:] = [[1, 2, 3]]
        depth[:] = [[1.0]]

    with patch.object(plugin, "_find_mesh2d_topology_names", return_value=["topo2d"]), \
         patch.object(plugin, "_prompt_for_morphodynamic_variables", return_value=[]), \
         patch.object(plugin, "_load_mesh2d_layer") as load_mesh2d_mock:
        plugin.load_ugrid_mesh_file(str(src_path))

    kwargs = load_mesh2d_mock.call_args.kwargs
    assert "topology_names" in kwargs
    assert kwargs["topology_names"][0] == "topo2d"
    assert kwargs["expect_data_variables"] is True


# ---------------------------------------------------------------------------
# File-parsing tests using real fixture files
# ---------------------------------------------------------------------------

def test_load_polyline_file_adds_layer(plugin):
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    plugin.load_polyline_file(str(PLI_01))

    assert add_map_layer.call_count == 1


def test_load_fixed_weir_file_adds_two_layers(plugin):
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    plugin.load_file_by_extension(str(FXW_01))

    assert add_map_layer.call_count == 2


def test_load_xyn_file_adds_layer(plugin, tmp_path):
    xyn_file = tmp_path / "points.xyn"
    xyn_file.write_text("1.0 2.0 point_a\n3.0 4.0 point_b\n")

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    plugin.load_xyn_file(str(xyn_file))

    assert add_map_layer.call_count == 1


def test_load_xyn_file_auto_names(plugin, tmp_path):
    """Lines with only x y (no name) should generate obs_N names without error."""
    xyn_file = tmp_path / "nonames.xyn"
    xyn_file.write_text("1.0 2.0\n3.0 4.0\n")

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    plugin.load_xyn_file(str(xyn_file))

    assert add_map_layer.call_count == 1


def test_load_xyn_file_empty_warns(plugin, tmp_path):
    empty_file = tmp_path / "empty.xyn"
    empty_file.write_text("")

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_xyn_file(str(empty_file))

    mock_mb.warning.assert_called_once()


def test_load_xyz_file_adds_layer(plugin):
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    plugin.load_xyz_file(str(XYZ_01))

    assert add_map_layer.call_count == 1


def test_load_xyz_file_malformed_warns(plugin, tmp_path):
    xyz_file = tmp_path / "bad.xyz"
    xyz_file.write_text("1.0 2.0\n")

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_xyz_file(str(xyz_file))

    mock_mb.warning.assert_called_once()


def test_load_cross_sections_from_selection_csl(plugin):
    plugin.load_cross_sections_files = MagicMock()

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg:
        mock_dlg.getOpenFileName.side_effect = [
            (str(CSD_01), ""),
            (str(GRID_01), ""),
        ]
        plugin.load_cross_sections_from_selection(str(CSL_01))

    plugin.load_cross_sections_files.assert_called_once_with(
        str(CSL_01), str(CSD_01), str(GRID_01)
    )


def test_load_cross_sections_from_selection_csd(plugin):
    plugin.load_cross_sections_files = MagicMock()

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg:
        mock_dlg.getOpenFileName.side_effect = [
            (str(CSL_01), ""),
            (str(GRID_01), ""),
        ]
        plugin.load_cross_sections_from_selection(str(CSD_01))

    plugin.load_cross_sections_files.assert_called_once_with(
        str(CSL_01), str(CSD_01), str(GRID_01)
    )


def test_load_cross_sections_files_adds_layer(plugin):
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    profile = {
        "name": "A12Ma_Kj.1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }

    with patch.object(
        plugin,
        "_read_mesh_branch_profiles_from_grid",
        return_value=({"a12ma_kj.1": profile}, 28992),
    ):
        plugin.load_cross_sections_files(str(CSL_01), str(CSD_01), str(GRID_01))

    assert add_map_layer.call_count == 1


def test_load_cross_sections_files_missing_definition_still_loads(plugin):
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    profile = {
        "name": "A12Ma_Kj.1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }

    with patch.object(
        plugin,
        "_read_mesh_branch_profiles_from_grid",
        return_value=({"a12ma_kj.1": profile}, 28992),
    ), patch.object(plugin, "_read_crossdef_records", return_value={}):
        plugin.load_cross_sections_files(str(CSL_01), str(CSD_01), str(GRID_01))

    assert add_map_layer.call_count == 1


def test_read_crossdef_records_includes_circular_fields(plugin, tmp_path):
    csd_file = tmp_path / "circle.csd"
    csd_file.write_text(
        "[General]\n"
        "fileType = crossDef\n\n"
        "[Definition]\n"
        "id = CIRC001\n"
        "type = circle\n"
        "diameter = 1.5\n"
        "frictionType = Manning\n"
        "frictionValue = 0.030\n"
    )

    definitions = plugin._read_crossdef_records(str(csd_file))
    assert "circ001" in definitions
    assert definitions["circ001"]["type"] == "circle"
    assert definitions["circ001"]["diameter"] == "1.5"
    assert definitions["circ001"]["frictiontype"] == "Manning"
    assert definitions["circ001"]["frictionvalue"] == "0.030"


def test_read_dimr_component_input_files(plugin, tmp_path):
    dimr = tmp_path / "dimr_config.xml"
    dimr.write_text(
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<dimrConfig xmlns='http://schemas.deltares.nl/dimrConfig'>\n"
        "  <component name='fm'>\n"
        "    <inputFile>FlowFM.mdu</inputFile>\n"
        "  </component>\n"
        "  <component name='rr'>\n"
        "    <inputFile>rr_config.xml</inputFile>\n"
        "  </component>\n"
        "</dimrConfig>\n",
        encoding="utf-8",
    )

    files = plugin._read_dimr_component_input_files(str(dimr))

    assert files == ["FlowFM.mdu", "rr_config.xml"]


def test_load_dimr_config_requires_defusedxml(plugin, monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    monkeypatch.setattr(plugin_module, "_HAS_DEFUSEDXML", False)
    monkeypatch.setattr(plugin_module, "ET", None)

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_dimr_config_file(str(MODEL_01_DIMR))

    plugin.iface.messageBar.return_value.pushSuccess.assert_not_called()
    mock_mb.critical.assert_called_once()
    message = mock_mb.critical.call_args[0][2]
    assert "required package 'defusedxml' is not available" in message
    assert "Install Python Dependencies" in message
    assert "restart QGIS" in message


def test_load_dimr_model_01_imports_without_problem(plugin):
    plugin.load_file_by_extension = MagicMock()

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_dimr_config_file(str(MODEL_01_DIMR))

    expected_mdu = str((MODEL_01_DIMR.parent / "FlowFM.mdu").resolve())
    plugin.load_file_by_extension.assert_called_once_with(expected_mdu, spatial_grid_path=None)
    mock_mb.warning.assert_not_called()
    mock_mb.critical.assert_not_called()
    plugin.iface.messageBar.return_value.pushSuccess.assert_called_once_with(
        "Delft3D File Manager",
        "DIMR import completed: imported 1 input file(s), missing 0.",
    )


def test_read_mdu_primary_files(plugin, tmp_path):
    mdu = tmp_path / "FlowFM.mdu"
    mdu.write_text(
        "[geometry]\n"
        "NetFile = net.nc\n"
        "CrossLocFile = csl.ini\n"
        "CrossDefFile = csd.ini\n"
        "StructureFile = structures.ini\n"
        "IniFieldFile = initialFields.ini\n"
        "FrictFile = roughness-main.ini;roughness-floodplain.ini\n"
        "[external forcing]\n"
        "ExtForceFileNew = extn.ext\n",
        encoding="utf-8",
    )

    primary = plugin._read_mdu_primary_files(str(mdu))

    assert primary["net_file"] == "net.nc"
    assert primary["crossloc_file"] == "csl.ini"
    assert primary["crossdef_file"] == "csd.ini"
    assert primary["structure_file"] == "structures.ini"
    assert primary["ext_force_file"] == "extn.ext"
    assert primary["frict_files"] == ["roughness-main.ini", "roughness-floodplain.ini"]


def test_load_fm_mdu_file_passes_netfile_to_spatial_imports(plugin, tmp_path):
    mdu = tmp_path / "FlowFM.mdu"
    mdu.write_text("[model]\nname = test\n", encoding="utf-8")

    net = tmp_path / "net.nc"
    ext = tmp_path / "extn.ext"
    structures = tmp_path / "structures.ini"
    inifield = tmp_path / "initialFields.ini"
    roughness = tmp_path / "roughness-main.ini"

    for path in (net, ext, structures, inifield, roughness):
        path.write_text("", encoding="utf-8")

    primary = {
        "net_file": "net.nc",
        "crossloc_file": "",
        "crossdef_file": "",
        "structure_file": "structures.ini",
        "ext_force_file": "extn.ext",
        "ini_field_file": "initialFields.ini",
        "frict_files": ["roughness-main.ini"],
        "thin_dam_file": "",
        "fixed_weir_file": "",
        "pillar_file": "",
    }

    plugin.load_ugrid_mesh_file = MagicMock()
    plugin.load_cross_sections_files = MagicMock()
    plugin.load_ext_file = MagicMock()
    plugin.load_file_by_extension = MagicMock()
    plugin.load_polyline_file = MagicMock()
    plugin.load_fixed_weir_file = MagicMock()

    with patch.object(plugin, "_read_mdu_primary_files", return_value=primary):
        plugin.load_fm_mdu_file(str(mdu), import_referenced=True)

    expected_grid = str(net)
    plugin.load_ext_file.assert_called_once_with(str(ext), grid_path=expected_grid)
    plugin.load_file_by_extension.assert_any_call(str(structures), spatial_grid_path=expected_grid)
    plugin.load_file_by_extension.assert_any_call(str(inifield), spatial_grid_path=expected_grid)
    plugin.load_file_by_extension.assert_any_call(str(roughness), spatial_grid_path=expected_grid)


def test_load_fm_mdu_model_01_attempts_all_primary_imports(plugin):
    mdu_path = MODEL_01_DIMR.parent / "FlowFM.mdu"
    base = MODEL_01_DIMR.parent.resolve()
    expected_grid = str((base / "grd_net.nc").resolve())
    expected_csl = str((base / "csl.ini").resolve())
    expected_csd = str((base / "csd.ini").resolve())
    expected_ext = str((base / "extn.ext").resolve())
    expected_spatial_imports = {
        str((base / "structures.ini").resolve()),
        str((base / "initialFields.ini").resolve()),
        str((base / "roughness-Main.ini").resolve()),
        str((base / "roughness-Floodplain.ini").resolve()),
    }

    plugin.load_ugrid_mesh_file = MagicMock()
    plugin.load_cross_sections_files = MagicMock()
    plugin.load_ext_file = MagicMock()
    plugin.load_file_by_extension = MagicMock()
    plugin.load_polyline_file = MagicMock()
    plugin.load_fixed_weir_file = MagicMock()
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_fm_mdu_file(str(mdu_path), import_referenced=True)

    plugin.load_ugrid_mesh_file.assert_called_once_with(expected_grid)
    plugin.load_cross_sections_files.assert_called_once_with(expected_csl, expected_csd, expected_grid)
    plugin.load_ext_file.assert_called_once_with(expected_ext, grid_path=expected_grid)

    add_map_layer.assert_called_once()
    summary_layer = add_map_layer.call_args[0][0]
    summary_rows = summary_layer.dataProvider.return_value.addFeatures.call_args[0][0]
    assert len(summary_rows) == 11

    imported_paths = {
        args[0]
        for args, kwargs in plugin.load_file_by_extension.call_args_list
        if kwargs.get("spatial_grid_path") == expected_grid
    }
    assert expected_spatial_imports.issubset(imported_paths)

    mock_mb.warning.assert_not_called()
    mock_mb.critical.assert_not_called()


def test_parse_bc_forcing_file(plugin, tmp_path):
    bc = tmp_path / "bc.bc"
    bc.write_text(
        "[General]\n"
        "fileType = boundConds\n"
        "[forcing]\n"
        "Name = UpstreamQ\n"
        "Function = timeseries\n"
        "Quantity = time\n"
        "Unit = hours since 2000-01-01 00:00:00\n"
        "Quantity = dischargebnd\n"
        "Unit = m3/s\n"
        "0 12\n"
        "24 15\n",
        encoding="utf-8",
    )

    rows = plugin._parse_bc_forcing_file(str(bc))

    assert len(rows) == 1
    assert rows[0]["bc_name"] == "UpstreamQ"
    assert rows[0]["bc_function"] == "timeseries"
    assert rows[0]["quantity_1"].lower() == "time"
    assert rows[0]["quantity_2"].lower() == "dischargebnd"
    assert rows[0]["series"] == [(0.0, 12.0), (24.0, 15.0)]


def test_timeseries_from_feature_uses_quantity_unit_axis_labels(plugin):
    feature = {
        "bc_name": "UpstreamQ",
        "bc_function": "timeseries",
        "quantity_1": "time",
        "unit_1": "hours since 2000-01-01 00:00:00",
        "quantity_2": "dischargebnd",
        "unit_2": "m3/s",
        "series_xy": "0 12;24 15",
    }

    points, metadata, message = plugin._timeseries_from_feature(feature)

    assert points == [(0.0, 12.0), (24.0, 15.0)]
    assert metadata["x_axis_label"] == "time [hours since 2000-01-01 00:00:00]"
    assert metadata["y_axis_label"] == "dischargebnd [m3/s]"
    assert message == ""


def test_timeseries_from_feature_axis_label_fallbacks(plugin):
    feature = {
        "bc_name": "UpstreamQ",
        "bc_function": "timeseries",
        "quantity_1": "",
        "unit_1": "",
        "quantity_2": "waterlevelbnd",
        "unit_2": "",
        "series_xy": "0 0.2;1 0.3",
    }

    _, metadata, _ = plugin._timeseries_from_feature(feature)

    assert metadata["x_axis_label"] == "x"
    assert metadata["y_axis_label"] == "waterlevelbnd"


def test_load_ext_file_imports_linked_bc(plugin, tmp_path):
    ext = tmp_path / "extn.ext"
    bc = tmp_path / "bc.bc"
    ext.write_text(
        "[General]\n"
        "fileType = extForce\n"
        "[Boundary]\n"
        "quantity = dischargebnd\n"
        "nodeId = bnd_01\n"
        "forcingfile = bc.bc\n",
        encoding="utf-8",
    )
    bc.write_text(
        "[General]\n"
        "fileType = boundConds\n"
        "[forcing]\n"
        "Name = bnd_01\n"
        "Function = timeseries\n"
        "Quantity = time\n"
        "Unit = h\n"
        "Quantity = dischargebnd\n"
        "Unit = m3/s\n"
        "0 1\n"
        "1 2\n",
        encoding="utf-8",
    )

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    context = {
        "branch_lookup": {},
        "node_lookup": {"bnd_01": (120000.0, 450000.0)},
        "epsg": 28992,
    }

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))), \
         patch.object(plugin, "_apply_boundary_type_categorized_style") as style_mock:
        plugin.load_ext_file(str(ext))

    assert add_map_layer.call_count == 1
    style_mock.assert_called_once()


def test_load_structures_spatial_file_creates_points(plugin, tmp_path):
    structures = tmp_path / "structures.ini"
    structures.write_text(
        "[General]\n"
        "fileType = structure\n"
        "[Structure]\n"
        "id = S1\n"
        "name = S1\n"
        "type = weir\n"
        "branchId = B1\n"
        "chainage = 500\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))), \
         patch.object(plugin, "_apply_structure_type_categorized_style") as style_mock:
        plugin.load_structures_spatial_file(str(structures))

    assert add_map_layer.call_count == 1
    style_mock.assert_called_once()


def test_parse_structures_file_keeps_type_specific_fields(plugin, tmp_path):
    structures = tmp_path / "structures.ini"
    structures.write_text(
        "[General]\n"
        "fileType = structure\n"
        "[Structure]\n"
        "id = W1\n"
        "type = weir\n"
        "branchId = B1\n"
        "chainage = 500\n"
        "crestWidth = 12.5\n"
        "allowedFlowDir = both\n"
        "[Structure]\n"
        "id = C1\n"
        "type = compound\n"
        "structureIds = W1;G1;P1\n",
        encoding="utf-8",
    )

    records = plugin._parse_structures_file(str(structures))

    assert len(records) == 2
    assert records[0]["normalized"]["crestwidth"] == "12.5"
    assert records[0]["normalized"]["allowedflowdir"] == "both"
    assert records[1]["structureIds"] == ["W1", "G1", "P1"]


def test_load_structures_spatial_file_adds_compound_table(plugin, tmp_path):
    structures = tmp_path / "structures.ini"
    structures.write_text(
        "[General]\n"
        "fileType = structure\n"
        "[Structure]\n"
        "id = S1\n"
        "type = weir\n"
        "branchId = B1\n"
        "chainage = 500\n"
        "[Structure]\n"
        "id = C1\n"
        "type = compound\n"
        "structureIds = S1\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_structures_spatial_file(str(structures))

    assert add_map_layer.call_count == 2


def test_load_structures_spatial_file_accepts_quoted_branch_and_comma_chainage(plugin, tmp_path):
    structures = tmp_path / "structures_quotes.ini"
    structures.write_text(
        "[General]\n"
        "fileType = structure\n"
        "[Structure]\n"
        "id = S1\n"
        "type = weir\n"
        "branchId = \"B1\"\n"
        "chainage = 500,0\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_structures_spatial_file(str(structures))

    assert add_map_layer.call_count == 1


def test_interpolate_point_on_branch_clamps_small_end_overshoot(plugin):
    profile = {
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }

    result = plugin._interpolate_point_on_branch(profile, 1000.0 + 5e-7)

    assert result == (1000.0, 0.0)


def test_load_structures_spatial_file_reports_requested_and_max_chainage(plugin, tmp_path):
    structures = tmp_path / "structures_out_of_range.ini"
    structures.write_text(
        "[General]\n"
        "fileType = structure\n"
        "[Structure]\n"
        "id = S1\n"
        "type = weir\n"
        "branchId = B1\n"
        "chainage = 1200\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_structures_spatial_file(str(structures))

    assert add_map_layer.call_count == 1
    layer = add_map_layer.call_args[0][0]
    feature = layer.dataProvider.return_value.addFeatures.call_args[0][0][0]

    resolve_note_values = [
        call.args[1]
        for call in feature.__setitem__.call_args_list
        if len(call.args) == 2 and call.args[0] == "resolve_note"
    ]
    assert resolve_note_values
    assert "requested 1200" in resolve_note_values[-1]
    assert "max 1000" in resolve_note_values[-1]


def test_load_structures_spatial_file_compound_only_skips_grid_prompt(plugin, tmp_path):
    structures = tmp_path / "structures.ini"
    structures.write_text(
        "[General]\n"
        "fileType = structure\n"
        "[Structure]\n"
        "id = C1\n"
        "type = compound\n"
        "structureIds = A;B\n",
        encoding="utf-8",
    )

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context") as resolve_mock:
        plugin.load_structures_spatial_file(str(structures))

    resolve_mock.assert_not_called()
    assert add_map_layer.call_count == 1


def test_load_1d_field_spatial_file_creates_points(plugin, tmp_path):
    field = tmp_path / "InitialWaterLevel.ini"
    field.write_text(
        "[General]\n"
        "fileType = 1dField\n"
        "[Global]\n"
        "quantity = waterlevel\n"
        "unit = m\n"
        "[Branch]\n"
        "branchId = B1\n"
        "chainage = 100 200\n"
        "values = 1.0 2.0\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_1d_field_spatial_file(str(field))

    assert add_map_layer.call_count == 1


def test_load_roughness_spatial_file_creates_points(plugin, tmp_path):
    roughness = tmp_path / "roughness.ini"
    roughness.write_text(
        "[General]\n"
        "fileType = roughness\n"
        "[Branch]\n"
        "branchId = B1\n"
        "frictionType = Strickler\n"
        "functionType = absDischarge\n"
        "chainage = 100 300\n"
        "frictionValues = 20 30\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_roughness_spatial_file(str(roughness))

    assert add_map_layer.call_count == 1


def test_load_roughness_spatial_file_accepts_case_and_alias_keys(plugin, tmp_path):
    roughness = tmp_path / "roughness_alias.ini"
    roughness.write_text(
        "[General]\n"
        "fileType = roughness\n"
        "[Branch]\n"
        "branchid = B1\n"
        "frictiontype = Manning\n"
        "function = absDischarge\n"
        "chainages = 100 300\n"
        "frictionValue = 20 30\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_roughness_spatial_file(str(roughness))

    assert add_map_layer.call_count == 1


def test_load_roughness_spatial_file_accepts_branch_like_section_name(plugin, tmp_path):
    roughness = tmp_path / "roughness_branch_like.ini"
    roughness.write_text(
        "[General]\n"
        "fileType = roughness\n"
        "[Branch 1]\n"
        "branchId = B1\n"
        "frictionType = Manning\n"
        "functionType = absDischarge\n"
        "chainage = 100 300\n"
        "frictionValues = 20 30\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_roughness_spatial_file(str(roughness))

    assert add_map_layer.call_count == 1


def test_load_roughness_spatial_file_reports_no_candidate_blocks(plugin, tmp_path):
    roughness = tmp_path / "roughness_no_candidate.ini"
    roughness.write_text(
        "[General]\n"
        "fileType = roughness\n"
        "[Global]\n"
        "frictionType = Manning\n"
        "frictionValue = 25\n",
        encoding="utf-8",
    )

    context = {"branch_lookup": {}, "node_lookup": {}, "epsg": 28992}

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))), \
         patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_roughness_spatial_file(str(roughness))

    mock_mb.warning.assert_called_once()
    call_args = mock_mb.warning.call_args[0]
    assert "Candidate roughness blocks processed=0" in call_args[2]


def test_load_roughness_spatial_file_global_defaults_create_midpoint_features(plugin, tmp_path):
    roughness = tmp_path / "roughness_global.ini"
    roughness.write_text(
        "[General]\n"
        "fileType = roughness\n"
        "[Global]\n"
        "frictionType = Manning\n"
        "frictionValue = 25\n",
        encoding="utf-8",
    )

    profile = {
        "name": "B1",
        "points": [(0.0, 0.0), (1000.0, 0.0)],
        "cumlen": [0.0, 1000.0],
        "length": 1000.0,
    }
    context = {"branch_lookup": {"b1": profile}, "node_lookup": {}, "epsg": 28992}

    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    with patch.object(plugin, "_resolve_spatial_context", return_value=(context, str(tmp_path / "grid.nc"))):
        plugin.load_roughness_spatial_file(str(roughness))

    assert add_map_layer.call_count == 1


# ---------------------------------------------------------------------------
# ShorelineS .mat file import tests
# ---------------------------------------------------------------------------

def test_route_mat(plugin):
    plugin.load_shorelines_mat_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.mat")
    plugin.load_shorelines_mat_file.assert_called_once_with("/fake/file.mat")


def test_load_shorelines_mat_valid_all_datasets(plugin):
    """Test successful import with coastline, hard structures, and groynes."""
    import numpy as np
    
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    # Create mock structure as a dict (simulates numpy.void indexed access)
    O_data = {
        'x': np.array([[1.0, 2.0], [3.0, 4.0]]),
        'y': np.array([[5.0, 6.0], [7.0, 8.0]]),
        'timenum': np.array([719529.0, 719530.0]),  # 1D after squeeze_me=True
        'xhard': np.array([10.0, 11.0, np.nan, 12.0]),
        'yhard': np.array([20.0, 21.0, np.nan, 22.0]),
        'x_groyne': np.array([30.0, 31.0, 32.0]),
        'y_groyne': np.array([40.0, 41.0, 42.0])
    }

    # With squeeze_me=True, the (1,1) array becomes a scalar (the dict directly)
    mock_mat = {
        "O": O_data
    }

    with patch("scipy.io.loadmat", return_value=mock_mat):
        plugin.load_shorelines_mat_file("/fake/output.mat")

    # Should add 3 layers: coastline (2 features) + hard_structures (1) + groynes (1)
    assert add_map_layer.call_count == 3


def test_load_shorelines_mat_coastline_only(plugin):
    """Test import with only coastline (required fields)."""
    import numpy as np
    
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    O_data = {
        'x': np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        'y': np.array([[5.0, 6.0, 7.0], [8.0, 9.0, 10.0]]),
        'timenum': np.array([719529.0, 719530.0, 719531.0])  # 1D after squeeze_me=True
    }

    mock_mat = {"O": O_data}

    with patch("scipy.io.loadmat", return_value=mock_mat):
        plugin.load_shorelines_mat_file("/fake/coastline_only.mat")

    # Should add 1 layer (coastline) with 3 features (one per timestep)
    assert add_map_layer.call_count == 1


def test_load_shorelines_mat_empty_hard_features(plugin):
    """Test that empty hard structures/groynes arrays don't create layers."""
    import numpy as np
    
    add_map_layer = _add_map_layer_mock()
    add_map_layer.reset_mock()

    # All-NaN hard features should not create a layer
    O_data = {
        'x': np.array([[1.0, 2.0], [3.0, 4.0]]),
        'y': np.array([[5.0, 6.0], [7.0, 8.0]]),
        'timenum': np.array([719529.0, 719530.0]),  # 1D after squeeze_me=True
        'xhard': np.array([np.nan, np.nan]),
        'yhard': np.array([np.nan, np.nan]),
        'x_groyne': np.array([]),
        'y_groyne': np.array([])
    }

    mock_mat = {"O": O_data}

    with patch("scipy.io.loadmat", return_value=mock_mat):
        plugin.load_shorelines_mat_file("/fake/coastline_with_empty_hard.mat")

    # Should add only coastline layer (no hard structures, no groynes)
    assert add_map_layer.call_count == 1


def test_load_shorelines_mat_non_shorelines_structure(plugin):
    """Test that non-ShorelineS files are rejected with clear warning."""
    mock_mat = {
        "some_data": [1, 2, 3],
        "other_field": [4, 5, 6],
    }

    with patch("scipy.io.loadmat", return_value=mock_mat), \
         patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_shorelines_mat_file("/fake/not_shorelines.mat")

    mock_mb.warning.assert_called_once()
    call_args = mock_mb.warning.call_args[0]
    assert "ShorelineS" in call_args[2]


def test_load_shorelines_mat_malformed_shapes(plugin):
    """Test that mismatched array shapes raise critical error."""
    import numpy as np
    
    O_data = {
        'x': np.array([[1.0, 2.0]]),  # 1x2 array, but should be 2D with 2 rows
        'y': np.array([3.0, 4.0]),     # 1D array, should be 2D
        'timenum': np.array([719529.0, 719530.0])  # 1D after squeeze_me=True
    }

    mock_mat = {"O": O_data}

    with patch("scipy.io.loadmat", return_value=mock_mat), \
         patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_shorelines_mat_file("/fake/malformed.mat")

    mock_mb.critical.assert_called_once()
    call_args = mock_mb.critical.call_args[0]
    assert "Invalid" in call_args[2] or "shape" in call_args[2].lower()


def test_load_shorelines_mat_file_read_error(plugin):
    """Test graceful handling of file read errors."""
    with patch("scipy.io.loadmat", 
               side_effect=IOError("Cannot read file")), \
         patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_shorelines_mat_file("/fake/corrupted.mat")

    mock_mb.critical.assert_called_once()
    call_args = mock_mb.critical.call_args[0]
    assert "Error reading" in call_args[2]


def test_matlab_datenum_to_datetime(plugin):
    assert plugin._matlab_datenum_to_datetime(719529.0) == datetime(1970, 1, 1, 0, 0, 0)
    assert plugin._matlab_datenum_to_datetime(719529.5) == datetime(1970, 1, 1, 12, 0, 0)


def test_load_coastline_layer_sets_datetime_field(plugin):
    import numpy as np

    captured = {}

    class FakeQDateTime:
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return isinstance(other, FakeQDateTime) and self.value == other.value

    class FakeField:
        def __init__(self, name, variant_type):
            self.name = name
            self.variant_type = variant_type

    class FakeFeature:
        def __init__(self, fields):
            self.fields = fields
            self.geometry = None
            self.attributes = None

        def setGeometry(self, geometry):
            self.geometry = geometry

        def setAttributes(self, attributes):
            self.attributes = attributes

    class FakeProvider:
        def __init__(self):
            self.attributes = None
            self.features = None

        def addAttributes(self, attributes):
            self.attributes = attributes

        def addFeatures(self, features):
            self.features = features
            captured["features"] = features

    class FakeLayer:
        def __init__(self, *args, **kwargs):
            self.provider = FakeProvider()

        def dataProvider(self):
            return self.provider

        def updateFields(self):
            pass

        def fields(self):
            return []

        def updateExtents(self):
            pass

    fake_project = SimpleNamespace(addMapLayer=lambda layer: captured.setdefault("layer", layer))

    with patch("Delft3DFileManager.Delft3DFileManager.QgsVectorLayer", FakeLayer), \
         patch("Delft3DFileManager.Delft3DFileManager.QgsField", FakeField), \
         patch("Delft3DFileManager.Delft3DFileManager.QgsFeature", FakeFeature), \
            patch("Delft3DFileManager.Delft3DFileManager.QDateTime", FakeQDateTime), \
         patch("Delft3DFileManager.Delft3DFileManager.QgsGeometry.fromPolylineXY", side_effect=lambda polyline: polyline), \
         patch("Delft3DFileManager.Delft3DFileManager.QgsProject.instance", return_value=fake_project):
        feature_count = plugin._load_coastline_layer(
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            np.array([[5.0, 6.0], [7.0, 8.0]]),
            np.array([719529.0, 719529.5]),
            "shorelines",
            28992,
        )

    assert feature_count == 2
    assert [field.name for field in captured["layer"].provider.attributes] == ["t_index", "timenum", "datetime"]
    assert captured["layer"].provider.attributes[2].variant_type != _qgis_core.QVariant.String
    assert captured["features"][0].attributes == [0, 719529.0, FakeQDateTime(datetime(1970, 1, 1, 0, 0, 0))]
    assert captured["features"][1].attributes == [1, 719529.5, FakeQDateTime(datetime(1970, 1, 1, 12, 0, 0))]


# ---------------------------------------------------------------------------
# Cross-section profile chart helper tests
# ---------------------------------------------------------------------------

class _FakeField:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def disconnect(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)


class _FakeFeature:
    def __init__(self, attrs, fid=1):
        self._attrs = attrs
        self._fid = fid

    def __getitem__(self, key):
        return self._attrs.get(key)

    def id(self):
        return self._fid


class _FakeLayer:
    def __init__(self, fields, selected=None):
        self._fields = [_FakeField(name) for name in fields]
        self._selected = selected or []
        self.selectionChanged = _FakeSignal()

    def type(self):
        return _qgis_core.QgsMapLayerType.VectorLayer

    def geometryType(self):
        return _qgis_core.QgsWkbTypes.PointGeometry

    def fields(self):
        return self._fields

    def getSelectedFeatures(self):
        return list(self._selected)


def test_profile_layer_detection(plugin):
    layer = _FakeLayer(
        ["id", "definitionId", "def_type", "def_yCoords", "def_zCoords", "def_diam"]
    )
    assert plugin._is_cross_section_layer(layer)


def test_parse_float_list_valid_and_invalid(plugin):
    assert plugin._parse_float_list("1 2.5 -3") == [1.0, 2.5, -3.0]
    assert plugin._parse_float_list("1 two 3") is None


def test_build_yz_profile_success(plugin):
    feature = _FakeFeature({"def_yCoords": "0 1 2", "def_zCoords": "-1 -2 -3"})
    points = plugin._build_yz_profile(feature)
    assert points == [(0.0, -1.0), (1.0, -2.0), (2.0, -3.0)]


def test_build_yz_profile_mismatch_returns_empty(plugin):
    feature = _FakeFeature({"def_yCoords": "0 1", "def_zCoords": "-1"})
    assert plugin._build_yz_profile(feature) == []


def test_build_circle_profile_success(plugin):
    feature = _FakeFeature({"def_diam": "2.0"})
    points = plugin._build_circle_profile(feature, n=8)
    assert len(points) == 9
    assert points[0][0] == pytest.approx(points[-1][0])
    assert points[0][1] == pytest.approx(points[-1][1])
    assert min(point[1] for point in points) < 0.0
    assert max(point[1] for point in points) > 0.0


def test_open_profile_from_selected_feature(plugin):
    feature = _FakeFeature(
        {
            "id": "cs_1",
            "definitionId": "def_1",
            "def_type": "yz",
            "def_yCoords": "0 1",
            "def_zCoords": "-1 -2",
            "def_diam": "",
        }
    )
    layer = _FakeLayer(
        ["id", "definitionId", "def_type", "def_yCoords", "def_zCoords", "def_diam"],
        selected=[feature],
    )

    plugin.iface.activeLayer.return_value = layer
    plugin._show_profile_in_dialog = MagicMock()

    plugin.open_cross_section_profile_window()

    plugin._show_profile_in_dialog.assert_called_once_with(feature)


def test_selection_changed_updates_profile(plugin):
    feature = _FakeFeature(
        {
            "id": "cs_2",
            "definitionId": "def_2",
            "def_type": "yz",
            "def_yCoords": "0 1",
            "def_zCoords": "-2 -3",
            "def_diam": "",
        }
    )
    layer = _FakeLayer(
        ["id", "definitionId", "def_type", "def_yCoords", "def_zCoords", "def_diam"],
        selected=[feature],
    )

    plugin._show_profile_in_dialog = MagicMock()
    plugin._set_profile_layer(layer)
    plugin._on_profile_layer_selection_changed()

    plugin._show_profile_in_dialog.assert_called_once_with(feature)


def test_double_click_with_no_cross_section_layer_no_crash(plugin):
    plugin.iface.activeLayer.return_value = None
    plugin._handle_canvas_double_click(SimpleNamespace(x=lambda: 0.0, y=lambda: 0.0))
