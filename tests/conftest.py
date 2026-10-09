import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub all QGIS/PyQt modules before any plugin code is imported.
# Must be at module level so it runs before test collection imports the plugin.
for _mod_name in [
    "qgis",
    "qgis.core",
    "qgis.PyQt",
    "qgis.PyQt.QtCore",
    "qgis.PyQt.QtWidgets",
    "qgis.PyQt.QtGui",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

if "qgis.gui" not in sys.modules:
    _qgis_gui = ModuleType("qgis.gui")

    class _QgsMapTool:
        def __init__(self, canvas):
            self.canvas = canvas

        def deactivate(self):
            pass

    _qgis_gui.QgsMapTool = _QgsMapTool
    _qgis_gui.QgsRubberBand = MagicMock()
    sys.modules["qgis.gui"] = _qgis_gui

import pytest


@pytest.fixture
def plugin():
    from Delft3DFileManager.Delft3DFileManager import Delft3DFileManager
    return Delft3DFileManager(MagicMock())
