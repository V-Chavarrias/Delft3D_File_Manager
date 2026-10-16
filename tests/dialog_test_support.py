from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from tests.fixtures_qgis_mocks import install_qgis_mocks


class FakeQtWidget:
    def __init__(self, parent=None):
        self._parent = parent
        self._enabled = True

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

    def setWindowTitle(self, title):
        self._window_title = title

    def setWindowFlag(self, flag, enabled):
        del flag, enabled

    def setSizeGripEnabled(self, enabled):
        del enabled

    def setMinimumWidth(self, width):
        self._minimum_width = width

    def setMinimumSize(self, width, height):
        self._minimum_size = (width, height)

    def resize(self, width, height):
        self._size = (width, height)

    def setSizePolicy(self, horizontal, vertical):
        self._size_policy = (horizontal, vertical)

    def deleteLater(self):
        self._deleted = True

    def reject(self):
        self._rejected = True


class FakeQtDialog(FakeQtWidget):
    pass


class FakeQtThread:
    def __init__(self, parent=None):
        self._parent = parent


class FakeTextControl:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def clear(self):
        self._text = ""


class FakeToggleButton:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


class FakeListWidget:
    def __init__(self):
        self.items = []

    def clear(self):
        self.items.clear()

    def addItem(self, item):
        self.items.append(str(item))


def load_dialog_module(
    monkeypatch,
    filename,
    module_key,
    package="tests",
    qt_core_overrides=None,
):
    install_qgis_mocks()
    qt_widgets = sys.modules["qgis.PyQt.QtWidgets"]
    monkeypatch.setattr(qt_widgets, "QWidget", FakeQtWidget, raising=False)
    monkeypatch.setattr(qt_widgets, "QDialog", FakeQtDialog, raising=False)
    qt_core = sys.modules["qgis.PyQt.QtCore"]
    for name, value in (qt_core_overrides or {}).items():
        monkeypatch.setattr(qt_core, name, value, raising=False)

    source_path = (
        Path(__file__).resolve().parents[1] / "Delft3DFileManager" / filename
    )
    module_name = f"{package}._unit_{module_key}"
    spec = spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load dialog module: {source_path}")

    module = module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def new_widget_instance(widget_class):
    widget = object.__new__(widget_class)
    FakeQtWidget.__init__(widget)
    return widget
