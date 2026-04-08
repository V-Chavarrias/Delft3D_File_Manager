import sys
from unittest.mock import MagicMock

# Stub all QGIS/PyQt modules before any plugin code is imported.
# Must be at module level so it runs before test collection imports the plugin.
for _mod_name in [
    "qgis",
    "qgis.core",
    "qgis.PyQt",
    "qgis.PyQt.QtWidgets",
    "qgis.PyQt.QtGui",
    "PyQt5",
    "PyQt5.QtCore",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

import pytest


@pytest.fixture
def plugin():
    from Delft3DFileManager.Delft3DFileManager import Delft3DFileManager
    return Delft3DFileManager(MagicMock())
