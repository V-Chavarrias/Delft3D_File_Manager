import os
from unittest.mock import MagicMock, patch

import pytest


def _make_weir_fields(plugin):
    """Return mock QgsField list matching the fixed-weir schema."""
    fields = []
    for name in plugin._fixed_weir_field_names():
        f = MagicMock()
        f.name.return_value = name
        fields.append(f)
    return fields


def _make_weir_feature(weir_name, numeric_values, x, y, feature_id=1):
    """
    Return (feature_mock, [point_mock]) for export_fixed_weir_pliz().
    numeric_values: list of 7 floats [crest_lvl, sill_hL, sill_hR, crest_w, slope_L, slope_R, rough_cd]
    """
    field_data = {
        "weir_name": weir_name,
        "crest_lvl": numeric_values[0],
        "sill_hL": numeric_values[1],
        "sill_hR": numeric_values[2],
        "crest_w": numeric_values[3],
        "slope_L": numeric_values[4],
        "slope_R": numeric_values[5],
        "rough_cd": numeric_values[6],
    }
    feat = MagicMock()
    feat.id.return_value = feature_id
    feat.__getitem__.side_effect = lambda k: field_data[k]
    feat.geometry.return_value.isEmpty.return_value = False

    point = MagicMock()
    point.x.return_value = x
    point.y.return_value = y

    return feat, [point]


_NUMERIC = [1.0, 0.0, 5.71, 10.0, 4.0, 4.0, 0.0]


def test_export_fixed_weir_pliz_single_block(plugin, tmp_path):
    layer = MagicMock()
    layer.fields.return_value = _make_weir_fields(plugin)
    feat, points = _make_weir_feature("weir1", _NUMERIC, 100.0, 200.0)
    layer.getFeatures.return_value = [feat]

    out_base = str(tmp_path / "test")

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", return_value=points):
        mock_dlg.getSaveFileName.return_value = (out_base, "")
        plugin.export_fixed_weir_pliz(layer)

    out = str(tmp_path / "test.pliz")
    assert os.path.exists(out)
    lines = open(out).read().splitlines()
    assert len(lines) == 3  # name + header + 1 point row
    assert lines[1] == "1 9"
    assert lines[2].startswith("100.000000 200.000000")


def test_export_fixed_weir_pliz_multiple_blocks(plugin, tmp_path):
    layer = MagicMock()
    layer.fields.return_value = _make_weir_fields(plugin)
    feat1, pts1 = _make_weir_feature("weir1", _NUMERIC, 100.0, 200.0, feature_id=1)
    feat2, pts2 = _make_weir_feature("weir2", _NUMERIC, 300.0, 400.0, feature_id=2)
    layer.getFeatures.return_value = [feat1, feat2]

    out_base = str(tmp_path / "test")

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", side_effect=[pts1, pts2]):
        mock_dlg.getSaveFileName.return_value = (out_base, "")
        plugin.export_fixed_weir_pliz(layer)

    out = str(tmp_path / "test.pliz")
    lines = open(out).read().splitlines()
    block_headers = [l for l in lines if l.endswith(":")]
    assert len(block_headers) == 2


def test_export_fixed_weir_pliz_name_normalized(plugin, tmp_path):
    layer = MagicMock()
    layer.fields.return_value = _make_weir_fields(plugin)
    feat, points = _make_weir_feature("myweir", _NUMERIC, 1.0, 2.0)
    layer.getFeatures.return_value = [feat]

    out_base = str(tmp_path / "test")

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", return_value=points):
        mock_dlg.getSaveFileName.return_value = (out_base, "")
        plugin.export_fixed_weir_pliz(layer)

    out = str(tmp_path / "test.pliz")
    first_line = open(out).readline().strip()
    assert first_line.endswith(":")


def test_export_fixed_weir_pliz_auto_append(plugin, tmp_path):
    layer = MagicMock()
    layer.fields.return_value = _make_weir_fields(plugin)
    feat, points = _make_weir_feature("weir1", _NUMERIC, 1.0, 2.0)
    layer.getFeatures.return_value = [feat]

    bare_path = str(tmp_path / "output")
    expected = str(tmp_path / "output.pliz")

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", return_value=points):
        mock_dlg.getSaveFileName.return_value = (bare_path, "")
        plugin.export_fixed_weir_pliz(layer)

    assert os.path.exists(expected)
    assert not os.path.exists(bare_path)


def test_export_fixed_weir_pliz_header_columns(plugin, tmp_path):
    layer = MagicMock()
    layer.fields.return_value = _make_weir_fields(plugin)
    feat, points = _make_weir_feature("weir1", _NUMERIC, 1.0, 2.0)
    layer.getFeatures.return_value = [feat]

    out_base = str(tmp_path / "test")

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch.object(plugin, "_extract_points", return_value=points):
        mock_dlg.getSaveFileName.return_value = (out_base, "")
        plugin.export_fixed_weir_pliz(layer)

    out = str(tmp_path / "test.pliz")
    lines = open(out).read().splitlines()
    # lines[0] = block name, lines[1] = header "<n> 9"
    assert lines[1].endswith("9")
    assert lines[1].split()[1] == "9"


def test_export_fixed_weir_pliz_no_valid_features(plugin, tmp_path):
    layer = MagicMock()
    layer.fields.return_value = _make_weir_fields(plugin)
    # Feature with empty geometry — will be skipped
    feat = MagicMock()
    feat.geometry.return_value.isEmpty.return_value = True
    layer.getFeatures.return_value = [feat]

    out = str(tmp_path / "test.pliz")

    with patch("Delft3DFileManager.Delft3DFileManager.QFileDialog") as mock_dlg, \
         patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        mock_dlg.getSaveFileName.return_value = (out, "")
        plugin.export_fixed_weir_pliz(layer)

    mock_mb.warning.assert_called_once()
