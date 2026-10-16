from unittest.mock import MagicMock

import pytest

from tests.fixtures_qgis_mocks import install_qgis_mocks

install_qgis_mocks()


@pytest.fixture
def plugin():
    from Delft3DFileManager.Delft3DFileManager import Delft3DFileManager
    return Delft3DFileManager(MagicMock())


@pytest.fixture
def strict_iface():
    from tests.fixtures_qgis_fakes import FakeQgisInterface
    return FakeQgisInterface()


@pytest.fixture
def strict_plugin(strict_iface):
    from Delft3DFileManager.Delft3DFileManager import Delft3DFileManager
    return Delft3DFileManager(strict_iface)


@pytest.fixture
def strict_project(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module
    from tests.fixtures_qgis_fakes import FakeQgsProject

    FakeQgsProject.reset_instance()
    monkeypatch.setattr(plugin_module, "QgsProject", FakeQgsProject)
    return FakeQgsProject.instance()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    tier_markers = ("unit", "qgis_runtime", "e2e")
    for item in items:
        if not any(item.get_closest_marker(marker) for marker in tier_markers):
            item.add_marker(pytest.mark.unit)
