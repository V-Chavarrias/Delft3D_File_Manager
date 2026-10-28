import importlib
import sys

import pytest

import Delft3DFileManager.one_d_results_dialog as one_d_dialog_module
from tests.fixtures_qgis_mocks import install_qgis_mocks
from tests.fixtures_qgis_fakes import (
    FakeAction,
    FakeComboBox,
    FakeCRS,
    FakeFeature,
    FakeField,
    FakeGeometry,
    FakeMenu,
    FakeQgisInterface,
    FakeQgsProject,
    FakeVectorLayer,
)


def test_qgis_mock_installer_restores_required_import_symbols(monkeypatch):
    symbols = [
        (sys.modules["qgis.core"], "QgsProject"),
        (sys.modules["qgis.core"], "QgsMeshDatasetGroupMetadata"),
        (sys.modules["qgis.PyQt.QtWidgets"], "QDialog"),
    ]
    for module, name in symbols:
        monkeypatch.setattr(module, name, getattr(module, name))
        delattr(module, name)

    install_qgis_mocks()

    for module, name in symbols:
        assert getattr(module, name) is not None


def test_action_menu_and_combo_box_fakes_are_strict():
    iface = FakeQgisInterface()
    action = FakeAction(None, "Import", iface.mainWindow())
    calls = []
    action.triggered.connect(lambda: calls.append(action.text()))

    menu = FakeMenu("Tools", iface.mainWindow())
    assert menu.addAction(action) is action
    action.trigger()

    assert menu.title() == "Tools"
    assert menu.menuAction().text() == "Tools"
    assert menu.actions() == [action]
    assert calls == ["Import"]
    with pytest.raises(AttributeError):
        action.setUnsupportedState(True)

    combo = FakeComboBox()
    index_changes = []
    combo.currentIndexChanged.connect(index_changes.append)
    combo.addItem("Water level", "s1")
    combo.addItem("Velocity", "velocity")
    combo.setCurrentIndex(1)

    assert combo.count() == 2
    assert combo.currentText() == "Velocity"
    assert combo.currentData() == "velocity"
    assert index_changes == [0, 1]
    with pytest.raises(AttributeError):
        combo.unsupportedMethod()


def test_results_dialog_controls_use_real_option_selection_logic(monkeypatch):
    original_module_state = dict(one_d_dialog_module.__dict__)

    class FakeDialogBase:
        pass

    monkeypatch.setattr(
        sys.modules["qgis.PyQt.QtWidgets"],
        "QDialog",
        FakeDialogBase,
    )
    try:
        importlib.reload(one_d_dialog_module)
        dialog_type = one_d_dialog_module.OneDResultsDialog
        dialog = object.__new__(dialog_type)
        dialog._variable_combo = FakeComboBox()
        dialog._time_combo = FakeComboBox()

        dialog.set_variable_options(
            [("mesh2d_s1", "Water level"), ("mesh2d_ucx", "Velocity")],
            selected_value="mesh2d_ucx",
        )
        dialog.set_time_options(
            [(0, "2020-01-01 00:00"), (1, "2020-01-01 01:00")],
            selected_value=1,
        )

        assert dialog.selected_variable() == "mesh2d_ucx"
        assert dialog.selected_time_value() == 1
        assert dialog._variable_combo.currentText() == "Velocity"
        assert dialog._time_combo.currentText() == "2020-01-01 01:00"
    finally:
        module_state = one_d_dialog_module.__dict__
        for name in set(module_state).difference(original_module_state):
            del module_state[name]
        module_state.update(original_module_state)


def test_layer_feature_crs_and_project_fakes_keep_explicit_state():
    feature = FakeFeature(
        {"name": "station_a"},
        FakeGeometry.from_points([(1.25, 2.5)]),
    )
    layer = FakeVectorLayer(
        "observations",
        [FakeField("name")],
        [feature],
        layer_type="vector",
        geometry_type="point",
        crs=FakeCRS("EPSG:28992"),
    )
    project = FakeQgsProject()

    assert project.addMapLayer(layer) is layer
    assert project.mapLayers() == {layer.id(): layer}
    assert layer.crs().authid() == "EPSG:28992"
    assert layer.featureCount() == 1
    assert list(layer.getFeatures()) == [feature]
    assert feature["name"] == "station_a"
    assert feature.geometry().asPoint().x() == 1.25

    project.removeMapLayer(layer.id())
    assert project.mapLayers() == {}
