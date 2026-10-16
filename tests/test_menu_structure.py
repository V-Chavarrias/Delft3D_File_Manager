from unittest.mock import MagicMock

import Delft3DFileManager.Delft3DFileManager as plugin_module
from tests.menu_expectations import SUBMENU_ACTIONS, TOP_LEVEL_MENU_ACTIONS


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

    expected_submenus = dict(SUBMENU_ACTIONS)
    assert [menu.label for menu in menus] == list(expected_submenus)
    assert [action.label for action in plugin.viewer_menu.actions] == [
        *expected_submenus["Viewer"],
    ]
    assert [action.label for action in plugin.compute_2d_variables_menu.actions] == [
        *expected_submenus["Compute 2D Variables"],
    ]
    assert plugin.profile_chart_action.triggered.callback == plugin.open_cross_section_profile_window
    assert plugin.boundary_conditions_action.triggered.callback == plugin.open_cross_section_profile_window
    assert plugin.create_mesh_polyline_action.triggered.callback == plugin.create_polyline_from_mesh
    assert plugin.mesh_difference_action.triggered.callback == plugin.compute_mesh_difference
    assert plugin.large_map_action.triggered.callback == plugin.open_large_map_viewer
    assert plugin.export_action.triggered.callback == plugin.export_active_layer
    assert ".xyn" in plugin.export_action.status_tip

    registered = [entry.args[1] for entry in iface.addPluginToMenu.call_args_list]
    submenu_labels = {
        plugin.viewer_menu.menuAction(): plugin.viewer_menu.label,
        plugin.compute_2d_variables_menu.menuAction(): (
            plugin.compute_2d_variables_menu.label
        ),
    }
    registered_labels = [
        submenu_labels[action] if action in submenu_labels else action.label
        for action in registered
    ]
    assert registered_labels == list(TOP_LEVEL_MENU_ACTIONS)
    assert not hasattr(plugin, "export_pointcloud_action")
    toolbar_actions = [
        entry.args[0] for entry in iface.addToolBarIcon.call_args_list
    ]
    assert toolbar_actions == [
        plugin.import_action,
        plugin.export_action,
        plugin.profile_chart_action,
        plugin.one_d_results_action,
        plugin.mesh_profile_action,
        plugin.his_timeseries_action,
        plugin.large_map_action,
        plugin.mesh_difference_action,
    ]

    plugin.unload()
    removed = [entry.args[1] for entry in iface.removePluginMenu.call_args_list]
    assert plugin.viewer_menu.menuAction() in removed
    assert plugin.compute_2d_variables_menu.menuAction() in removed
    assert plugin.open_guide_action in removed
    assert plugin.create_mesh_polyline_action in removed
    assert plugin.boundary_conditions_action not in removed
    assert plugin.export_action in removed
    iface.removeToolBarIcon.assert_any_call(plugin.mesh_difference_action)
    iface.removeToolBarIcon.assert_any_call(plugin.large_map_action)
