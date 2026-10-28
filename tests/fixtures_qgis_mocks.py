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
_QGIS_IMPORT_SYMBOLS = {
    "qgis.core": ("QgsProject", "QgsMeshDatasetGroupMetadata"),
    "qgis.PyQt.QtWidgets": ("QDialog",),
}
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

    for module_name, symbol_names in _QGIS_IMPORT_SYMBOLS.items():
        module = sys.modules[module_name]
        if not isinstance(module, MagicMock):
            continue
        for symbol_name in symbol_names:
            try:
                getattr(module, symbol_name)
            except AttributeError:
                setattr(
                    module,
                    symbol_name,
                    MagicMock(name=f"{module_name}.{symbol_name}"),
                )


def qgis_mocks_installed():
    return _qgis_mocks_installed
