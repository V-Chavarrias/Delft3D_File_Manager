from collections import Counter
import importlib
import runpy
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from tests.menu_expectations import SUBMENU_ACTIONS, TOP_LEVEL_MENU_ACTIONS


pytestmark = [pytest.mark.qgis_runtime, pytest.mark.e2e]

_PLUGIN_PACKAGE = "Delft3DFileManager"


class _RecordingMessageBar:
    def __init__(self):
        self.warnings = []

    def pushWarning(self, title, text):
        self.warnings.append((title, text))


class _RecordingQgisInterface:
    def __init__(self, main_window, map_canvas):
        self._main_window = main_window
        self._map_canvas = map_canvas
        self._message_bar = _RecordingMessageBar()
        self.menu_additions = []
        self.menu_removals = []
        self.toolbar_additions = []
        self.toolbar_removals = []

    def mainWindow(self):
        return self._main_window

    def mapCanvas(self):
        return self._map_canvas

    def messageBar(self):
        return self._message_bar

    def addPluginToMenu(self, menu_name, action):
        self.menu_additions.append((menu_name, action))

    def removePluginMenu(self, menu_name, action):
        self.menu_removals.append((menu_name, action))

    def addToolBarIcon(self, action):
        self.toolbar_additions.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar_removals.append(action)


def test_packaged_plugin_loads_initializes_and_unloads(
    qgis_application, monkeypatch, tmp_path
):
    assert qgis_application is not None

    repository_root = Path(__file__).resolve().parents[2]
    source_plugin = repository_root / _PLUGIN_PACKAGE
    build_root = tmp_path / "build"
    build_root.mkdir()
    shutil.copytree(source_plugin, build_root / _PLUGIN_PACKAGE)
    for filename in ("LICENSE", "README.md"):
        shutil.copy2(repository_root / filename, build_root / filename)

    monkeypatch.chdir(build_root)
    runpy.run_path(str(repository_root / "build_plugin.py"), run_name="__main__")
    archives = list(build_root.glob("Delft3D_File_Manager_v*.zip"))
    assert len(archives) == 1, f"Expected one plugin archive, found {archives}"

    extracted_root = tmp_path / "plugins"
    extracted_root.mkdir()
    with zipfile.ZipFile(archives[0]) as archive:
        archive_names = set(archive.namelist())
        expected_source_entries = {
            f"{_PLUGIN_PACKAGE}/{path.relative_to(source_plugin).as_posix()}"
            for path in source_plugin.rglob("*")
            if path.is_file()
            and (path.suffix == ".py" or path.name.startswith("icon"))
        }
        required_entries = {
            f"{_PLUGIN_PACKAGE}/metadata.txt",
            f"{_PLUGIN_PACKAGE}/README.md",
            f"{_PLUGIN_PACKAGE}/__init__.py",
            f"{_PLUGIN_PACKAGE}/Delft3DFileManager.py",
            f"{_PLUGIN_PACKAGE}/icon.svg",
            f"{_PLUGIN_PACKAGE}/icon-import.svg",
        }
        missing_entries = (expected_source_entries | required_entries) - archive_names
        assert not missing_entries, (
            f"Plugin archive is missing required files: {sorted(missing_entries)}"
        )
        archive.extractall(extracted_root)

    plugin_directory = extracted_root / _PLUGIN_PACKAGE
    previous_plugin_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == _PLUGIN_PACKAGE or name.startswith(f"{_PLUGIN_PACKAGE}.")
    }
    for name in previous_plugin_modules:
        del sys.modules[name]
    monkeypatch.syspath_prepend(str(extracted_root))
    importlib.invalidate_caches()

    try:
        entrypoint = importlib.import_module(_PLUGIN_PACKAGE)
        assert Path(entrypoint.__file__).resolve() == (
            plugin_directory / "__init__.py"
        ).resolve()

        plugin_module = importlib.import_module(
            f"{_PLUGIN_PACKAGE}.Delft3DFileManager"
        )
        assert Path(plugin_module.__file__).resolve() == (
            plugin_directory / "Delft3DFileManager.py"
        ).resolve()

        from qgis.gui import QgsMapCanvas
        from qgis.PyQt.QtWidgets import QAction, QMainWindow

        main_window = QMainWindow()
        map_canvas = QgsMapCanvas(main_window)
        iface = _RecordingQgisInterface(main_window, map_canvas)
        plugin = entrypoint.classFactory(iface)
        try:
            plugin.initGui()

            assert tuple(action.text() for _, action in iface.menu_additions) == (
                TOP_LEVEL_MENU_ACTIONS
            )
            assert (
                plugin.viewer_menu.title(),
                tuple(action.text() for action in plugin.viewer_menu.actions()),
            ) == SUBMENU_ACTIONS[0]
            assert (
                plugin.compute_2d_variables_menu.title(),
                tuple(
                    action.text()
                    for action in plugin.compute_2d_variables_menu.actions()
                ),
            ) == SUBMENU_ACTIONS[1]
            assert isinstance(plugin.import_action, QAction)
            assert isinstance(plugin.export_action, QAction)
            assert not plugin.import_action.icon().isNull()
            assert plugin._canvas_double_click_connected

            toolbar_action_names = {
                action.text() for action in iface.toolbar_additions
            }
            assert {"Import", "Export", "Large MAP Viewer"} <= toolbar_action_names
        finally:
            plugin.unload()

        assert not plugin._canvas_double_click_connected
        assert Counter(
            (menu_name, id(action)) for menu_name, action in iface.menu_additions
        ) == Counter(
            (menu_name, id(action)) for menu_name, action in iface.menu_removals
        )
        assert Counter(map(id, iface.toolbar_additions)) == Counter(
            map(id, iface.toolbar_removals)
        )
        map_canvas.close()
        main_window.close()
    finally:
        for name in tuple(sys.modules):
            if name == _PLUGIN_PACKAGE or name.startswith(f"{_PLUGIN_PACKAGE}."):
                del sys.modules[name]
        sys.modules.update(previous_plugin_modules)
