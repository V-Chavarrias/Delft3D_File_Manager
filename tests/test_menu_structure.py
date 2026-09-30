from unittest.mock import MagicMock, call

import Delft3DFileManager.Delft3DFileManager as plugin_module


def test_menu_structure_and_viewer_callbacks(monkeypatch):
    menus = []

    class FakeSignal:
        def connect(self, callback):
            self.callback = callback

    class FakeAction:
        def __init__(self, icon, text, parent):
            self.icon = icon
            self.label = text
            self.parent = parent
            self.triggered = FakeSignal()

        def setStatusTip(self, tip):
            self.status_tip = tip

    class FakeMenu:
        def __init__(self, label, parent):
            self.label = label
            self.parent = parent
            self.actions = []
            self._menu_action = object()
            menus.append(self)

        def addAction(self, action):
            self.actions.append(action)

        def menuAction(self):
            return self._menu_action

    monkeypatch.setattr(plugin_module, "QAction", FakeAction)
    monkeypatch.setattr(plugin_module, "QMenu", FakeMenu)

    iface = MagicMock()
    plugin = plugin_module.Delft3DFileManager(iface)
    plugin.initGui()

    assert [menu.label for menu in menus] == ["viewer", "Compute 2D variables"]
    assert [action.label for action in plugin.viewer_menu.actions] == [
        "Cross-section",
        "HIS time series",
        "1D MAP",
        "2D slice",
        "Boundary conditions",
    ]
    assert [action.label for action in plugin.compute_2d_variables_menu.actions] == [
        "Streamfunction",
        "Mesh properties",
    ]
    assert plugin.profile_chart_action.triggered.callback == plugin.open_cross_section_profile_window
    assert plugin.boundary_conditions_action.triggered.callback == plugin.open_cross_section_profile_window

    registered = [entry.args[1] for entry in iface.addPluginToMenu.call_args_list]
    assert registered[:3] == [
        plugin.install_deps_action,
        plugin.viewer_menu.menuAction(),
        plugin.compute_2d_variables_menu.menuAction(),
    ]
    assert registered[3:] == [
        plugin.import_action,
        plugin.export_action,
        plugin.bed_level_action,
        plugin.create_trachytopes_action,
        plugin.create_bridge_points_action,
        plugin.create_fixed_weir_points_action,
        plugin.create_1d_network_action,
        plugin.update_trachytopes_action,
        plugin.export_trachytopes_action,
        plugin.export_pointcloud_action,
    ]

    plugin.unload()
    removed = [entry.args[1] for entry in iface.removePluginMenu.call_args_list]
    assert plugin.viewer_menu.menuAction() in removed
    assert plugin.compute_2d_variables_menu.menuAction() in removed
    assert plugin.boundary_conditions_action not in removed
