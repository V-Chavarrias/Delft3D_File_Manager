import sys
from types import ModuleType
from unittest.mock import MagicMock


_QGIS_MODULE_NAMES = (
    "qgis",
    "qgis.core",
    "qgis.PyQt",
    "qgis.PyQt.QtCore",
    "qgis.PyQt.QtWidgets",
    "qgis.PyQt.QtGui",
)
_qgis_mocks_installed = False


def install_qgis_mocks():
    global _qgis_mocks_installed

    for module_name in _QGIS_MODULE_NAMES:
        if module_name not in sys.modules:
            sys.modules[module_name] = MagicMock(name=module_name)
            _qgis_mocks_installed = True

    if "qgis.gui" not in sys.modules:
        qgis_gui = ModuleType("qgis.gui")

        class QgsMapTool:
            def __init__(self, canvas):
                self.canvas = canvas

            def deactivate(self):
                pass

        qgis_gui.QgsMapTool = QgsMapTool
        qgis_gui.QgsRubberBand = MagicMock(name="qgis.gui.QgsRubberBand")
        sys.modules["qgis.gui"] = qgis_gui
        _qgis_mocks_installed = True


def qgis_mocks_installed():
    return _qgis_mocks_installed
