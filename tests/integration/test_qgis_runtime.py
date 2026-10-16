import os
from types import SimpleNamespace

import pytest

from tests.fixtures_qgis_fakes import FakeQgisInterface
from tests.fixtures_qgis_mocks import qgis_mocks_installed


pytestmark = pytest.mark.qgis_runtime


@pytest.fixture(scope="session")
def qgis_runtime():
    if qgis_mocks_installed():
        pytest.skip(
            "Run the QGIS runtime tier with --confcutdir=tests\\integration "
            "to bypass the unit-test QGIS stubs."
        )

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from qgis.core import QgsApplication
    except ImportError as exc:
        pytest.skip(f"QGIS runtime is unavailable: {exc}")

    prefix_path = os.environ.get("QGIS_PREFIX_PATH")
    if prefix_path:
        QgsApplication.setPrefixPath(prefix_path, True)

    application = QgsApplication.instance()
    owns_application = application is None
    if owns_application:
        application = QgsApplication([], False)
        application.initQgis()

    try:
        yield application
    finally:
        if owns_application:
            application.exitQgis()


@pytest.mark.e2e
def test_bridge_import_and_export_use_real_qgis_layers(
    qgis_runtime,
    monkeypatch,
    tmp_path,
):
    from qgis.core import QgsProject
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    source = tmp_path / "incoming.pliz"
    source.write_text(
        "Test Bridge\n2 4\n"
        "120000 450000 2.5 1.0\n"
        "120100 450100 2.5 1.0\n",
        encoding="ascii",
    )
    output_base = tmp_path / "exported"
    project = QgsProject.instance()
    original_layer_ids = set(project.mapLayers())
    iface = FakeQgisInterface()
    plugin = plugin_module.Delft3DFileManager(iface)
    monkeypatch.setattr(
        plugin_module,
        "QFileDialog",
        SimpleNamespace(
            getSaveFileName=lambda *_args: (str(output_base), ""),
        ),
    )

    try:
        plugin.load_bridge_file(str(source))
        new_layers = {
            layer_id: layer
            for layer_id, layer in project.mapLayers().items()
            if layer_id not in original_layer_ids
        }
        assert len(new_layers) == 2
        point_layer = next(
            layer for layer in new_layers.values() if layer.name() == "incoming_points"
        )
        assert point_layer.isValid()
        assert point_layer.featureCount() == 2

        iface.setActiveLayer(point_layer)
        plugin.export_active_layer()

        output = output_base.with_suffix(".pliz")
        assert output.read_text(encoding="ascii") == (
            "Test Bridge\n2 4\n"
            "120000.000000 450000.000000 2.500000 1.000000\n"
            "120100.000000 450100.000000 2.500000 1.000000\n"
        )
        assert len(iface.messageBar().success_messages) == 2
    finally:
        for layer_id in set(project.mapLayers()) - original_layer_ids:
            project.removeMapLayer(layer_id)
