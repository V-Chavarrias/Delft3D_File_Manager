import sys
import pathlib
from unittest.mock import MagicMock, patch

import pytest

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
FXW_01 = DATA_DIR / "fxw_01.pliz"
PLI_01 = DATA_DIR / "pli_01.pli"

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

    with patch.object(plugin, "_pliz_has_extra_columns", return_value=False):
        plugin.load_file_by_extension("/fake/file.pliz")

    plugin.load_polyline_file.assert_called_once_with("/fake/file.pliz")
    plugin.load_fixed_weir_file.assert_not_called()


def test_route_xyn(plugin):
    plugin.load_xyn_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.xyn")
    plugin.load_xyn_file.assert_called_once_with("/fake/file.xyn")


def test_route_unknown(plugin):
    with patch("Delft3DFileManager.Delft3DFileManager.QMessageBox") as mock_mb:
        plugin.load_file_by_extension("/fake/file.abc")
    mock_mb.warning.assert_called_once()


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
