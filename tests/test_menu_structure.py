import Delft3DFileManager.Delft3DFileManager as plugin_module
from tests.menu_expectations import SUBMENU_ACTIONS, TOP_LEVEL_MENU_ACTIONS
from tests.fixtures_qgis_fakes import FakeAction, FakeMenu, FakeQgisInterface


def test_menu_structure_and_viewer_callbacks(monkeypatch):
    monkeypatch.setattr(plugin_module, "QAction", FakeAction)
    monkeypatch.setattr(plugin_module, "QMenu", FakeMenu)

    iface = FakeQgisInterface()
    plugin = plugin_module.Delft3DFileManager(iface)
    plugin.initGui()

    expected_submenus = dict(SUBMENU_ACTIONS)
    menus = [plugin.viewer_menu, plugin.compute_2d_variables_menu]
    assert [menu.title() for menu in menus] == list(expected_submenus)
    assert [action.text() for action in plugin.viewer_menu.actions()] == [
        *expected_submenus["Viewer"],
    ]
    assert [action.text() for action in plugin.compute_2d_variables_menu.actions()] == [
        *expected_submenus["Compute 2D Variables"],
    ]
    assert plugin.profile_chart_action.triggered.callback == plugin.open_cross_section_profile_window
    assert plugin.boundary_conditions_action.triggered.callback == plugin.open_cross_section_profile_window
    assert plugin.create_mesh_polyline_action.triggered.callback == plugin.create_polyline_from_mesh
    assert plugin.mesh_difference_action.triggered.callback == plugin.compute_mesh_difference
    assert plugin.large_map_action.triggered.callback == plugin.open_large_map_viewer
    assert plugin.export_action.triggered.callback == plugin.export_active_layer
    assert ".xyn" in plugin.export_action.statusTip()

    registered = [action for _menu_name, action in iface.menu_additions]
    submenu_labels = {
        plugin.viewer_menu.menuAction(): plugin.viewer_menu.title(),
        plugin.compute_2d_variables_menu.menuAction(): (
            plugin.compute_2d_variables_menu.title()
        ),
    }
    registered_labels = [
        submenu_labels[action] if action in submenu_labels else action.text()
        for action in registered
    ]
    assert registered_labels == list(TOP_LEVEL_MENU_ACTIONS)
    assert not hasattr(plugin, "export_pointcloud_action")
    toolbar_actions = iface.toolbar_additions
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
    removed = [action for _menu_name, action in iface.menu_removals]
    assert plugin.viewer_menu.menuAction() in removed
    assert plugin.compute_2d_variables_menu.menuAction() in removed
    assert plugin.open_guide_action in removed
    assert plugin.create_mesh_polyline_action in removed
    assert plugin.boundary_conditions_action not in removed
    assert plugin.export_action in removed
    assert plugin.mesh_difference_action in iface.toolbar_removals
    assert plugin.large_map_action in iface.toolbar_removals
