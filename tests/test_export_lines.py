import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# Access QGIS symbols through sys.modules (the explicitly registered stubs),
# not via `import qgis.core` which resolves to the auto-attribute chain.
_qgis_core = sys.modules["qgis.core"]


def _make_point(x, y):
    pt = MagicMock()
    pt.x.return_value = x
    pt.y.return_value = y
    return pt


def _make_layer():
    """Return a mock layer that passes the export_lines() type/geometry checks."""
    layer = MagicMock()
    layer.type.return_value = _qgis_core.QgsMapLayerType.VectorLayer
    layer.geometryType.return_value = _qgis_core.QgsWkbTypes.LineGeometry
    field = MagicMock()
    field.name.return_value = "weir_name"
    layer.fields.return_value = [field]
    return layer


def _make_feature(name, feature_id=1):
    feat = MagicMock()
    feat.id.return_value = feature_id
    feat.__getitem__.return_value = name
    feat.geometry.return_value.isEmpty.return_value = False
    return feat


# ---------------------------------------------------------------------------
# .pli format tests
# ---------------------------------------------------------------------------

def test_export_lines_pli_single(plugin, tmp_path):
    out = str(tmp_path / "result.pli")
    layer = _make_layer()
    feat = _make_feature("WeirA")
    pts = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    layer.getFeatures.return_value = [feat]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", return_value=[pts]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    lines = open(out).read().splitlines()
    assert lines[0] == "WeirA"
    assert lines[1] == "2 2"
    assert lines[2] == "1.000000 2.000000"
    assert lines[3] == "3.000000 4.000000"


def test_export_lines_pli_multipart(plugin, tmp_path):
    out = str(tmp_path / "result.pli")
    layer = _make_layer()
    feat = _make_feature("WeirA")
    pts1 = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    pts2 = [_make_point(5.0, 6.0), _make_point(7.0, 8.0)]
    layer.getFeatures.return_value = [feat]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", return_value=[pts1, pts2]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    lines = open(out).read().splitlines()
    assert lines[0] == "WeirA_1"
    assert lines[1] == "2 2"
    assert lines[4] == "WeirA_2"
    assert lines[5] == "2 2"


def test_export_lines_pli_auto_append(plugin, tmp_path):
    bare_path = str(tmp_path / "myfile")
    expected_path = str(tmp_path / "myfile.pli")
    layer = _make_layer()
    feat = _make_feature("WeirA")
    pts = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    layer.getFeatures.return_value = [feat]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", return_value=[pts]):
        mock_dlg.getSaveFileName.return_value = (bare_path, "")
        plugin.export_lines()

    assert os.path.exists(expected_path)
    assert not os.path.exists(bare_path)


# ---------------------------------------------------------------------------
# .xy format tests
# ---------------------------------------------------------------------------

def test_export_lines_xy_single(plugin, tmp_path):
    out = str(tmp_path / "result.xy")
    layer = _make_layer()
    feat = _make_feature("WeirA")
    pts = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    layer.getFeatures.return_value = [feat]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", return_value=[pts]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    lines = open(out).read().splitlines()
    assert lines == ["1.000000 2.000000", "3.000000 4.000000"]


def test_export_lines_xy_multiple_features_separator(plugin, tmp_path):
    out = str(tmp_path / "result.xy")
    layer = _make_layer()
    feat1 = _make_feature("WeirA", feature_id=1)
    feat2 = _make_feature("WeirB", feature_id=2)
    pts1 = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    pts2 = [_make_point(5.0, 6.0), _make_point(7.0, 8.0)]
    layer.getFeatures.return_value = [feat1, feat2]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", side_effect=[[pts1], [pts2]]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    lines = open(out).read().splitlines()
    assert lines[0] == "1.000000 2.000000"
    assert lines[1] == "3.000000 4.000000"
    assert lines[2] == "NaN NaN"
    assert lines[3] == "5.000000 6.000000"
    assert lines[4] == "7.000000 8.000000"


def test_export_lines_xy_multipart_separator(plugin, tmp_path):
    out = str(tmp_path / "result.xy")
    layer = _make_layer()
    feat = _make_feature("WeirA")
    pts1 = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    pts2 = [_make_point(5.0, 6.0), _make_point(7.0, 8.0)]
    layer.getFeatures.return_value = [feat]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", return_value=[pts1, pts2]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    lines = open(out).read().splitlines()
    assert lines[2] == "NaN NaN"


def test_export_lines_xy_no_trailing_nan(plugin, tmp_path):
    out = str(tmp_path / "result.xy")
    layer = _make_layer()
    feat1 = _make_feature("WeirA", feature_id=1)
    feat2 = _make_feature("WeirB", feature_id=2)
    pts1 = [_make_point(1.0, 2.0), _make_point(3.0, 4.0)]
    pts2 = [_make_point(5.0, 6.0), _make_point(7.0, 8.0)]
    layer.getFeatures.return_value = [feat1, feat2]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_polylines", side_effect=[[pts1], [pts2]]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    content = open(out).read()
    non_empty_lines = [l for l in content.splitlines() if l.strip()]
    assert non_empty_lines[-1] != "NaN NaN"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_export_lines_cancelled(plugin, tmp_path):
    layer = _make_layer()
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg:
        mock_dlg.getSaveFileName.return_value = ("", "")
        plugin.export_lines()

    plugin.iface.messageBar.return_value.pushSuccess.assert_not_called()


def test_export_lines_no_valid_features(plugin, tmp_path):
    out = str(tmp_path / "empty.pli")
    layer = _make_layer()
    feat = _make_feature("WeirA")
    layer.getFeatures.return_value = [feat]
    plugin.iface.activeLayer.return_value = layer

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb, \
         patch.object(plugin, "_extract_polylines", return_value=[]):
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_lines()

    mock_mb.warning.assert_called_once()
