from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from tests.dialog_test_support import (
    FakeQtThread,
    FakeTextControl,
    FakeToggleButton,
    load_dialog_module,
    new_widget_instance,
)
from tests.fixtures_qgis_fakes import FakeComboBox, FakeSignal


pytestmark = pytest.mark.unit


@pytest.fixture
def dialog_module(monkeypatch):
    return load_dialog_module(
        monkeypatch,
        "bed_level_dialog.py",
        "bed_level_dialog_state",
        package="Delft3DFileManager",
        qt_core_overrides={"QThread": FakeQtThread},
    )


def _dialog(module, mesh_path="", source_path=""):
    dialog = new_widget_instance(module.BedLevelDialog)
    dialog.mesh_path_edit = FakeTextControl(mesh_path)
    dialog.output_mesh_edit = FakeTextControl()
    dialog.mesh_epsg_edit = FakeTextControl()
    dialog.src_path_edit = FakeTextControl(source_path)
    dialog.src_epsg_edit = FakeTextControl()
    dialog.combo_z_var = FakeComboBox()
    dialog.combo_src_var = FakeComboBox()
    dialog.combo_raster_layer = FakeComboBox()
    dialog.combo_raster_band = FakeComboBox()
    dialog.combo_vector_layer = FakeComboBox()
    dialog.combo_vector_attr = FakeComboBox()
    dialog.radio_netcdf = FakeToggleButton(checked=True)
    dialog.radio_raster = FakeToggleButton()
    dialog.radio_vector = FakeToggleButton()
    return dialog


def _message_box(module, monkeypatch):
    message_box = SimpleNamespace(
        warning=MagicMock(),
        critical=MagicMock(),
        information=MagicMock(),
    )
    monkeypatch.setattr(module, "QMessageBox", message_box)
    return message_box


def test_qt_and_qgis_enum_helpers_support_nested_names(dialog_module, monkeypatch):
    monkeypatch.setattr(
        dialog_module,
        "Qt",
        SimpleNamespace(AlignmentFlag=SimpleNamespace(AlignCenter=1)),
    )
    monkeypatch.setattr(
        dialog_module,
        "QDialogButtonBox",
        SimpleNamespace(
            ButtonRole=SimpleNamespace(AcceptRole=2, RejectRole=3),
            StandardButton=SimpleNamespace(Close=4),
        ),
    )
    monkeypatch.setattr(
        dialog_module,
        "QFileDialog",
        SimpleNamespace(
            FileMode=SimpleNamespace(ExistingFile=5),
            Option=SimpleNamespace(DontUseNativeDialog=6),
        ),
    )
    monkeypatch.setattr(
        dialog_module,
        "QgsWkbTypes",
        SimpleNamespace(GeometryType=SimpleNamespace(PointGeometry=7)),
    )

    assert dialog_module._qt_alignment_flag("AlignCenter") == 1
    assert dialog_module._qdialogbuttonbox_role("AcceptRole") == 2
    assert dialog_module._qdialogbuttonbox_standard_button("Close") == 4
    assert dialog_module._qfiledialog_file_mode("ExistingFile") == 5
    assert dialog_module._qfiledialog_option("DontUseNativeDialog") == 6
    assert dialog_module._qgs_geometry_type("PointGeometry") == 7


def test_interpolation_worker_emits_progress_and_result(dialog_module, monkeypatch):
    worker = dialog_module._InterpolationWorker(
        "linear",
        "mesh.nc",
        "bedlevel",
        np.array([1.0]),
        np.array([2.0]),
        np.array([3.0]),
        28992,
        4326,
        "nearest",
    )
    worker.progress = MagicMock()
    worker.finished = MagicMock()
    worker.error = MagicMock()

    def interpolate(**kwargs):
        kwargs["progress_callback"](1, 4)
        return 3

    monkeypatch.setattr(dialog_module, "run_interpolation", interpolate)
    worker.run()

    worker.progress.emit.assert_called_once_with(1, 4)
    worker.finished.emit.assert_called_once_with(3)
    worker.error.emit.assert_not_called()


def test_interpolation_worker_reports_traceback_on_failure(dialog_module, monkeypatch):
    worker = dialog_module._InterpolationWorker(
        "linear",
        "mesh.nc",
        "bedlevel",
        np.array([]),
        np.array([]),
        np.array([]),
        None,
        4326,
        "nearest",
    )
    worker.progress = MagicMock()
    worker.finished = MagicMock()
    worker.error = MagicMock()
    monkeypatch.setattr(
        dialog_module,
        "run_interpolation",
        MagicMock(side_effect=RuntimeError("interpolation failed")),
    )

    worker.run()

    worker.finished.emit.assert_not_called()
    error_message = worker.error.emit.call_args.args[0]
    assert "Traceback" in error_message
    assert "RuntimeError: interpolation failed" in error_message


def test_source_type_panels_follow_radio_selection(dialog_module):
    dialog = _dialog(dialog_module)
    dialog.panel_netcdf = MagicMock()
    dialog.panel_raster = MagicMock()
    dialog.panel_vector = MagicMock()

    for selected, expected in (
        ("netcdf", (True, False, False)),
        ("raster", (False, True, False)),
        ("vector", (False, False, True)),
    ):
        dialog.radio_netcdf.setChecked(selected == "netcdf")
        dialog.radio_raster.setChecked(selected == "raster")
        dialog.radio_vector.setChecked(selected == "vector")
        dialog._on_source_type_toggled()

        assert dialog.panel_netcdf.setVisible.call_args.args == (expected[0],)
        assert dialog.panel_raster.setVisible.call_args.args == (expected[1],)
        assert dialog.panel_vector.setVisible.call_args.args == (expected[2],)


def test_raster_and_vector_selections_populate_available_fields(dialog_module):
    dialog = _dialog(dialog_module)

    class Raster:
        def bandCount(self):
            return 2

        def bandName(self, band):
            return {1: "Elevation", 2: "Uncertainty"}[band]

    class Field:
        def __init__(self, name, numeric):
            self._name = name
            self._numeric = numeric

        def name(self):
            return self._name

        def isNumeric(self):
            return self._numeric

    class Vector:
        def fields(self):
            return [Field("bedlevel", True), Field("label", False)]

    dialog._selected_raster_layer = lambda: Raster()
    dialog._selected_vector_layer = lambda: Vector()
    dialog.combo_raster_band.addItem("stale", 99)
    dialog.combo_vector_attr.addItem("stale")

    dialog._on_raster_layer_changed()
    dialog._on_vector_layer_changed()

    assert [
        (dialog.combo_raster_band.itemText(index), dialog.combo_raster_band.itemData(index))
        for index in range(dialog.combo_raster_band.count())
    ] == [("1: Elevation", 1), ("2: Uncertainty", 2)]
    assert [dialog.combo_vector_attr.itemText(index) for index in range(
        dialog.combo_vector_attr.count()
    )] == ["bedlevel"]


def test_layer_population_filters_vector_geometry_types(dialog_module, monkeypatch):
    dialog = _dialog(dialog_module)

    class Raster:
        def __init__(self, name, layer_id):
            self._name = name
            self._id = layer_id

        def name(self):
            return self._name

        def id(self):
            return self._id

    class Vector:
        def __init__(self, name, layer_id, geometry_type):
            self._name = name
            self._id = layer_id
            self._geometry_type = geometry_type

        def name(self):
            return self._name

        def id(self):
            return self._id

        def geometryType(self):
            return self._geometry_type

    raster = Raster("DEM", "raster-id")
    point = Vector("Samples", "point-id", 1)
    line = Vector("Centerline", "line-id", 2)
    unknown = Vector("Unspecified", "unknown-id", 3)
    layers = {
        "raster": raster,
        "point": point,
        "line": line,
        "unknown": unknown,
    }
    project = SimpleNamespace(
        mapLayers=lambda: layers,
        mapLayer=lambda layer_id: {
            layer.id(): layer for layer in layers.values()
        }.get(layer_id),
    )
    monkeypatch.setattr(
        dialog_module,
        "QgsProject",
        SimpleNamespace(instance=lambda: project),
    )
    monkeypatch.setattr(dialog_module, "QgsRasterLayer", Raster)
    monkeypatch.setattr(dialog_module, "QgsVectorLayer", Vector)
    monkeypatch.setattr(
        dialog_module,
        "QgsWkbTypes",
        SimpleNamespace(PointGeometry=1, UnknownGeometry=3),
    )
    dialog._on_raster_layer_changed = MagicMock()
    dialog._on_vector_layer_changed = MagicMock()

    dialog._populate_qgis_layers()

    assert dialog.combo_raster_layer.itemText(0) == "DEM"
    assert dialog.combo_raster_layer.itemData(0) == "raster-id"
    assert [
        dialog.combo_vector_layer.itemText(index)
        for index in range(dialog.combo_vector_layer.count())
    ] == ["Samples", "Unspecified"]
    assert dialog.combo_vector_layer.itemData(1) == "unknown-id"
    dialog._on_raster_layer_changed.assert_called_once_with()
    dialog._on_vector_layer_changed.assert_called_once_with()
    assert dialog._selected_raster_layer() is raster
    assert dialog._selected_vector_layer() is point


def test_source_data_dispatches_to_selected_source_loader(dialog_module):
    dialog = _dialog(dialog_module)
    netcdf_result = (np.array([1]), np.array([2]), np.array([3]), 4326)
    raster_result = (np.array([4]), np.array([5]), np.array([6]), 28992)
    vector_result = (np.array([7]), np.array([8]), np.array([9]), 32631)
    dialog._load_source_netcdf = MagicMock(return_value=netcdf_result)
    dialog._load_source_raster = MagicMock(return_value=raster_result)
    dialog._load_source_vector = MagicMock(return_value=vector_result)

    assert dialog._load_source_data() == netcdf_result
    dialog.radio_netcdf.setChecked(False)
    dialog.radio_raster.setChecked(True)
    assert dialog._load_source_data() == raster_result
    dialog.radio_raster.setChecked(False)
    dialog.radio_vector.setChecked(True)
    assert dialog._load_source_data() == vector_result
    dialog._load_source_netcdf.assert_called_once_with()
    dialog._load_source_raster.assert_called_once_with()
    dialog._load_source_vector.assert_called_once_with()


def test_vector_loader_skips_invalid_attributes_and_geometries(dialog_module):
    dialog = _dialog(dialog_module)

    class Point:
        def __init__(self, x, y):
            self._x = x
            self._y = y

        def x(self):
            return self._x

        def y(self):
            return self._y

    class Geometry:
        def __init__(self, point=None, empty=False):
            self._point = point
            self._empty = empty

        def isEmpty(self):
            return self._empty

        def centroid(self):
            return self

        def asPoint(self):
            return self._point

    class Feature:
        def __init__(self, value, geometry):
            self._value = value
            self._geometry = geometry

        def __getitem__(self, _attribute):
            return self._value

        def geometry(self):
            return self._geometry

    class Layer:
        def crs(self):
            return SimpleNamespace(authid=lambda: "EPSG:28992")

        def getFeatures(self):
            return iter(
                [
                    Feature(3.5, Geometry(Point(10, 20))),
                    Feature(None, Geometry(Point(11, 21))),
                    Feature("invalid", Geometry(Point(12, 22))),
                    Feature(4.5, None),
                    Feature(5.5, Geometry(empty=True)),
                ]
            )

    dialog.combo_vector_attr.addItem("elevation")
    dialog._selected_vector_layer = lambda: Layer()

    x, y, z, epsg = dialog._load_source_vector()

    assert np.array_equal(x, [10])
    assert np.array_equal(y, [20])
    assert np.array_equal(z, [3.5])
    assert epsg == 28992


def test_validate_reports_required_inputs_and_same_path_output(dialog_module, tmp_path, monkeypatch):
    mesh_path = tmp_path / "mesh.nc"
    source_path = tmp_path / "source.nc"
    mesh_path.touch()
    source_path.touch()
    dialog = _dialog(dialog_module, str(mesh_path), str(source_path))
    dialog.combo_z_var.addItem("bedlevel")
    dialog.combo_src_var.addItem("elevation")
    message_box = _message_box(dialog_module, monkeypatch)

    dialog.mesh_path_edit.setText(str(tmp_path / "missing.nc"))
    assert dialog._validate() is False
    message_box.warning.assert_called_with(
        dialog,
        "Missing input",
        "Please select a valid mesh file.",
    )

    dialog.mesh_path_edit.setText(str(mesh_path))
    dialog.output_mesh_edit.setText(str(tmp_path / "missing" / "out.nc"))
    assert dialog._validate() is False
    message_box.warning.assert_called_with(
        dialog,
        "Invalid output",
        "The output folder does not exist.",
    )

    dialog.output_mesh_edit.setText(str(mesh_path))
    assert dialog._validate() is True
    assert dialog.output_mesh_edit.text() == ""

    dialog.combo_z_var.clear()
    assert dialog._validate() is False

    dialog.combo_z_var.addItem("bedlevel")
    dialog.src_path_edit.setText(str(tmp_path / "missing-source.nc"))
    assert dialog._validate() is False

    dialog.src_path_edit.setText(str(source_path))
    dialog.combo_src_var.clear()
    assert dialog._validate() is False


def test_validate_checks_raster_and_vector_layer_selections(dialog_module, tmp_path, monkeypatch):
    mesh_path = tmp_path / "mesh.nc"
    mesh_path.touch()
    dialog = _dialog(dialog_module, str(mesh_path))
    dialog.combo_z_var.addItem("bedlevel")
    dialog._selected_raster_layer = lambda: None
    dialog._selected_vector_layer = lambda: None
    _message_box(dialog_module, monkeypatch)

    dialog.radio_netcdf.setChecked(False)
    dialog.radio_raster.setChecked(True)
    assert dialog._validate() is False

    dialog.radio_raster.setChecked(False)
    dialog.radio_vector.setChecked(True)
    assert dialog._validate() is False

    dialog._selected_vector_layer = lambda: object()
    assert dialog._validate() is False
    dialog.combo_vector_attr.addItem("bedlevel")
    assert dialog._validate() is True


def test_run_guard_empty_source_and_worker_success(dialog_module, monkeypatch):
    message_box = _message_box(dialog_module, monkeypatch)
    dialog = _dialog(dialog_module, "mesh.nc", "source.nc")
    dialog._worker = SimpleNamespace(isRunning=lambda: True)
    dialog._validate = MagicMock()
    dialog._on_run()
    dialog._validate.assert_not_called()

    dialog._worker = None
    dialog._validate = MagicMock(return_value=True)
    dialog._load_source_data = MagicMock(
        return_value=(np.array([]), np.array([]), np.array([]), 4326)
    )
    dialog.run_btn = MagicMock()
    dialog.status_label = FakeTextControl()
    dialog._on_run()
    message_box.warning.assert_called_once()
    dialog.run_btn.setEnabled.assert_called_with(True)
    assert dialog.status_label.text() == ""

    source_data = (
        np.array([1.0, 2.0]),
        np.array([3.0, 4.0]),
        np.array([5.0, 6.0]),
        4326,
    )
    dialog._load_source_data = MagicMock(return_value=source_data)
    dialog.combo_method = FakeComboBox()
    dialog.combo_method.addItem("Linear", "linear")
    dialog.combo_outside_policy = FakeComboBox()
    dialog.combo_outside_policy.addItem("Nearest", "nearest")
    dialog.combo_z_var = FakeComboBox()
    dialog.combo_z_var.addItem("bedlevel")
    dialog.mesh_path_edit = FakeTextControl("mesh.nc")
    dialog.output_mesh_edit = FakeTextControl()
    dialog._mesh_epsg = MagicMock(return_value=28992)
    dialog.progress_bar = MagicMock()
    dialog.iface = SimpleNamespace(messageBar=lambda: SimpleNamespace(pushSuccess=MagicMock()))

    worker = SimpleNamespace(
        progress=FakeSignal(),
        finished=FakeSignal(),
        error=FakeSignal(),
        started=False,
    )
    worker.start = lambda: setattr(worker, "started", True)
    worker_factory = MagicMock(return_value=worker)
    monkeypatch.setattr(dialog_module, "_InterpolationWorker", worker_factory)

    dialog._on_run()

    worker_factory.assert_called_once()
    assert worker_factory.call_args.kwargs["method"] == "linear"
    assert worker_factory.call_args.kwargs["mesh_path"] == "mesh.nc"
    assert worker_factory.call_args.kwargs["source_epsg"] == 4326
    assert worker.started is True
    assert dialog._target_mesh_path == "mesh.nc"

    worker.progress.emit(1, 2)
    dialog.progress_bar.setValue.assert_any_call(50)
    worker.finished.emit(2)
    assert "Done. 2 mesh node(s) updated." == dialog.status_label.text()
    assert dialog.progress_bar.setValue.call_args.args == (100,)


def test_progress_error_and_close_handlers(dialog_module, monkeypatch):
    message_box = _message_box(dialog_module, monkeypatch)
    dialog = _dialog(dialog_module, "mesh.nc")
    dialog.progress_bar = MagicMock()
    dialog.run_btn = MagicMock()
    dialog.status_label = FakeTextControl()
    dialog.iface = SimpleNamespace(
        messageBar=lambda: SimpleNamespace(pushSuccess=MagicMock())
    )
    dialog._target_mesh_path = ""

    dialog._on_progress(1, 0)
    dialog.progress_bar.setValue.assert_called_once_with(0)
    dialog.progress_bar.setValue.reset_mock()
    dialog._on_error("failed")
    assert dialog.status_label.text() == "Failed – see error dialog."
    message_box.critical.assert_called_once_with(
        dialog,
        "Interpolation error",
        "failed",
    )

    dialog.refresh_dependency_status = MagicMock()
    dialog._show_missing_netcdf4_message("read a file")
    dialog.refresh_dependency_status.assert_called_once_with()
    assert dialog.status_label.text() == "Missing dependency: netCDF4"
    message_box.warning.assert_called_once()

    dialog._worker = SimpleNamespace(isRunning=lambda: True)
    dialog.reject()
    message_box.information.assert_called_once()
    dialog._worker = None
    dialog.reject()
    assert dialog._rejected is True
