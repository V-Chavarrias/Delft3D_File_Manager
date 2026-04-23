import sys
import pathlib
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


def test_route_xyz(plugin):
    plugin.load_xyz_file = MagicMock()
    plugin.load_file_by_extension("/fake/file.xyz")
    plugin.load_xyz_file.assert_called_once_with("/fake/file.xyz")


def test_route_csl(plugin):
    plugin.load_cross_sections_from_selection = MagicMock()
    plugin.load_file_by_extension("/fake/file.csl")
    plugin.load_cross_sections_from_selection.assert_called_once_with("/fake/file.csl")


def test_route_csd(plugin):
    plugin.load_cross_sections_from_selection = MagicMock()
    plugin.load_file_by_extension("/fake/file.csd")
    plugin.load_cross_sections_from_selection.assert_called_once_with("/fake/file.csd")


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
