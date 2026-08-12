# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsMapLayerType, QgsWkbTypes, QgsSpatialIndex,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol
)
from qgis.PyQt.QtCore import QDateTime, QEvent, QObject, QVariant, Qt, QTimer, QT_VERSION_STR
from datetime import datetime, timedelta
import itertools
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import glob
try:
    from defusedxml import ElementTree as ET
    _HAS_DEFUSEDXML = True
except ImportError:
    ET = None
    _HAS_DEFUSEDXML = False


_IMPORT_PROGRESS_DIALOG_OBJECT_NAME = "Delft3DFileManagerImportProgressDialog"


def _qt_major_version():
    """Return Qt major version as int when available, otherwise None."""
    raw = ""
    try:
        raw = str(QT_VERSION_STR or "")
    except Exception:
        raw = ""

    if not raw:
        return None

    token = raw.split(".", 1)[0].strip()
    if not token.isdigit():
        return None
    return int(token)


def _is_qt6_runtime():
    """Return True when plugin runs under Qt6 (QGIS4)."""
    major = _qt_major_version()
    return major == 6


def _double_click_event_type():
    """Return the Qt enum value for mouse double-click across Qt5/Qt6."""
    event_type = getattr(QEvent, "MouseButtonDblClick", None)
    if event_type is None:
        event_type = getattr(getattr(QEvent, "Type", None), "MouseButtonDblClick", None)
    return event_type


def _left_mouse_button_value():
    """Return the Qt enum value for left mouse button across Qt5/Qt6."""
    left_button = getattr(Qt, "LeftButton", None)
    if left_button is None:
        left_button = getattr(getattr(Qt, "MouseButton", None), "LeftButton", None)
    return left_button


def _qmessagebox_icon_question():
    """Return the QMessageBox question icon enum across Qt5/Qt6."""
    icon = getattr(QMessageBox, "Question", None)
    if icon is None:
        icon = getattr(getattr(QMessageBox, "Icon", None), "Question", None)
    return icon


def _qmessagebox_button_role(name):
    """Return QMessageBox button role enum by name across Qt5/Qt6."""
    role = getattr(QMessageBox, name, None)
    if role is None:
        role = getattr(getattr(QMessageBox, "ButtonRole", None), name, None)
    return role


def _qmessagebox_standard_button(name):
    """Return QMessageBox standard button enum by name across Qt5/Qt6."""
    button = getattr(QMessageBox, name, None)
    if button is None:
        button = getattr(getattr(QMessageBox, "StandardButton", None), name, None)
    return button


def _dialog_exec(dialog):
    """Execute a Qt dialog across Qt5/Qt6 (exec_ vs exec)."""
    execute = getattr(dialog, "exec", None)
    if callable(execute):
        return execute()

    execute_legacy = getattr(dialog, "exec_", None)
    if callable(execute_legacy):
        return execute_legacy()

    raise AttributeError("Dialog object has neither exec nor exec_ method")


class _CanvasDoubleClickFilter(QObject):
    """Event filter that forwards canvas double-clicks as map coordinates."""

    def __init__(self, canvas, callback):
        super().__init__()
        self._canvas = canvas
        self._callback = callback

    def eventFilter(self, watched, event):
        double_click_type = _double_click_event_type()
        if double_click_type is None or event.type() != double_click_type:
            return False

        left_button = _left_mouse_button_value()
        if left_button is None:
            return False

        button = getattr(event, "button", lambda: None)()
        if button != left_button:
            return False

        try:
            transform = self._canvas.getCoordinateTransform()
            point = transform.toMapCoordinates(event.pos().x(), event.pos().y())
            self._callback(point)
        except Exception:
            # Keep default canvas behavior even if coordinate conversion fails.
            return False
        return False

class Delft3DFileManager:
    def __init__(self, iface):
        self.iface = iface
        self.import_action = None
        self.export_action = None
        self.export_pointcloud_action = None
        self.bed_level_action = None
        self.create_trachytopes_action = None
        self.create_bridge_points_action = None
        self.create_fixed_weir_points_action = None
        self.create_1d_network_action = None
        self.update_trachytopes_action = None
        self.export_trachytopes_action = None
        self.install_deps_action = None
        self.profile_chart_action = None
        self.his_timeseries_action = None
        self._bed_level_dialog = None
        self._profile_dialog = None
        self._his_dialog = None
        self._profile_layer = None
        self._profile_selection_connected = False
        self._canvas_double_click_connected = False
        self._canvas_double_click_filter = None
        self._active_progress_dialog = None
        self._partition_mesh_sync_sessions = {}
        self._his_sources = {}
        self._his_series_cache = {}
        self._required_packages = ["netCDF4", "pyproj", "scipy", "defusedxml"]
        self._warned_missing_defusedxml = False

    def initGui(self):
        """Create toolbar button and menu item"""
        if not _HAS_DEFUSEDXML and not self._warned_missing_defusedxml:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Dependency 'defusedxml' is required for DIMR XML import. "
                "To install it, use 'Delft3D File Manager -> Install Python Dependencies', "
                "then restart QGIS.",
            )
            self._warned_missing_defusedxml = True

        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.import_action = QAction(QIcon(icon_path), "Import", self.iface.mainWindow())
        self.import_action.setStatusTip(
            "Import Delft3D file (.fxw/.pli/.ldb/.pol/.pliz/.xyn/.xyz/.nc/.mat/.csl/.csd/.ini/.mdu/.ext/.bc/dimr_config.xml)"
        )
        self.import_action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.import_action)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.import_action)

        self.export_action = QAction(QIcon(icon_path), "Export", self.iface.mainWindow())
        self.export_action.setStatusTip("Export the active line or fixed-weir point layer to a Delft3D format")
        self.export_action.triggered.connect(self.export_active_layer)
        self.iface.addToolBarIcon(self.export_action)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.export_action)

        self.bed_level_action = QAction(
            QIcon(icon_path), "Write Bed Level to Mesh", self.iface.mainWindow()
        )
        self.bed_level_action.setStatusTip(
            "Interpolate elevation data from a source layer into a UGRID mesh file"
        )
        self.bed_level_action.triggered.connect(self.open_bed_level_dialog)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.bed_level_action)

        self.create_trachytopes_action = QAction(
            QIcon(icon_path), "Create Trachytopes from Mesh", self.iface.mainWindow()
        )
        self.create_trachytopes_action.setStatusTip(
            "Extract mesh2d_edge_x/y to point layer with trachytope attributes"
        )
        self.create_trachytopes_action.triggered.connect(self.create_trachytopes_from_mesh)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.create_trachytopes_action)

        self.create_bridge_points_action = QAction(
            QIcon(icon_path), "Create Bridge Points from Polyline", self.iface.mainWindow()
        )
        self.create_bridge_points_action.setStatusTip(
            "Create a bridge point layer from active polyline vertices with default width and drag_cd"
        )
        self.create_bridge_points_action.triggered.connect(self.create_bridge_points_from_polyline)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.create_bridge_points_action)

        self.create_fixed_weir_points_action = QAction(
            QIcon(icon_path), "Create Fixed-Weir Points from Polyline", self.iface.mainWindow()
        )
        self.create_fixed_weir_points_action.setStatusTip(
            "Create a fixed-weir point layer from active polyline vertices with default weir attributes"
        )
        self.create_fixed_weir_points_action.triggered.connect(self.create_fixed_weir_points_from_polyline)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.create_fixed_weir_points_action)

        self.create_1d_network_action = QAction(
            QIcon(icon_path), "Create 1D Network", self.iface.mainWindow()
        )
        self.create_1d_network_action.setStatusTip(
            "Create a 1D network NetCDF from snapped branch polylines and optional special points"
        )
        self.create_1d_network_action.triggered.connect(self.create_1d_network)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.create_1d_network_action)

        self.update_trachytopes_action = QAction(
            QIcon(icon_path), "Set Trachytopes in Polygons", self.iface.mainWindow()
        )
        self.update_trachytopes_action.setStatusTip(
            "Set trachytope_number and fraction for trachytopes points inside polygons"
        )
        self.update_trachytopes_action.triggered.connect(self.set_trachytopes_in_polygons)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.update_trachytopes_action)

        self.export_trachytopes_action = QAction(
            QIcon(icon_path), "Export Trachytopes (.arl)", self.iface.mainWindow()
        )
        self.export_trachytopes_action.setStatusTip(
            "Export trachytopes point layer to ASCII .arl (space-separated)"
        )
        self.export_trachytopes_action.triggered.connect(self.export_trachytopes_arl)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.export_trachytopes_action)

        self.export_pointcloud_action = QAction(
            QIcon(icon_path), "Export Point Cloud (.xyn)", self.iface.mainWindow()
        )
        self.export_pointcloud_action.setStatusTip(
            "Export point layer to ASCII .xyn (x y name)"
        )
        self.export_pointcloud_action.triggered.connect(self.export_point_cloud_xyn)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.export_pointcloud_action)

        self.install_deps_action = QAction(
            QIcon(icon_path), "Install Python Dependencies", self.iface.mainWindow()
        )
        self.install_deps_action.setStatusTip(
            "Install required Python packages (netCDF4, pyproj, scipy)"
        )
        self.install_deps_action.triggered.connect(self.install_dependencies)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.install_deps_action)

        self.profile_chart_action = QAction(
            QIcon(icon_path), "Profile / Timeseries", self.iface.mainWindow()
        )
        self.profile_chart_action.setStatusTip(
            "Open the profile/timeseries chart window for cross-sections and boundary conditions"
        )
        self.profile_chart_action.triggered.connect(self.open_cross_section_profile_window)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.profile_chart_action)

        self.his_timeseries_action = QAction(
            QIcon(icon_path), "HIS Timeseries", self.iface.mainWindow()
        )
        self.his_timeseries_action.setStatusTip(
            "Open the Delft3D FM HIS timeseries explorer for selected stations/cross-sections"
        )
        self.his_timeseries_action.triggered.connect(self.open_his_timeseries_window)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.his_timeseries_action)

        self._connect_canvas_double_click()

    def unload(self):
        """Remove the plugin menu item and icon"""
        if self.import_action:
            self.iface.removeToolBarIcon(self.import_action)
            self.iface.removePluginMenu("&Delft3D File Manager", self.import_action)
        if self.export_action:
            self.iface.removeToolBarIcon(self.export_action)
            self.iface.removePluginMenu("&Delft3D File Manager", self.export_action)
        if self.bed_level_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.bed_level_action)
        if self.create_trachytopes_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.create_trachytopes_action)
        if self.create_bridge_points_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.create_bridge_points_action)
        if self.create_fixed_weir_points_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.create_fixed_weir_points_action)
        if self.create_1d_network_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.create_1d_network_action)
        if self.update_trachytopes_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.update_trachytopes_action)
        if self.export_trachytopes_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.export_trachytopes_action)
        if self.export_pointcloud_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.export_pointcloud_action)
        if self.install_deps_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.install_deps_action)
        if self.profile_chart_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.profile_chart_action)
        if self.his_timeseries_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.his_timeseries_action)

        self._disconnect_profile_layer_selection()
        self._disconnect_canvas_double_click()

    def run(self):
        """Main entry point: open file dialog and dispatch by extension"""
        filepath, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select Delft3D file",
            "",
            "Delft3D Files (*.fxw *.pli *.ldb *.pol *.pliz *.xyn *.xyz *.nc *.mat *.csl *.csd *.ini *.mdu *.ext *.bc *.xml);;All Files (*)"
        )
        if filepath:
            self.load_file_by_extension(filepath)

    def load_file_by_extension(self, filepath, spatial_grid_path=None):
        """Route file to appropriate parser based on extension.

        spatial_grid_path is an optional UGRID path propagated by parent imports
        (for example DIMR -> MDU) to avoid repeatedly prompting for a grid file.
        """
        _, ext = os.path.splitext(filepath)
        ext_lower = ext.lower()
        
        if ext_lower == ".fxw":
            self.load_fixed_weir_file(filepath)
        elif ext_lower == ".pliz":
            column_count = self._pliz_column_count(filepath)
            if column_count == 2:
                self.load_polyline_file(filepath)
            elif column_count == 4:
                self.load_bridge_file(filepath)
            elif column_count == 9:
                self.load_fixed_weir_file(filepath)
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    "Unsupported .pliz header column count. Expected 2 (polyline), 4 (bridge), or 9 (fixed-weir).",
                )
        elif ext_lower in [".pli", ".ldb", ".pol"]:
            self.load_polyline_file(filepath)
        elif ext_lower == ".xyn":
            self.load_xyn_file(filepath)
        elif ext_lower == ".xyz":
            self.load_xyz_file(filepath)
        elif ext_lower == ".nc":
            self.load_netcdf_file(filepath)
        elif ext_lower == ".mat":
            self.load_shorelines_mat_file(filepath)
        elif ext_lower == ".xml" and os.path.basename(filepath).lower() == "dimr_config.xml":
            self.load_dimr_config_file(filepath, spatial_grid_path=spatial_grid_path)
        elif ext_lower == ".mdu":
            self.load_fm_mdu_file(filepath, import_referenced=True, spatial_grid_path=spatial_grid_path)
        elif ext_lower == ".ext":
            self.load_ext_file(filepath, grid_path=spatial_grid_path)
        elif ext_lower == ".bc":
            self.load_bc_file(filepath)
        elif ext_lower in [".csl", ".csd"]:
            self.load_cross_sections_from_selection(filepath)
        elif ext_lower == ".ini":
            ini_kind = self._detect_ini_file_type(filepath)
            if ini_kind in ("crossloc", "crossdef"):
                self.load_cross_sections_from_selection(filepath)
            elif ini_kind == "extforce":
                self.load_ext_file(filepath, grid_path=spatial_grid_path)
            elif ini_kind == "boundconds":
                self.load_bc_file(filepath)
            elif ini_kind == "structure":
                self.load_structures_spatial_file(filepath, grid_path=spatial_grid_path)
            elif ini_kind == "inifield":
                self.load_ini_field_spatial_file(filepath, grid_path=spatial_grid_path)
            elif ini_kind == "1dfield":
                self.load_1d_field_spatial_file(filepath, grid_path=spatial_grid_path)
            elif ini_kind == "roughness":
                self.load_roughness_spatial_file(filepath, grid_path=spatial_grid_path)
            else:
                self.load_ini_table_file(filepath)
        else:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Unsupported file extension: {ext}\n\n"
                "Supported extensions:\n"
                "  .fxw - Fixed weir file\n"
                "  .pli - Polyline file\n"
                "  .ldb - Light database file\n"
                "  .pol - Polygon file\n"
                "  .pliz - Polyline or fixed weir file (auto-detected by column count)\n"
                "  .xyn - Point file\n"
                "  .xyz - Point file with elevation\n"
                "  .nc - UGRID mesh file\n"
                "  .mat - ShorelineS results file\n"
                "  .csl/.csd/.ini - Cross-section location/definition or generic INI file\n"
                "  .mdu - FM model definition file\n"
                "  .ext - External forcing definition file\n"
                "  .bc - Boundary condition forcing file\n"
                "  dimr_config.xml - DIMR simulation definition"
            )

    def load_cross_sections_from_selection(self, selected_filepath):
        """Load cross-sections by prompting for missing files based on selected .csl or .csd."""
        selected_path = os.path.abspath(selected_filepath)
        selected_ext = os.path.splitext(selected_path)[1].lower()
        start_dir = os.path.dirname(selected_path)

        csl_path = ""
        csd_path = ""

        if selected_ext == ".csl":
            csl_path = selected_path
        elif selected_ext == ".csd":
            csd_path = selected_path
        elif selected_ext == ".ini":
            ini_kind = self._detect_cross_section_ini_kind(selected_path)
            if ini_kind == "crossloc":
                csl_path = selected_path
            elif ini_kind == "crossdef":
                csd_path = selected_path
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    "Selected .ini file is not a supported cross-section file.",
                )
                return

        if not csl_path:
            csl_path, _ = QFileDialog.getOpenFileName(
                self.iface.mainWindow(),
                "Select Cross-Section Locations (.csl)",
                start_dir,
                "Cross-section location files (*.csl *.ini);;All Files (*)",
            )
            if not csl_path:
                return

        if not csd_path:
            csd_path, _ = QFileDialog.getOpenFileName(
                self.iface.mainWindow(),
                "Select Cross-Section Definitions (.csd)",
                start_dir,
                "Cross-section definition files (*.csd *.ini);;All Files (*)",
            )
            if not csd_path:
                return

        grid_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select UGRID Grid (.nc)",
            start_dir,
            "NetCDF files (*.nc);;All Files (*)",
        )
        if not grid_path:
            return

        self.load_cross_sections_files(csl_path, csd_path, grid_path)

    def load_cross_sections_files(self, csl_path, csd_path, grid_path):
        """Import FM cross-sections from locations/definitions and mesh grid into one point layer."""
        csl_path = os.path.abspath(csl_path)
        csd_path = os.path.abspath(csd_path)
        grid_path = os.path.abspath(grid_path)

        for path in (csl_path, csd_path, grid_path):
            if not os.path.exists(path):
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Input file does not exist: {path}",
                )
                return

        try:
            cross_sections = self._read_crossloc_records(csl_path)
            if not cross_sections:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    "No [CrossSection] records were found in the selected .csl file",
                )
                return

            definitions = self._read_crossdef_records(csd_path)
            branch_lookup, epsg = self._read_mesh_branch_profiles_from_grid(grid_path)
            if not branch_lookup:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    "Could not derive any mesh1d branch profiles from the selected grid",
                )
                return
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not import cross-sections: {exc}",
            )
            return

        base_name = os.path.splitext(os.path.basename(csl_path))[0]
        layer = QgsVectorLayer(f"Point?crs=EPSG:{epsg}", f"{base_name}_cross_sections", "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("id", QVariant.String),
                QgsField("branchId", QVariant.String),
                QgsField("chainage", QVariant.Double),
                QgsField("shift", QVariant.Double),
                QgsField("definitionId", QVariant.String),
                QgsField("def_type", QVariant.String),
                QgsField("def_thalweg", QVariant.String),
                QgsField("def_singleValZ", QVariant.String),
                QgsField("def_yzCount", QVariant.String),
                QgsField("def_convey", QVariant.String),
                QgsField("def_secCount", QVariant.String),
                QgsField("def_fricIds", QVariant.String),
                QgsField("def_fricPos", QVariant.String),
                QgsField("def_diam", QVariant.String),
                QgsField("def_fricType", QVariant.String),
                QgsField("def_fricVal", QVariant.String),
                QgsField("def_yCoords", QVariant.String),
                QgsField("def_zCoords", QVariant.String),
                QgsField("def_raw", QVariant.String),
                QgsField("def_found", QVariant.Int),
                QgsField("import_note", QVariant.String),
            ]
        )
        layer.updateFields()

        features = []
        skipped = 0
        missing_definition_count = 0

        for record in cross_sections:
            note_parts = []
            branch_key = record["branchId"].strip().lower()
            branch_profile = branch_lookup.get(branch_key)
            if branch_profile is None:
                skipped += 1
                continue

            target_distance = record["chainage"] + record["shift"]
            point_xy = self._interpolate_point_on_branch(branch_profile, target_distance)
            if point_xy is None:
                skipped += 1
                continue

            definition = definitions.get(record["definitionId"].strip().lower())
            definition_found = 1 if definition is not None else 0
            if not definition_found:
                missing_definition_count += 1
                note_parts.append("definition_not_found")

            definition = definition or {}
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_xy[0], point_xy[1])))
            feature.setAttributes(
                [
                    record["id"],
                    record["branchId"],
                    float(record["chainage"]),
                    float(record["shift"]),
                    record["definitionId"],
                    definition.get("type", ""),
                    definition.get("thalweg", ""),
                    definition.get("singlevaluedz", ""),
                    definition.get("yzcount", ""),
                    definition.get("conveyance", ""),
                    definition.get("sectioncount", ""),
                    definition.get("frictionids", ""),
                    definition.get("frictionpositions", ""),
                    definition.get("diameter", ""),
                    definition.get("frictiontype", ""),
                    definition.get("frictionvalue", ""),
                    definition.get("ycoordinates", ""),
                    definition.get("zcoordinates", ""),
                    self._definition_to_text(definition),
                    definition_found,
                    ";".join(note_parts),
                ]
            )
            features.append(feature)

        if not features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid cross-section points were derived from the selected files",
            )
            return

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        summary = (
            f"Loaded {len(features)} cross-section point(s)"
            f" from {os.path.basename(csl_path)}"
        )
        if skipped > 0 or missing_definition_count > 0:
            summary += f" (skipped: {skipped}, missing definitions: {missing_definition_count})"

        self.iface.messageBar().pushSuccess("Delft3D File Manager", summary)

    def _field_name_map(self, layer):
        """Return case-insensitive field-name lookup for a vector layer."""
        lookup = {}
        for field in layer.fields():
            name = field.name()
            lookup[name.lower()] = name
        return lookup

    def _is_cross_section_layer(self, layer):
        """Return True when layer appears to be an imported FM cross-section point layer."""
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return False
        if layer.geometryType() != QgsWkbTypes.PointGeometry:
            return False

        field_lookup = self._field_name_map(layer)
        has_type = "def_type" in field_lookup
        has_id = "id" in field_lookup or "definitionid" in field_lookup
        has_profile = "def_ycoords" in field_lookup or "def_diam" in field_lookup
        return has_type and has_id and has_profile

    def _is_boundary_condition_layer(self, layer):
        """Return True when layer appears to be an imported boundary-condition layer."""
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return False

        field_lookup = self._field_name_map(layer)
        required = {"bc_name", "bc_function", "series_xy"}
        return required.issubset(set(field_lookup.keys()))

    def _parse_float_list(self, text):
        """Parse whitespace-separated numeric text into a list of floats."""
        if text is None:
            return None

        raw_text = str(text).strip()
        if not raw_text:
            return []

        values = []
        for token in raw_text.split():
            try:
                value = float(token)
            except ValueError:
                return None
            if not math.isfinite(value):
                return None
            values.append(value)
        return values

    def _build_yz_profile(self, feature):
        """Build profile points from yCoordinates/zCoordinates attributes."""
        y_coords = self._parse_float_list(feature["def_yCoords"])
        z_coords = self._parse_float_list(feature["def_zCoords"])

        if y_coords is None or z_coords is None:
            return []
        if len(y_coords) != len(z_coords):
            return []
        if len(y_coords) < 2:
            return []

        return [(x_val, z_val) for x_val, z_val in zip(y_coords, z_coords)]

    def _build_circle_profile(self, feature, n=64):
        """Build a circular profile from diameter as a closed full circle."""
        raw_diam = feature["def_diam"]
        if raw_diam is None:
            return []

        try:
            diameter = float(str(raw_diam).strip())
        except (TypeError, ValueError):
            return []

        if not math.isfinite(diameter) or diameter <= 0.0:
            return []

        radius = diameter / 2.0
        points = []
        for idx in range(n + 1):
            angle = (2.0 * math.pi * idx) / n
            x_val = radius * math.cos(angle)
            z_val = radius * math.sin(angle)
            points.append((x_val, z_val))
        return points

    def _profile_from_feature(self, feature):
        """Build displayable profile points and metadata for one feature."""
        raw_type = feature["def_type"] if feature["def_type"] is not None else ""
        profile_type = str(raw_type).strip().lower()

        if profile_type == "yz":
            points = self._build_yz_profile(feature)
            if points:
                return points, {"def_type": "yz"}, ""
            return [], {"def_type": "yz"}, "Invalid yz profile: check def_yCoords/def_zCoords values."

        if profile_type == "circle":
            points = self._build_circle_profile(feature)
            if points:
                return points, {"def_type": "circle"}, ""
            return [], {"def_type": "circle"}, "Invalid circle profile: check def_diam value."

        return [], {"def_type": profile_type or "unknown"}, f"Unsupported def_type: {profile_type or 'empty'}"

    def _parse_series_xy_text(self, text):
        """Parse semicolon-separated x y pairs into float tuples."""
        if text is None:
            return []

        raw_text = str(text).strip()
        if not raw_text:
            return []

        points = []
        for pair_text in raw_text.split(";"):
            tokens = pair_text.strip().split()
            if len(tokens) < 2:
                continue
            try:
                x_val = float(tokens[0])
                y_val = float(tokens[1])
            except ValueError:
                continue
            if not math.isfinite(x_val) or not math.isfinite(y_val):
                continue
            points.append((x_val, y_val))
        return points

    def _format_axis_label(self, quantity, unit, fallback):
        """Build an axis label from quantity/unit text with a fallback."""
        quantity_text = "" if quantity is None else str(quantity).strip()
        unit_text = "" if unit is None else str(unit).strip()

        if quantity_text and unit_text:
            return f"{quantity_text} [{unit_text}]"
        if quantity_text:
            return quantity_text
        if unit_text:
            return unit_text
        return fallback

    def _timeseries_from_feature(self, feature):
        """Build displayable points and metadata for one boundary-condition feature."""
        points = self._parse_series_xy_text(feature["series_xy"])
        metadata = {
            "id": "" if feature["bc_name"] is None else str(feature["bc_name"]),
            "definitionId": "" if feature["bc_function"] is None else str(feature["bc_function"]),
            "def_type": "" if feature["quantity_1"] is None else str(feature["quantity_1"]),
            "x_axis_label": self._format_axis_label(feature["quantity_1"], feature["unit_1"], "x"),
            "y_axis_label": self._format_axis_label(feature["quantity_2"], feature["unit_2"], "value"),
        }
        if points:
            return points, metadata, ""
        return [], metadata, "No numeric series found for this boundary condition."

    def _profile_metadata(self, feature):
        """Extract lightweight metadata for chart display."""
        metadata = {
            "id": "",
            "definitionId": "",
            "def_type": "",
        }

        for key in metadata.keys():
            value = feature[key]
            metadata[key] = "" if value is None else str(value)
        return metadata

    def _profile_title(self, feature):
        """Build chart title from feature attributes."""
        feature_id = feature["id"] if feature["id"] is not None else feature.id()
        definition_id = feature["definitionId"] if feature["definitionId"] is not None else ""
        if definition_id:
            return f"Cross-section {feature_id} ({definition_id})"
        return f"Cross-section {feature_id}"

    def _timeseries_title(self, feature):
        """Build chart title for boundary-condition features."""
        name = feature["bc_name"] if feature["bc_name"] is not None else feature.id()
        quantity = feature["quantity_1"] if feature["quantity_1"] is not None else ""
        if quantity:
            return f"Boundary condition {name} ({quantity})"
        return f"Boundary condition {name}"

    def _create_cross_section_profile_dialog(self):
        """Construct the profile dialog lazily to keep plugin import lightweight."""
        from .cross_section_profile_dialog import CrossSectionProfileDialog

        return CrossSectionProfileDialog(self.iface.mainWindow())

    def _ensure_profile_dialog(self):
        """Ensure profile dialog exists and return it."""
        if self._profile_dialog is None:
            self._profile_dialog = self._create_cross_section_profile_dialog()
        return self._profile_dialog

    def _show_profile_in_dialog(self, feature):
        """Render one feature profile in the profile dialog."""
        points, profile_meta, message = self._profile_from_feature(feature)
        metadata = self._profile_metadata(feature)
        metadata.update(profile_meta)

        dialog = self._ensure_profile_dialog()
        dialog.set_profile(
            points=points,
            title=self._profile_title(feature),
            metadata=metadata,
            message=message,
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_timeseries_in_dialog(self, feature):
        """Render one boundary-condition timeseries in the profile dialog."""
        points, metadata, message = self._timeseries_from_feature(feature)

        dialog = self._ensure_profile_dialog()
        dialog.set_profile(
            points=points,
            title=self._timeseries_title(feature),
            metadata=metadata,
            message=message,
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_profile_message(self, message):
        """Show guidance or status text in the profile dialog."""
        dialog = self._ensure_profile_dialog()
        dialog.set_profile(points=[], title="Profile / Timeseries", metadata={}, message=message)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _disconnect_profile_layer_selection(self):
        """Disconnect existing profile layer selection signal safely."""
        if self._profile_layer is None or not self._profile_selection_connected:
            self._profile_layer = None
            self._profile_selection_connected = False
            return

        try:
            self._profile_layer.selectionChanged.disconnect(self._on_profile_layer_selection_changed)
        except RuntimeError:
            pass

        self._profile_layer = None
        self._profile_selection_connected = False

    def _set_profile_layer(self, layer):
        """Track active profile layer and hook selection updates."""
        if layer is self._profile_layer and self._profile_selection_connected:
            return

        self._disconnect_profile_layer_selection()

        if layer is None:
            return

        try:
            layer.selectionChanged.connect(self._on_profile_layer_selection_changed)
            self._profile_layer = layer
            self._profile_selection_connected = True
        except Exception:
            self._profile_layer = None
            self._profile_selection_connected = False

    def _selected_cross_section_feature(self, layer):
        """Return first selected feature from the layer or None."""
        if layer is None:
            return None

        try:
            selected = list(layer.getSelectedFeatures())
        except Exception:
            selected = []

        return selected[0] if selected else None

    def _on_profile_layer_selection_changed(self, *args):
        """Refresh chart from the first selected feature on the tracked layer."""
        layer = self._profile_layer
        if layer is None:
            return

        selected_feature = self._selected_cross_section_feature(layer)
        if selected_feature is None:
            self._show_profile_message("Select a cross-section or boundary-condition feature.")
            return

        if self._is_cross_section_layer(layer):
            self._show_profile_in_dialog(selected_feature)
        elif self._is_boundary_condition_layer(layer):
            self._show_timeseries_in_dialog(selected_feature)

    def open_cross_section_profile_window(self):
        """Open/focus profile chart and render selected feature when available."""
        layer = self.iface.activeLayer()
        is_cross_section = self._is_cross_section_layer(layer)
        is_boundary = self._is_boundary_condition_layer(layer)

        if not is_cross_section and not is_boundary:
            self._show_profile_message(
                "Activate a cross-section or boundary-condition layer and select a feature to preview data."
            )
            self._disconnect_profile_layer_selection()
            return

        self._set_profile_layer(layer)
        selected_feature = self._selected_cross_section_feature(layer)
        if selected_feature is None:
            self._show_profile_message("Select a cross-section or boundary-condition feature.")
            return

        if is_cross_section:
            self._show_profile_in_dialog(selected_feature)
        else:
            self._show_timeseries_in_dialog(selected_feature)

    def _create_his_timeseries_dialog(self):
        """Construct the HIS timeseries dialog lazily."""
        from .his_timeseries_dialog import HisTimeseriesDialog

        dialog = HisTimeseriesDialog(self.iface.mainWindow())
        dialog.set_handlers(
            on_controls_changed=self._on_his_dialog_controls_changed,
            on_plot_requested=self._on_his_dialog_plot_requested,
            on_refresh_requested=self._on_his_dialog_refresh_requested,
        )
        return dialog

    def _ensure_his_timeseries_dialog(self):
        """Ensure HIS dialog exists and return it."""
        if self._his_dialog is None:
            self._his_dialog = self._create_his_timeseries_dialog()
        return self._his_dialog

    def _his_source_options(self):
        """Return source combo options for all loaded HIS sources."""
        options = []
        for source_path, source_info in sorted(self._his_sources.items()):
            label = f"{source_info['base_name']} ({source_info['path']})"
            options.append((source_path, label))
        return options

    def _his_variable_options(self, source_info, scope):
        """Return variable combo options for selected source and scope."""
        catalog_map = {
            "station": source_info.get("station_variables", []),
            "cross_section": source_info.get("cross_section_variables", []),
            "global": source_info.get("global_variables", []),
        }
        options = []
        for entry in catalog_map.get(scope, []):
            options.append((entry["name"], entry["label"]))
        return options

    def _his_active_selection_features(self, source_path, scope):
        """Return selected features from active layer for the requested HIS scope."""
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return [], "Activate a HIS observation layer and select feature(s)."

        field_lookup = self._field_name_map(layer)
        required = ("his_source", "obs_type", "obs_index", "obs_name")
        if not all(name in field_lookup for name in required):
            return [], "Active layer is not a HIS observation layer."

        expected_obs_type = "station" if scope == "station" else "cross_section"

        expected_geometry = (
            QgsWkbTypes.PointGeometry if expected_obs_type == "station" else QgsWkbTypes.LineGeometry
        )
        if layer.geometryType() != expected_geometry:
            geometry_name = "point" if expected_obs_type == "station" else "line"
            return [], f"Active layer must be a HIS {geometry_name} layer for scope '{expected_obs_type}'."

        layer_source_value = ""
        try:
            first_feature = next(layer.getFeatures(), None)
            if first_feature is not None:
                layer_source_value = str(first_feature[field_lookup["his_source"]] or "")
        except Exception:
            layer_source_value = ""

        if layer_source_value and os.path.normcase(layer_source_value) != os.path.normcase(source_path):
            return [], "Active selection belongs to a different HIS source than selected in the dialog."

        selected_features = []
        try:
            selected_features = list(layer.getSelectedFeatures())
        except Exception:
            selected_features = []

        if not selected_features:
            return [], f"Select one or more {expected_obs_type.replace('_', ' ')} feature(s) in the active layer."

        filtered = []
        for feature in selected_features:
            obs_type_value = str(feature[field_lookup["obs_type"]] or "").strip().lower()
            if obs_type_value != expected_obs_type:
                continue
            filtered.append(feature)

        if not filtered:
            return [], f"Selected features do not match scope '{expected_obs_type}'."

        return filtered, ""

    def _refresh_his_dialog_state(self, keep_current=True):
        """Refresh dialog combo options and selection status."""
        dialog = self._ensure_his_timeseries_dialog()

        source_options = self._his_source_options()
        selected_source = dialog.selected_source() if keep_current else None
        if not source_options:
            dialog.set_source_options([])
            dialog.set_scope_options([])
            dialog.set_variable_options([])
            dialog.set_selection_text("Selection: no HIS source loaded")
            dialog.set_message("Import a Delft3D FM HIS .nc file first.")
            return

        if selected_source is None or selected_source not in dict(source_options):
            selected_source = source_options[0][0]

        dialog.set_source_options(source_options, selected_value=selected_source)

        scope_options = [
            ("station", "Selected stations"),
            ("cross_section", "Selected cross-sections"),
            ("global", "Global variables"),
        ]
        selected_scope = dialog.selected_scope() if keep_current else None
        if selected_scope not in {"station", "cross_section", "global"}:
            selected_scope = "station"
        dialog.set_scope_options(scope_options, selected_value=selected_scope)

        source_info = self._his_sources.get(selected_source)
        variable_options = []
        if source_info is not None:
            variable_options = self._his_variable_options(source_info, selected_scope)

        selected_variable = dialog.selected_variable() if keep_current else None
        if selected_variable not in dict(variable_options):
            selected_variable = variable_options[0][0] if variable_options else None
        dialog.set_variable_options(variable_options, selected_value=selected_variable)

        if selected_scope == "global":
            dialog.set_selection_text("Selection: global scope does not require map selection")
            dialog.set_message("")
            return

        features, message = self._his_active_selection_features(selected_source, selected_scope)
        if features:
            label = selected_scope.replace("_", " ")
            dialog.set_selection_text(f"Selection: {len(features)} selected {label}(s) from active layer")
            dialog.set_message("")
        else:
            dialog.set_selection_text("Selection: none")
            dialog.set_message(message)

    def _on_his_dialog_controls_changed(self):
        """Handle combo changes in HIS dialog."""
        self._refresh_his_dialog_state(keep_current=True)

    def _on_his_dialog_refresh_requested(self):
        """Refresh selection-dependent status in HIS dialog."""
        self._refresh_his_dialog_state(keep_current=True)

    def _his_variable_info(self, source_info, scope, variable_name):
        """Return variable metadata entry by name for a scope."""
        catalog = {
            "station": source_info.get("station_variables", []),
            "cross_section": source_info.get("cross_section_variables", []),
            "global": source_info.get("global_variables", []),
        }.get(scope, [])
        for entry in catalog:
            if entry.get("name") == variable_name:
                return entry
        return None

    def _his_time_axis_label(self, source_info):
        """Return time-axis label for a HIS source."""
        units = str(source_info.get("time_units") or "").strip()
        return self._format_axis_label(source_info.get("time_name", "time"), units, "time")

    def _his_read_series(self, source_path, variable_name, scope, obs_index=None):
        """Read one HIS series lazily from disk, with small cache reuse."""
        cache_key = (source_path, variable_name, scope, obs_index)
        cached = self._his_series_cache.get(cache_key)
        if cached is not None:
            return cached

        source_info = self._his_sources.get(source_path)
        if source_info is None:
            raise RuntimeError("Selected HIS source is no longer available.")

        import netCDF4 as nc
        import numpy as np

        with nc.Dataset(source_path, "r") as ds:
            time_var_name = source_info["time_var"]
            if time_var_name not in ds.variables:
                raise RuntimeError("HIS time variable could not be found in source file.")
            time_values = ds.variables[time_var_name][:]
            if isinstance(time_values, np.ma.MaskedArray):
                time_values = time_values.filled(np.nan)
            time_values = np.asarray(time_values, dtype=float)

            if variable_name not in ds.variables:
                raise RuntimeError(f"Variable '{variable_name}' could not be found in source file.")
            variable = ds.variables[variable_name]
            values = variable[:]
            if isinstance(values, np.ma.MaskedArray):
                values = values.filled(np.nan)
            values = np.asarray(values, dtype=float)

            if scope == "global":
                series_values = values
            else:
                obs_dim = source_info["station_dim"] if scope == "station" else source_info["cross_section_dim"]
                if obs_dim not in variable.dimensions:
                    raise RuntimeError(
                        f"Variable '{variable_name}' is not available for scope '{scope}'."
                    )
                if obs_index is None:
                    raise RuntimeError("Observation index is required for station/cross-section series.")

                obs_axis = variable.dimensions.index(obs_dim)
                series_values = np.take(values, indices=int(obs_index), axis=obs_axis)

            series_values = np.asarray(series_values, dtype=float).reshape(-1)
            if time_values.shape[0] != series_values.shape[0]:
                raise RuntimeError(
                    f"Variable '{variable_name}' length does not match time axis."
                )

            valid_mask = np.isfinite(time_values) & np.isfinite(series_values)
            x_values = time_values[valid_mask].tolist()
            y_values = series_values[valid_mask].tolist()

        variable_info = self._his_variable_info(source_info, scope, variable_name) or {}
        payload = {
            "x": x_values,
            "y": y_values,
            "x_label": self._his_time_axis_label(source_info),
            "y_label": self._format_axis_label(
                variable_info.get("long_name", variable_name),
                variable_info.get("units", ""),
                variable_name,
            ),
            "variable_label": variable_info.get("label", variable_name),
        }

        self._his_series_cache[cache_key] = payload
        if len(self._his_series_cache) > 96:
            oldest_key = next(iter(self._his_series_cache.keys()))
            self._his_series_cache.pop(oldest_key, None)
        return payload

    def _on_his_dialog_plot_requested(self, mode):
        """Plot button handler for HIS dialog (new plot vs append)."""
        dialog = self._ensure_his_timeseries_dialog()
        source_path = dialog.selected_source()
        scope = dialog.selected_scope()
        variable_name = dialog.selected_variable()

        if not source_path or source_path not in self._his_sources:
            dialog.set_message("Select a valid HIS source.")
            return
        if not variable_name:
            dialog.set_message("Select a variable to plot.")
            return

        source_info = self._his_sources[source_path]
        series_entries = []
        x_axis_label = self._his_time_axis_label(source_info)
        y_axis_label = "value"

        if scope == "global":
            try:
                series_payload = self._his_read_series(source_path, variable_name, scope)
            except Exception as exc:
                dialog.set_message(str(exc))
                return

            y_axis_label = series_payload["y_label"]
            series_entries.append(
                {
                    "x": series_payload["x"],
                    "y": series_payload["y"],
                    "label": f"global | {series_payload['variable_label']}",
                }
            )
        else:
            selected_features, message = self._his_active_selection_features(source_path, scope)
            if not selected_features:
                dialog.set_message(message)
                return

            if len(selected_features) > 20:
                dialog.set_message(
                    f"Plotting {len(selected_features)} selected features. Reduce selection if the plot becomes cluttered."
                )

            for feature in selected_features:
                try:
                    obs_index = int(feature["obs_index"])
                except (TypeError, ValueError):
                    continue

                obs_name = ""
                try:
                    obs_name = str(feature["obs_name"] or "").strip()
                except Exception:
                    obs_name = ""
                if not obs_name:
                    obs_name = f"{scope}_{obs_index + 1}"

                try:
                    series_payload = self._his_read_series(
                        source_path,
                        variable_name,
                        scope,
                        obs_index=obs_index,
                    )
                except Exception as exc:
                    dialog.set_message(str(exc))
                    return

                y_axis_label = series_payload["y_label"]
                series_entries.append(
                    {
                        "x": series_payload["x"],
                        "y": series_payload["y"],
                        "label": f"{obs_name} | {series_payload['variable_label']}",
                    }
                )

        if not series_entries:
            dialog.set_message("No valid series found for the current selection.")
            return

        append = str(mode).strip().lower() == "add"
        dialog.apply_series(
            series_entries,
            x_axis_label=x_axis_label,
            y_axis_label=y_axis_label,
            title=f"HIS Timeseries - {source_info['base_name']}",
            append=append,
        )

    def open_his_timeseries_window(self):
        """Open/focus the HIS timeseries explorer."""
        dialog = self._ensure_his_timeseries_dialog()
        self._refresh_his_dialog_state(keep_current=True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _find_nearest_feature(self, layer, map_point):
        """Return nearest feature around a map click, with a map-unit tolerance."""
        if layer is None or map_point is None:
            return None

        try:
            tolerance = float(self.iface.mapCanvas().mapUnitsPerPixel()) * 8.0
        except Exception:
            tolerance = 0.0

        click_geom = QgsGeometry.fromPointXY(QgsPointXY(float(map_point.x()), float(map_point.y())))
        best_feature = None
        best_distance = None

        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue

            try:
                distance = float(geometry.distance(click_geom))
            except (TypeError, AttributeError):
                continue

            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_feature = feature

        if best_feature is None:
            return None
        if tolerance > 0.0 and best_distance is not None and best_distance > tolerance:
            return None
        return best_feature

    def _handle_canvas_double_click(self, map_point):
        """Handle map canvas double-click by opening profile for nearest feature."""
        layer = self.iface.activeLayer()
        is_cross_section = self._is_cross_section_layer(layer)
        is_boundary = self._is_boundary_condition_layer(layer)
        if not is_cross_section and not is_boundary:
            return

        feature = self._find_nearest_feature(layer, map_point)
        if feature is None:
            return

        self._set_profile_layer(layer)
        if is_cross_section:
            self._show_profile_in_dialog(feature)
        else:
            self._show_timeseries_in_dialog(feature)

    def _select_grid_file_for_spatial_import(self, start_dir):
        """Prompt user to select a grid file needed for spatial imports."""
        grid_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select UGRID Grid (.nc) for Spatial Import",
            start_dir,
            "NetCDF files (*.nc);;All Files (*)",
        )
        return grid_path

    def _read_mesh_node_lookup_from_grid(self, grid_path):
        """Read node-id to coordinate lookup from grid file."""
        try:
            import netCDF4 as nc
            import numpy as np
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS."
            ) from exc

        with nc.Dataset(grid_path, "r") as ds:
            node_x = ds.variables["network_node_x"][:] if "network_node_x" in ds.variables else None
            node_y = ds.variables["network_node_y"][:] if "network_node_y" in ds.variables else None
            node_ids = self._read_string_array(ds, "network_node_id")
            if not self._has_nonempty_strings(node_ids):
                node_ids = self._read_string_array(ds, "network_node_long_name")

            epsg = self._read_epsg_from_nc(ds)
            if epsg is None:
                epsg = 28992

        if node_x is None or node_y is None or not node_ids:
            return {}, epsg

        if isinstance(node_x, np.ma.MaskedArray):
            node_x = node_x.filled(np.nan)
        if isinstance(node_y, np.ma.MaskedArray):
            node_y = node_y.filled(np.nan)

        node_x = np.asarray(node_x, dtype=float)
        node_y = np.asarray(node_y, dtype=float)

        lookup = {}
        n = min(len(node_ids), len(node_x), len(node_y))
        for idx in range(n):
            node_id = str(node_ids[idx]).strip()
            if not node_id:
                continue
            x_val = float(node_x[idx])
            y_val = float(node_y[idx])
            if not math.isfinite(x_val) or not math.isfinite(y_val):
                continue
            lookup[node_id.lower()] = (x_val, y_val)
        return lookup, epsg

    def _build_spatial_context(self, grid_path):
        """Build reusable spatial context for branch and node-based feature placement."""
        branch_lookup, epsg = self._read_mesh_branch_profiles_from_grid(grid_path)
        node_lookup, node_epsg = self._read_mesh_node_lookup_from_grid(grid_path)
        if node_epsg is not None:
            epsg = node_epsg
        return {
            "branch_lookup": branch_lookup,
            "node_lookup": node_lookup,
            "epsg": epsg,
        }

    def _resolve_spatial_context(self, grid_path, start_dir):
        """Resolve spatial context by using provided grid path or prompting user."""
        chosen_grid = grid_path
        if not chosen_grid or not os.path.exists(chosen_grid):
            chosen_grid = self._select_grid_file_for_spatial_import(start_dir)
            if not chosen_grid:
                return None, None

        try:
            context = self._build_spatial_context(chosen_grid)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not build spatial context from grid: {exc}",
            )
            return None, None

        return context, os.path.abspath(chosen_grid)

    def _parse_numeric_list(self, text):
        """Parse whitespace-separated numeric text into a list of finite floats."""
        raw = "" if text is None else str(text).strip()
        if not raw:
            return []

        values = []
        for token in raw.split():
            try:
                value = float(token)
            except ValueError:
                return []
            if not math.isfinite(value):
                return []
            values.append(value)
        return values

    def _series_text_from_points(self, points):
        """Serialize sequence of numeric pairs for chart display."""
        return ";".join(f"{x:.12g} {y:.12g}" for x, y in points)

    def _bc_name_lookup(self, records):
        """Build case-insensitive lookup of BC forcing records by name."""
        lookup = {}
        for record in records:
            key = str(record.get("bc_name", "")).strip().lower()
            if key:
                lookup[key] = record
        return lookup

    def _split_semicolon_paths(self, text):
        """Split semicolon-separated path values while preserving order."""
        if text is None:
            return []
        parts = []
        for token in str(text).split(";"):
            item = token.strip()
            if item:
                parts.append(item)
        return parts

    def _value_case_insensitive(self, mapping, *keys):
        """Get first matching value from dict using case-insensitive key lookup."""
        if not mapping:
            return ""

        normalized = {
            str(existing_key).strip().lower(): "" if value is None else str(value).strip()
            for existing_key, value in mapping.items()
        }
        for key in keys:
            value = normalized.get(str(key).strip().lower(), "")
            if value:
                return value
        return ""

    def _has_any_key_case_insensitive(self, mapping, *keys):
        """Return whether dict contains any of the provided keys (case-insensitive)."""
        if not mapping:
            return False
        available = {str(existing_key).strip().lower() for existing_key in mapping.keys()}
        for key in keys:
            if str(key).strip().lower() in available:
                return True
        return False

    def _normalize_branch_key(self, value):
        """Normalize branch-like identifiers for tolerant matching."""
        text = "" if value is None else str(value).strip()
        text = text.strip("\"'")
        return text.lower()

    def _parse_first_float(self, text):
        """Extract first finite float from free-form text (supports comma decimal)."""
        raw = "" if text is None else str(text).strip()
        if not raw:
            return None

        # Normalize decimal comma and strip surrounding quotes.
        candidate = raw.strip("\"'").replace(",", ".")
        match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", candidate)
        if not match:
            return None

        try:
            value = float(match.group(0))
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
        return value

    def _resolve_candidate_path(self, base_dir, value):
        """Resolve path value relative to a base directory if needed."""
        raw = "" if value is None else str(value).strip()
        if not raw:
            return ""
        if os.path.isabs(raw):
            return raw
        return os.path.abspath(os.path.join(base_dir, raw))

    def _read_dimr_component_input_files(self, dimr_config_path):
        """Return inputFile values found in DIMR component blocks."""
        if not _HAS_DEFUSEDXML or ET is None:
            raise RuntimeError(
                "required package 'defusedxml' is not available. "
                "Install it via 'Delft3D File Manager -> Install Python Dependencies', "
                "restart QGIS, and try again."
            )

        tree = ET.parse(dimr_config_path)
        root = tree.getroot()

        input_files = []
        for component in root.iter():
            if not component.tag.lower().endswith("component"):
                continue
            for child in component:
                if child.tag.lower().endswith("inputfile"):
                    value = "" if child.text is None else child.text.strip()
                    if value:
                        input_files.append(value)
        return input_files

    def load_dimr_config_file(self, filepath, spatial_grid_path=None):
        """Load a DIMR config and import referenced Delft3D FM inputs."""
        self._close_orphan_loading_progress_dialogs()
        dimr_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(dimr_path)

        try:
            input_files = self._read_dimr_component_input_files(dimr_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not read dimr_config.xml: {exc}",
            )
            return

        if not input_files:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No component inputFile entries were found in dimr_config.xml.",
            )
            return

        imported_count = 0
        missing_count = 0
        for input_file in input_files:
            candidate = self._resolve_candidate_path(base_dir, input_file)
            if not os.path.exists(candidate):
                missing_count += 1
                continue
            try:
                self.load_file_by_extension(candidate, spatial_grid_path=spatial_grid_path)
                imported_count += 1
            finally:
                self._close_orphan_loading_progress_dialogs()

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"DIMR import completed: imported {imported_count} input file(s), missing {missing_count}.",
        )

    def _read_mdu_primary_files(self, filepath):
        """Read key file references from an FM .mdu file."""
        sections = self._parse_repeated_ini_sections(filepath)
        primary = {
            "net_file": "",
            "crossloc_file": "",
            "crossdef_file": "",
            "structure_file": "",
            "ext_force_file": "",
            "ini_field_file": "",
            "frict_files": [],
            "thin_dam_file": "",
            "fixed_weir_file": "",
            "pillar_file": "",
        }

        for block in sections:
            section = block["section"].strip().lower()
            values = block["values"]

            if section == "geometry":
                primary["net_file"] = values.get("NetFile", "").strip()
                primary["crossloc_file"] = values.get("CrossLocFile", "").strip()
                primary["crossdef_file"] = values.get("CrossDefFile", "").strip()
                primary["structure_file"] = values.get("StructureFile", "").strip()
                primary["ini_field_file"] = values.get("IniFieldFile", "").strip()
                primary["thin_dam_file"] = values.get("ThinDamFile", "").strip()
                primary["fixed_weir_file"] = values.get("FixedWeirFile", "").strip()
                primary["pillar_file"] = values.get("PillarFile", "").strip()
                primary["frict_files"] = self._split_semicolon_paths(values.get("FrictFile", ""))
            elif section == "external forcing":
                ext_new = values.get("ExtForceFileNew", "").strip()
                ext_old = values.get("ExtForceFile", "").strip()
                primary["ext_force_file"] = ext_new or ext_old

        return primary

    def load_fm_mdu_file(self, filepath, import_referenced=True, spatial_grid_path=None):
        """Load FM .mdu and optionally import referenced files."""
        mdu_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(mdu_path)

        try:
            primary = self._read_mdu_primary_files(mdu_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not read FM MDU file: {exc}",
            )
            return

        summary_layer = QgsVectorLayer("None", f"{os.path.splitext(os.path.basename(mdu_path))[0]}_mdu_files", "memory")
        provider = summary_layer.dataProvider()
        provider.addAttributes([
            QgsField("group", QVariant.String),
            QgsField("key", QVariant.String),
            QgsField("path", QVariant.String),
            QgsField("exists", QVariant.Int),
        ])
        summary_layer.updateFields()

        summary_rows = []

        def add_row(group, key, value):
            resolved = self._resolve_candidate_path(base_dir, value)
            exists = 1 if resolved and os.path.exists(resolved) else 0
            feature = QgsFeature(summary_layer.fields())
            feature.setAttributes([group, key, resolved, exists])
            summary_rows.append(feature)
            return resolved, bool(exists)

        net_path, net_ok = add_row("geometry", "NetFile", primary["net_file"])
        csl_path, csl_ok = add_row("geometry", "CrossLocFile", primary["crossloc_file"])
        csd_path, csd_ok = add_row("geometry", "CrossDefFile", primary["crossdef_file"])
        struct_path, struct_ok = add_row("geometry", "StructureFile", primary["structure_file"])
        ext_path, ext_ok = add_row("external forcing", "ExtForceFile", primary["ext_force_file"])
        ini_field_path, ini_field_ok = add_row("geometry", "IniFieldFile", primary["ini_field_file"])
        thin_dam_path, thin_dam_ok = add_row("geometry", "ThinDamFile", primary["thin_dam_file"])
        fixed_weir_path, fixed_weir_ok = add_row("geometry", "FixedWeirFile", primary["fixed_weir_file"])
        pillar_path, pillar_ok = add_row("geometry", "PillarFile", primary["pillar_file"])

        for frict_file in primary["frict_files"]:
            add_row("geometry", "FrictFile", frict_file)

        if summary_rows:
            provider.addFeatures(summary_rows)
            summary_layer.updateExtents()
            QgsProject.instance().addMapLayer(summary_layer)

        if not import_referenced:
            self.iface.messageBar().pushSuccess(
                "Delft3D File Manager",
                f"Loaded FM MDU references from {os.path.basename(mdu_path)}",
            )
            return

        if net_ok:
            self.load_ugrid_mesh_file(net_path)
        if csl_ok and csd_ok and net_ok:
            self.load_cross_sections_files(csl_path, csd_path, net_path)
        effective_grid_path = net_path if net_ok else spatial_grid_path

        if ext_ok:
            self.load_ext_file(ext_path, grid_path=effective_grid_path)
        if struct_ok:
            self.load_file_by_extension(struct_path, spatial_grid_path=effective_grid_path)
        if ini_field_ok:
            self.load_file_by_extension(ini_field_path, spatial_grid_path=effective_grid_path)
        for frict_file in primary["frict_files"]:
            frict_path = self._resolve_candidate_path(base_dir, frict_file)
            if frict_path and os.path.exists(frict_path):
                self.load_file_by_extension(frict_path, spatial_grid_path=effective_grid_path)
        if thin_dam_ok:
            self.load_polyline_file(thin_dam_path)
        if fixed_weir_ok:
            self.load_fixed_weir_file(fixed_weir_path)
        if pillar_ok:
            self.load_file_by_extension(pillar_path, spatial_grid_path=effective_grid_path)

    def _parse_bc_forcing_file(self, filepath):
        """Parse Delft3D FM boundary-condition forcing blocks from a .bc file."""
        forcing_blocks = []
        current = None

        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except UnicodeDecodeError:
            with open(filepath, "r") as handle:
                lines = handle.readlines()

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            if line.startswith("[") and line.endswith("]"):
                if current is not None:
                    forcing_blocks.append(current)
                section_name = line[1:-1].strip().lower()
                current = {"section": section_name, "meta": {}, "series": []}
                continue

            if current is None or current.get("section") != "forcing":
                continue

            if "=" in line:
                key, value = line.split("=", 1)
                key_norm = key.strip().lower()
                current["meta"].setdefault(key_norm, []).append(value.strip())
                continue

            tokens = line.split()
            if len(tokens) < 2:
                continue
            try:
                x_val = float(tokens[0])
                y_val = float(tokens[1])
            except ValueError:
                continue
            if not math.isfinite(x_val) or not math.isfinite(y_val):
                continue
            current["series"].append((x_val, y_val))

        if current is not None:
            forcing_blocks.append(current)

        records = []
        for block in forcing_blocks:
            if block.get("section") != "forcing":
                continue

            meta = block["meta"]
            quantities = meta.get("quantity", [])
            units = meta.get("unit", [])

            record = {
                "bc_name": meta.get("name", [""])[0],
                "bc_function": meta.get("function", [""])[0],
                "quantity_1": quantities[0] if len(quantities) > 0 else "",
                "unit_1": units[0] if len(units) > 0 else "",
                "quantity_2": quantities[1] if len(quantities) > 1 else "",
                "unit_2": units[1] if len(units) > 1 else "",
                "series": block["series"],
            }
            records.append(record)

        return records

    def load_bc_file(self, filepath):
        """Import FM boundary-condition forcing file as a table-like memory layer."""
        bc_path = os.path.abspath(filepath)
        try:
            records = self._parse_bc_forcing_file(bc_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not import BC file: {exc}",
            )
            return

        if not records:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No [forcing] records found in boundary-condition file.",
            )
            return

        base_name = os.path.splitext(os.path.basename(bc_path))[0]
        layer = QgsVectorLayer("None", f"{base_name}_bc", "memory")
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("source_bc", QVariant.String),
            QgsField("bc_name", QVariant.String),
            QgsField("bc_function", QVariant.String),
            QgsField("quantity_1", QVariant.String),
            QgsField("unit_1", QVariant.String),
            QgsField("quantity_2", QVariant.String),
            QgsField("unit_2", QVariant.String),
            QgsField("sample_cnt", QVariant.Int),
            QgsField("series_xy", QVariant.String),
        ])
        layer.updateFields()

        features = []
        for record in records:
            feature = QgsFeature(layer.fields())
            series_text = ";".join(f"{x:.12g} {y:.12g}" for x, y in record["series"])
            feature.setAttributes([
                os.path.basename(bc_path),
                record["bc_name"],
                record["bc_function"],
                record["quantity_1"],
                record["unit_1"],
                record["quantity_2"],
                record["unit_2"],
                len(record["series"]),
                series_text,
            ])
            features.append(feature)

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {len(features)} boundary-condition record(s) from {os.path.basename(bc_path)}",
        )

    def _parse_ext_file(self, filepath):
        """Parse Delft3D FM .ext forcing links."""
        rows = []
        for block in self._parse_repeated_ini_sections(filepath):
            section = block["section"].strip().lower()
            values = block["values"]
            if section == "boundary":
                rows.append({
                    "kind": "boundary",
                    "id": values.get("nodeId", "").strip(),
                    "quantity": values.get("quantity", "").strip(),
                    "nodeId": values.get("nodeId", "").strip(),
                    "branchId": "",
                    "chainage": "",
                    "forcingfile": values.get("forcingfile", "").strip(),
                })
            elif section == "lateral":
                rows.append({
                    "kind": "lateral",
                    "id": values.get("id", "").strip() or values.get("name", "").strip(),
                    "quantity": "lateral_discharge",
                    "nodeId": "",
                    "branchId": values.get("branchId", "").strip(),
                    "chainage": values.get("chainage", "").strip(),
                    "forcingfile": values.get("discharge", "").strip(),
                })
        return rows

    def load_ext_file(self, filepath, grid_path=None):
        """Import FM external forcing as spatial features and link BC forcing series."""
        ext_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(ext_path)

        try:
            rows = self._parse_ext_file(ext_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not import EXT file: {exc}",
            )
            return

        context, resolved_grid = self._resolve_spatial_context(grid_path, base_dir)
        if context is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Spatial import requires a valid grid file.",
            )
            return

        bc_records_by_file = {}
        bc_files = []
        for row in rows:
            resolved_bc = self._resolve_candidate_path(base_dir, row.get("forcingfile", ""))
            if resolved_bc and os.path.exists(resolved_bc) and resolved_bc.lower().endswith(".bc"):
                bc_files.append(resolved_bc)

        for bc_path in sorted(set(bc_files)):
            try:
                bc_records_by_file[bc_path] = self._parse_bc_forcing_file(bc_path)
            except Exception:
                bc_records_by_file[bc_path] = []

        layer = QgsVectorLayer(
            f"Point?crs=EPSG:{context['epsg']}",
            f"{os.path.splitext(os.path.basename(ext_path))[0]}_ext_spatial",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("kind", QVariant.String),
            QgsField("bc_type", QVariant.String),
            QgsField("id", QVariant.String),
            QgsField("quantity", QVariant.String),
            QgsField("nodeId", QVariant.String),
            QgsField("branchId", QVariant.String),
            QgsField("chainage", QVariant.Double),
            QgsField("forcingfile", QVariant.String),
            QgsField("bc_name", QVariant.String),
            QgsField("bc_function", QVariant.String),
            QgsField("quantity_1", QVariant.String),
            QgsField("unit_1", QVariant.String),
            QgsField("quantity_2", QVariant.String),
            QgsField("unit_2", QVariant.String),
            QgsField("sample_cnt", QVariant.Int),
            QgsField("series_xy", QVariant.String),
            QgsField("source_ext", QVariant.String),
            QgsField("source_grid", QVariant.String),
        ])
        layer.updateFields()

        features = []
        unresolved = 0
        branch_lookup = context["branch_lookup"]
        normalized_branch_lookup = {
            self._normalize_branch_key(key): profile
            for key, profile in branch_lookup.items()
        }
        node_lookup = context["node_lookup"]

        for row in rows:
            point_xy = None
            row_id = str(row.get("id", "")).strip()
            kind = str(row.get("kind", "")).strip().lower()

            if kind == "boundary":
                node_id = str(row.get("nodeId", "")).strip().lower()
                point_xy = node_lookup.get(node_id)
            elif kind == "lateral":
                branch_id = str(row.get("branchId", "")).strip().lower()
                chainage_text = str(row.get("chainage", "")).strip()
                profile = branch_lookup.get(branch_id)
                try:
                    chainage_val = float(chainage_text) if chainage_text else 0.0
                except ValueError:
                    chainage_val = None
                if profile is not None and chainage_val is not None:
                    point_xy = self._interpolate_point_on_branch(profile, chainage_val)

            if point_xy is None:
                unresolved += 1
                continue

            forcing_file = str(row.get("forcingfile", "")).strip()
            resolved_bc = self._resolve_candidate_path(base_dir, forcing_file)
            bc_rows = bc_records_by_file.get(resolved_bc, [])
            bc_lookup = self._bc_name_lookup(bc_rows)
            bc_record = bc_lookup.get(row_id.lower())

            if bc_record is None and kind == "boundary":
                node_key = str(row.get("nodeId", "")).strip().lower()
                bc_record = bc_lookup.get(node_key)

            series = [] if bc_record is None else bc_record.get("series", [])
            series_text = self._series_text_from_points(series)
            bc_type = str(row.get("quantity", "")).strip()
            if not bc_type and bc_record is not None:
                bc_type = str(bc_record.get("quantity_2", "")).strip() or str(bc_record.get("bc_function", "")).strip()
            if not bc_type:
                bc_type = kind or "unknown"

            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_xy[0], point_xy[1])))
            feature.setAttributes([
                row.get("kind", ""),
                bc_type,
                row_id,
                row.get("quantity", ""),
                row.get("nodeId", ""),
                row.get("branchId", ""),
                float(row.get("chainage", 0.0) or 0.0) if str(row.get("chainage", "")).strip() else 0.0,
                forcing_file,
                "" if bc_record is None else bc_record.get("bc_name", ""),
                "" if bc_record is None else bc_record.get("bc_function", ""),
                "" if bc_record is None else bc_record.get("quantity_1", ""),
                "" if bc_record is None else bc_record.get("unit_1", ""),
                "" if bc_record is None else bc_record.get("quantity_2", ""),
                "" if bc_record is None else bc_record.get("unit_2", ""),
                len(series),
                series_text,
                os.path.basename(ext_path),
                os.path.basename(resolved_grid),
            ])
            features.append(feature)

        if not features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No spatial EXT features could be derived from branch/node references.",
            )
            return

        provider.addFeatures(features)
        layer.updateExtents()
        self._apply_boundary_type_categorized_style(layer)
        QgsProject.instance().addMapLayer(layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {len(features)} spatial forcing feature(s) from {os.path.basename(ext_path)} (unresolved: {unresolved}).",
        )

    def _parse_structures_file(self, filepath):
        """Parse [Structure] blocks from a structures file."""
        records = []
        for block in self._parse_repeated_ini_sections(filepath):
            if block["section"].strip().lower() != "structure":
                continue
            values = block["values"]
            normalized = {
                str(key).strip().lower(): "" if value is None else str(value).strip()
                for key, value in values.items()
            }
            structure_ids_text = normalized.get("structureids", "")
            structure_ids = [
                token for token in re.split(r"[;,\s]+", structure_ids_text) if token
            ]
            record = {
                "id": normalized.get("id", ""),
                "name": normalized.get("name", ""),
                "type": normalized.get("type", ""),
                "branchId": normalized.get("branchid", ""),
                "chainage": normalized.get("chainage", ""),
                "capacity": normalized.get("capacity", ""),
                "structureIds": structure_ids,
                "normalized": normalized,
                "raw": values,
            }
            records.append(record)
        return records

    def _build_structure_dynamic_fields(self, records, excluded_keys, used_names):
        """Build dynamic structure fields from keys present in the file."""
        key_values = {}
        for record in records:
            for key, value in record.get("normalized", {}).items():
                if key in excluded_keys:
                    continue
                key_values.setdefault(key, []).append(value)

        def infer_qvariant(values):
            non_empty = [str(item).strip() for item in values if str(item).strip()]
            if not non_empty:
                return QVariant.String
            for item in non_empty:
                try:
                    number = float(item)
                except ValueError:
                    return QVariant.String
                if not math.isfinite(number):
                    return QVariant.String
            return QVariant.Double

        def make_field_name(raw_key):
            name = re.sub(r"[^a-z0-9_]", "_", str(raw_key).strip().lower())
            if not name:
                name = "attr"
            if name[0].isdigit():
                name = f"f_{name}"
            name = name[:48]

            candidate = name
            suffix = 1
            while candidate in used_names:
                base = name[:44]
                candidate = f"{base}_{suffix}"
                suffix += 1
            used_names.add(candidate)
            return candidate

        mapping = {}
        fields = []
        for key in sorted(key_values.keys()):
            field_name = make_field_name(key)
            mapping[key] = field_name
            fields.append(QgsField(field_name, infer_qvariant(key_values[key])))
        return fields, mapping

    def _set_feature_dynamic_attributes(self, feature, record, key_mapping):
        """Populate dynamic structure attributes for a feature."""
        values = record.get("normalized", {})
        for key, field_name in key_mapping.items():
            raw_value = str(values.get(key, "")).strip()
            if raw_value == "":
                continue
            current_value = feature[field_name]
            if isinstance(current_value, (float, int)):
                try:
                    feature[field_name] = float(raw_value)
                except ValueError:
                    feature[field_name] = None
            else:
                feature[field_name] = raw_value

    def _apply_structure_type_categorized_style(self, layer):
        """Apply categorized point styling to structures by type field."""
        try:
            type_values = set()
            for feature in layer.getFeatures():
                type_value = str(feature["type"]).strip()
                if type_value:
                    type_values.add(type_value)
        except Exception:
            return

        if not type_values:
            return

        known_colors = {
            "weir": "#D1495B",
            "gate": "#00798C",
            "pump": "#30638E",
            "orifice": "#8F2D56",
            "culvert": "#0B6E4F",
            "bridge": "#2A9D8F",
            "checkvalve": "#6D597A",
            "generalstructure": "#EDAE49",
            "dambreak": "#BC4749",
            "longculvert": "#3F88C5",
            "universalweir": "#D17A22",
            "riverweir": "#A44A3F",
            "weirgen": "#B56576",
            "pumpstation": "#355070",
        }
        fallback_palette = [
            "#0B6E4F",
            "#D1495B",
            "#00798C",
            "#EDAE49",
            "#30638E",
            "#8F2D56",
            "#3F88C5",
            "#2A9D8F",
            "#6D597A",
            "#BC4749",
        ]

        def color_for_type(type_value):
            type_key = str(type_value).strip().lower()
            if type_key in known_colors:
                return known_colors[type_key]

            # Use a stable checksum to pick a fallback color for unknown types.
            checksum = sum(ord(ch) for ch in type_key)
            return fallback_palette[checksum % len(fallback_palette)]

        categories = []
        for type_value in sorted(type_values, key=lambda t: t.lower()):
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            try:
                symbol.setColor(QColor(color_for_type(type_value)))
            except (AttributeError, TypeError):
                pass
            categories.append(QgsRendererCategory(type_value, symbol, type_value))

        renderer = QgsCategorizedSymbolRenderer("type", categories)
        layer.setRenderer(renderer)
        try:
            layer.triggerRepaint()
        except RuntimeError:
            pass

    def _apply_boundary_type_categorized_style(self, layer):
        """Apply categorized point styling to boundary-condition spatial features."""
        try:
            type_values = set()
            for feature in layer.getFeatures():
                type_value = str(feature["bc_type"]).strip()
                if type_value:
                    type_values.add(type_value)
        except Exception:
            return

        if not type_values:
            return

        known_colors = {
            "dischargebnd": "#1D3557",
            "waterlevelbnd": "#0077B6",
            "salinitybnd": "#2A9D8F",
            "temperaturebnd": "#E76F51",
            "sedimentbnd": "#8D6E63",
            "lateral_discharge": "#6A4C93",
            "timeseries": "#3A86FF",
            "constant": "#FF006E",
        }
        fallback_palette = [
            "#0B6E4F",
            "#D1495B",
            "#00798C",
            "#EDAE49",
            "#30638E",
            "#8F2D56",
            "#3F88C5",
            "#2A9D8F",
            "#6D597A",
            "#BC4749",
        ]

        def color_for_type(type_value):
            type_key = str(type_value).strip().lower()
            if type_key in known_colors:
                return known_colors[type_key]

            checksum = sum(ord(ch) for ch in type_key)
            return fallback_palette[checksum % len(fallback_palette)]

        categories = []
        for type_value in sorted(type_values, key=lambda t: t.lower()):
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            try:
                symbol.setColor(QColor(color_for_type(type_value)))
            except (AttributeError, TypeError):
                pass
            categories.append(QgsRendererCategory(type_value, symbol, type_value))

        renderer = QgsCategorizedSymbolRenderer("bc_type", categories)
        layer.setRenderer(renderer)
        try:
            layer.triggerRepaint()
        except RuntimeError:
            pass

    def load_structures_spatial_file(self, filepath, grid_path=None):
        """Import structures as spatial point features using branchId/chainage."""
        structures_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(structures_path)

        try:
            records = self._parse_structures_file(structures_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not read structures file: {exc}",
            )
            return

        compound_records = []
        spatial_records = []
        for record in records:
            struct_type = str(record.get("type", "")).strip().lower()
            if struct_type == "compound":
                compound_records.append(record)
            else:
                spatial_records.append(record)

        context = {"branch_lookup": {}, "node_lookup": {}, "epsg": 28992}
        resolved_grid = ""
        if spatial_records:
            resolved_context, resolved_grid_path = self._resolve_spatial_context(grid_path, base_dir)
            if resolved_context is not None:
                context = resolved_context
                resolved_grid = resolved_grid_path

        excluded_spatial_keys = {
            "id", "name", "type", "branchid", "chainage", "capacity", "structureids"
        }
        excluded_compound_keys = {"id", "name", "type", "structureids"}

        spatial_field_names = {
            "id", "name", "type", "branchid", "chainage", "capacity", "bc_name",
            "bc_function", "quantity_1", "unit_1", "sample_cnt", "series_xy",
            "resolve_status", "resolve_note", "source_ini", "source_grid", "raw_json"
        }
        compound_field_names = {
            "id", "name", "type", "structureids", "child_count", "source_ini", "raw_json"
        }

        spatial_dynamic_fields, spatial_key_mapping = self._build_structure_dynamic_fields(
            spatial_records, excluded_spatial_keys, spatial_field_names
        )
        compound_dynamic_fields, compound_key_mapping = self._build_structure_dynamic_fields(
            compound_records, excluded_compound_keys, compound_field_names
        )

        layer = QgsVectorLayer(
            f"Point?crs=EPSG:{context['epsg']}",
            f"{os.path.splitext(os.path.basename(structures_path))[0]}_structures",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("id", QVariant.String),
            QgsField("name", QVariant.String),
            QgsField("type", QVariant.String),
            QgsField("branchId", QVariant.String),
            QgsField("chainage", QVariant.Double),
            QgsField("capacity", QVariant.String),
            QgsField("bc_name", QVariant.String),
            QgsField("bc_function", QVariant.String),
            QgsField("quantity_1", QVariant.String),
            QgsField("unit_1", QVariant.String),
            QgsField("sample_cnt", QVariant.Int),
            QgsField("series_xy", QVariant.String),
            QgsField("resolve_status", QVariant.String),
            QgsField("resolve_note", QVariant.String),
            QgsField("source_ini", QVariant.String),
            QgsField("source_grid", QVariant.String),
            QgsField("raw_json", QVariant.String),
        ])
        if spatial_dynamic_fields:
            provider.addAttributes(spatial_dynamic_fields)
        layer.updateFields()

        features = []
        unresolved = 0
        resolved = 0
        branch_lookup = context["branch_lookup"]
        normalized_branch_lookup = {
            self._normalize_branch_key(key): profile
            for key, profile in branch_lookup.items()
        }

        for record in spatial_records:
            branch_id_raw = str(record.get("branchId", "")).strip()
            branch_id = self._normalize_branch_key(branch_id_raw)
            point_xy = None
            chainage_val = None
            resolve_status = "resolved"
            resolve_note = ""

            if not branch_id:
                resolve_status = "unresolved"
                resolve_note = "missing branchId"
            else:
                profile = branch_lookup.get(branch_id)
                if profile is None:
                    profile = normalized_branch_lookup.get(branch_id)
                if profile is None:
                    resolve_status = "unresolved"
                    resolve_note = f"unknown branchId: {branch_id_raw}"
                else:
                    chainage_val = self._parse_first_float(record.get("chainage", ""))
                    if chainage_val is None:
                        resolve_status = "unresolved"
                        resolve_note = f"invalid chainage: {record.get('chainage', '')}"
                    else:
                        point_xy = self._interpolate_point_on_branch(profile, chainage_val)
                        if point_xy is None:
                            resolve_status = "unresolved"
                            max_chainage = profile.get("length", None)
                            if isinstance(max_chainage, (int, float)) and math.isfinite(float(max_chainage)):
                                resolve_note = (
                                    f"chainage out of range: requested {chainage_val:g}, max {float(max_chainage):g}"
                                )
                            else:
                                resolve_note = f"chainage out of range: requested {chainage_val:g}"

            bc_record = None
            cap_ref = str(record.get("capacity", "")).strip()
            if cap_ref.lower().endswith(".bc"):
                bc_path = self._resolve_candidate_path(base_dir, cap_ref)
                if os.path.exists(bc_path):
                    bc_lookup = self._bc_name_lookup(self._parse_bc_forcing_file(bc_path))
                    key_options = [str(record.get("id", "")).strip().lower(), str(record.get("name", "")).strip().lower()]
                    for key in key_options:
                        if key and key in bc_lookup:
                            bc_record = bc_lookup[key]
                            break

            series = [] if bc_record is None else bc_record.get("series", [])

            feature = QgsFeature(layer.fields())
            if point_xy is not None:
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_xy[0], point_xy[1])))
                resolved += 1
            else:
                unresolved += 1

            feature["id"] = record.get("id", "")
            feature["name"] = record.get("name", "")
            feature["type"] = record.get("type", "")
            feature["branchId"] = branch_id_raw
            feature["chainage"] = chainage_val if chainage_val is not None else None
            feature["capacity"] = cap_ref
            feature["bc_name"] = "" if bc_record is None else bc_record.get("bc_name", "")
            feature["bc_function"] = "" if bc_record is None else bc_record.get("bc_function", "")
            feature["quantity_1"] = "" if bc_record is None else bc_record.get("quantity_1", "")
            feature["unit_1"] = "" if bc_record is None else bc_record.get("unit_1", "")
            feature["sample_cnt"] = len(series)
            feature["series_xy"] = self._series_text_from_points(series)
            feature["resolve_status"] = resolve_status
            feature["resolve_note"] = resolve_note
            feature["source_ini"] = os.path.basename(structures_path)
            feature["source_grid"] = os.path.basename(resolved_grid)
            feature["raw_json"] = json.dumps(record.get("raw", {}), ensure_ascii=True)
            self._set_feature_dynamic_attributes(feature, record, spatial_key_mapping)
            features.append(feature)

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
            self._apply_structure_type_categorized_style(layer)
            QgsProject.instance().addMapLayer(layer)

        compound_count = 0
        if compound_records:
            compound_layer = QgsVectorLayer(
                "None",
                f"{os.path.splitext(os.path.basename(structures_path))[0]}_structures_compound",
                "memory",
            )
            compound_provider = compound_layer.dataProvider()
            compound_provider.addAttributes([
                QgsField("id", QVariant.String),
                QgsField("name", QVariant.String),
                QgsField("type", QVariant.String),
                QgsField("structureIds", QVariant.String),
                QgsField("child_count", QVariant.Int),
                QgsField("source_ini", QVariant.String),
                QgsField("raw_json", QVariant.String),
            ])
            if compound_dynamic_fields:
                compound_provider.addAttributes(compound_dynamic_fields)
            compound_layer.updateFields()

            compound_features = []
            for record in compound_records:
                feature = QgsFeature(compound_layer.fields())
                structure_ids = record.get("structureIds", [])
                feature["id"] = record.get("id", "")
                feature["name"] = record.get("name", "")
                feature["type"] = record.get("type", "")
                feature["structureIds"] = ";".join(structure_ids)
                feature["child_count"] = len(structure_ids)
                feature["source_ini"] = os.path.basename(structures_path)
                feature["raw_json"] = json.dumps(record.get("raw", {}), ensure_ascii=True)
                self._set_feature_dynamic_attributes(feature, record, compound_key_mapping)
                compound_features.append(feature)

            if compound_features:
                compound_provider.addFeatures(compound_features)
                compound_layer.updateExtents()
                QgsProject.instance().addMapLayer(compound_layer)
                compound_count = len(compound_features)

        if not features and compound_count == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No structure records were found in the selected file.",
            )
            return

        type_counts = {}
        all_unknown_types = set()
        known_types = {
            "pump", "weir", "gate", "orifice", "culvert", "bridge", "checkvalve",
            "generalstructure", "dambreak", "longculvert", "universalweir",
            "riverweir", "weirgen", "pumpstation", "compound"
        }
        for record in records:
            type_key = str(record.get("type", "")).strip() or "(unknown)"
            type_counts[type_key] = type_counts.get(type_key, 0) + 1
            if type_key != "(unknown)" and type_key.lower() not in known_types:
                all_unknown_types.add(type_key)
        counts_text = ", ".join(f"{name}:{count}" for name, count in sorted(type_counts.items()))

        summary = (
            f"Loaded structure records from {os.path.basename(structures_path)}: "
            f"spatial total {len(features)} (resolved {resolved}, unresolved {unresolved}), "
            f"compound table {compound_count}, unknown types {len(all_unknown_types)}. "
            f"Types: {counts_text}."
        )
        self.iface.messageBar().pushSuccess("Delft3D File Manager", summary)

        if all_unknown_types:
            unknown_text = ", ".join(sorted(all_unknown_types))
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                f"Unknown structure type(s) imported with raw attributes: {unknown_text}.",
            )

    def load_ini_field_spatial_file(self, filepath, grid_path=None):
        """Import iniField file by resolving its referenced dataFile."""
        ini_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(ini_path)

        sections = self._parse_repeated_ini_sections(ini_path)
        data_file = ""
        for block in sections:
            if block["section"].strip().lower() != "initial":
                continue
            data_file = block["values"].get("dataFile", "").strip()
            if data_file:
                break

        if not data_file:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Could not find dataFile entry in iniField file.",
            )
            return

        resolved_data = self._resolve_candidate_path(base_dir, data_file)
        if not os.path.exists(resolved_data):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Referenced dataFile does not exist: {resolved_data}",
            )
            return

        self.load_1d_field_spatial_file(resolved_data, grid_path=grid_path)

    def load_1d_field_spatial_file(self, filepath, grid_path=None):
        """Import 1dField branch chainage/value arrays as spatial points."""
        field_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(field_path)

        context, resolved_grid = self._resolve_spatial_context(grid_path, base_dir)
        if context is None:
            return

        sections = self._parse_repeated_ini_sections(field_path)
        layer = QgsVectorLayer(
            f"Point?crs=EPSG:{context['epsg']}",
            f"{os.path.splitext(os.path.basename(field_path))[0]}_field",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("branchId", QVariant.String),
            QgsField("chainage", QVariant.Double),
            QgsField("value", QVariant.Double),
            QgsField("quantity", QVariant.String),
            QgsField("unit", QVariant.String),
            QgsField("source_ini", QVariant.String),
            QgsField("source_grid", QVariant.String),
        ])
        layer.updateFields()

        quantity = ""
        unit = ""
        for block in sections:
            if block["section"].strip().lower() == "global":
                quantity = block["values"].get("quantity", "").strip()
                unit = block["values"].get("unit", "").strip()
                break

        features = []
        unresolved = 0
        branch_lookup = context["branch_lookup"]

        for block in sections:
            if block["section"].strip().lower() != "branch":
                continue

            values = block["values"]
            branch_id = values.get("branchId", "").strip()
            if not branch_id:
                continue

            chainage_vals = self._parse_numeric_list(values.get("chainage", ""))
            value_vals = self._parse_numeric_list(values.get("values", ""))
            n = min(len(chainage_vals), len(value_vals))
            if n == 0:
                continue

            profile = branch_lookup.get(branch_id.lower())
            if profile is None:
                unresolved += n
                continue

            for idx in range(n):
                point_xy = self._interpolate_point_on_branch(profile, chainage_vals[idx])
                if point_xy is None:
                    unresolved += 1
                    continue

                feature = QgsFeature(layer.fields())
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_xy[0], point_xy[1])))
                feature.setAttributes([
                    branch_id,
                    float(chainage_vals[idx]),
                    float(value_vals[idx]),
                    quantity,
                    unit,
                    os.path.basename(field_path),
                    os.path.basename(resolved_grid),
                ])
                features.append(feature)

        if not features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No spatial 1dField features could be created.",
            )
            return

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {len(features)} spatial 1dField point(s) from {os.path.basename(field_path)} (unresolved: {unresolved}).",
        )

    def load_roughness_spatial_file(self, filepath, grid_path=None):
        """Import roughness branch chainage/value arrays as spatial points."""
        rough_path = os.path.abspath(filepath)
        base_dir = os.path.dirname(rough_path)

        context, resolved_grid = self._resolve_spatial_context(grid_path, base_dir)
        if context is None:
            return

        sections = self._parse_repeated_ini_sections(rough_path)
        layer = QgsVectorLayer(
            f"Point?crs=EPSG:{context['epsg']}",
            f"{os.path.splitext(os.path.basename(rough_path))[0]}_roughness",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("branchId", QVariant.String),
            QgsField("chainage", QVariant.Double),
            QgsField("fric_value", QVariant.Double),
            QgsField("fric_type", QVariant.String),
            QgsField("function", QVariant.String),
            QgsField("source_ini", QVariant.String),
            QgsField("source_grid", QVariant.String),
        ])
        layer.updateFields()

        features = []
        unresolved = 0
        skipped_no_branch = 0
        skipped_no_values = 0
        skipped_no_chainage = 0
        skipped_no_match = 0
        candidate_blocks = 0
        section_names = set()
        branch_lookup = context["branch_lookup"]
        normalized_branch_lookup = {
            self._normalize_branch_key(key): profile
            for key, profile in branch_lookup.items()
        }
        global_values = {}
        for block in sections:
            if block["section"].strip().lower() == "global":
                global_values = block["values"]
                break

        for block in sections:
            section_name = block["section"].strip().lower()
            section_names.add(section_name)
            values = block["values"]

            # Accept both explicit [Branch] and branch-like sections carrying required keys.
            has_branch_key = self._has_any_key_case_insensitive(values, "branchId", "branch", "branch_id")
            has_chainage_key = self._has_any_key_case_insensitive(values, "chainage", "chainages")
            has_friction_key = self._has_any_key_case_insensitive(
                values,
                "frictionValues",
                "frictionValue",
                "friction",
                "values",
            )
            is_candidate = (section_name == "branch") or (has_branch_key and has_chainage_key and has_friction_key)
            if not is_candidate:
                continue
            candidate_blocks += 1

            branch_id = self._value_case_insensitive(values, "branchId", "branch", "branch_id")
            chainage_vals = self._parse_numeric_list(
                self._value_case_insensitive(values, "chainage", "chainages")
            )
            fric_vals = self._parse_numeric_list(
                self._value_case_insensitive(
                    values,
                    "frictionValues",
                    "frictionValue",
                    "friction",
                    "values",
                )
            )
            n = min(len(chainage_vals), len(fric_vals))
            if not branch_id:
                skipped_no_branch += 1
                continue
            if not chainage_vals:
                skipped_no_chainage += 1
                continue
            if not fric_vals:
                skipped_no_values += 1
                continue
            if n == 0:
                skipped_no_match += 1
                continue

            normalized_branch_id = self._normalize_branch_key(branch_id)
            profile = branch_lookup.get(normalized_branch_id)
            if profile is None:
                profile = normalized_branch_lookup.get(normalized_branch_id)
            if profile is None:
                unresolved += n
                continue

            for idx in range(n):
                point_xy = self._interpolate_point_on_branch(profile, chainage_vals[idx])
                if point_xy is None:
                    unresolved += 1
                    continue

                feature = QgsFeature(layer.fields())
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_xy[0], point_xy[1])))
                feature.setAttributes([
                    branch_id,
                    float(chainage_vals[idx]),
                    float(fric_vals[idx]),
                    self._value_case_insensitive(values, "frictionType", "friction_type"),
                    self._value_case_insensitive(values, "functionType", "function", "function_type"),
                    os.path.basename(rough_path),
                    os.path.basename(resolved_grid),
                ])
                features.append(feature)

        if not features and candidate_blocks == 0:
            global_fric_text = self._value_case_insensitive(
                global_values,
                "frictionValues",
                "frictionValue",
                "friction",
                "values",
            )
            global_fric_type = self._value_case_insensitive(global_values, "frictionType", "friction_type")
            global_function = self._value_case_insensitive(global_values, "functionType", "function", "function_type")
            global_fric_value = self._parse_first_float(global_fric_text)

            if global_fric_value is not None and branch_lookup:
                seen_profiles = set()
                for profile in branch_lookup.values():
                    profile_key = id(profile)
                    if profile_key in seen_profiles:
                        continue
                    seen_profiles.add(profile_key)

                    length = float(profile.get("length", 0.0) or 0.0)
                    chainage_mid = length * 0.5
                    point_xy = self._interpolate_point_on_branch(profile, chainage_mid)
                    if point_xy is None:
                        points = profile.get("points", [])
                        point_xy = points[0] if points else None
                        if point_xy is None:
                            continue
                        chainage_mid = 0.0

                    feature = QgsFeature(layer.fields())
                    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_xy[0], point_xy[1])))
                    feature.setAttributes([
                        profile.get("name", ""),
                        float(chainage_mid),
                        float(global_fric_value),
                        global_fric_type,
                        global_function,
                        os.path.basename(rough_path),
                        os.path.basename(resolved_grid),
                    ])
                    features.append(feature)

                if features:
                    provider.addFeatures(features)
                    layer.updateExtents()
                    QgsProject.instance().addMapLayer(layer)
                    self.iface.messageBar().pushSuccess(
                        "Delft3D File Manager",
                        (
                            f"Loaded {len(features)} spatial roughness point(s) from {os.path.basename(rough_path)} "
                            "using global roughness defaults (one midpoint per branch)."
                        ),
                    )
                    return

        if not features:
            section_names_text = ", ".join(sorted(name for name in section_names if name))
            if not section_names_text:
                section_names_text = "(none)"
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                (
                    "No spatial roughness features could be created. "
                    f"Candidate roughness blocks processed={candidate_blocks}; "
                    f"Skipped blocks: missing branchId={skipped_no_branch}, "
                    f"missing chainage={skipped_no_chainage}, "
                    f"missing friction values={skipped_no_values}, "
                    f"non-overlapping arrays={skipped_no_match}; unresolved points={unresolved}. "
                    f"Sections found: {section_names_text}."
                ),
            )
            return

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {len(features)} spatial roughness point(s) from {os.path.basename(rough_path)} (unresolved: {unresolved}).",
        )

    def load_ini_table_file(self, filepath):
        """Import generic Delft3D INI file as repeated section/key/value table."""
        ini_path = os.path.abspath(filepath)
        try:
            sections = self._parse_repeated_ini_sections(ini_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not import INI file: {exc}",
            )
            return

        base_name = os.path.splitext(os.path.basename(ini_path))[0]
        layer = QgsVectorLayer("None", f"{base_name}_ini", "memory")
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("section", QVariant.String),
            QgsField("key", QVariant.String),
            QgsField("value", QVariant.String),
            QgsField("source", QVariant.String),
        ])
        layer.updateFields()

        features = []
        for block in sections:
            section = block["section"]
            for key, value in block["values"].items():
                feature = QgsFeature(layer.fields())
                feature.setAttributes([section, key, value, os.path.basename(ini_path)])
                features.append(feature)

        if not features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No key/value entries were found in the selected INI file.",
            )
            return

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {len(features)} INI row(s) from {os.path.basename(ini_path)}",
        )

    def _connect_canvas_double_click(self):
        """Connect to map canvas double-click events, failing gracefully in test stubs."""
        if self._canvas_double_click_connected:
            return

        try:
            canvas = self.iface.mapCanvas()
            viewport = canvas.viewport()
            self._canvas_double_click_filter = _CanvasDoubleClickFilter(
                canvas, self._handle_canvas_double_click
            )
            viewport.installEventFilter(self._canvas_double_click_filter)
            self._canvas_double_click_connected = True
        except Exception:
            self._canvas_double_click_filter = None
            self._canvas_double_click_connected = False

    def _disconnect_canvas_double_click(self):
        """Disconnect canvas double-click handling if it was connected."""
        if not self._canvas_double_click_connected:
            self._canvas_double_click_filter = None
            return

        try:
            canvas = self.iface.mapCanvas()
            viewport = canvas.viewport()
            if self._canvas_double_click_filter is not None:
                viewport.removeEventFilter(self._canvas_double_click_filter)
        except (RuntimeError, AttributeError):
            pass

        self._canvas_double_click_filter = None
        self._canvas_double_click_connected = False

    def _parse_repeated_ini_sections(self, filepath):
        """Parse INI-style files while preserving repeated section blocks."""
        sections = []
        current_section = None
        current_values = {}

        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except UnicodeDecodeError:
            with open(filepath, "r") as handle:
                lines = handle.readlines()

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue

            if line.startswith("[") and line.endswith("]"):
                if current_section is not None:
                    sections.append({"section": current_section, "values": current_values})
                current_section = line[1:-1].strip()
                current_values = {}
                continue

            if "=" not in line or current_section is None:
                continue

            key, value = line.split("=", 1)
            current_values[key.strip()] = value.strip()

        if current_section is not None:
            sections.append({"section": current_section, "values": current_values})

        return sections

    def _detect_cross_section_ini_kind(self, filepath):
        """Detect whether an INI file is crossLoc or crossDef based on [General] fileType."""
        file_type = self._detect_ini_file_type(filepath)
        if file_type in ("crossloc", "crossdef"):
            return file_type
        return None

    def _detect_ini_file_type(self, filepath):
        """Detect generic Delft3D INI fileType from [General] block."""
        try:
            sections = self._parse_repeated_ini_sections(filepath)
        except OSError:
            return None

        for block in sections:
            if block["section"].strip().lower() != "general":
                continue
            file_type = block["values"].get("fileType", "").strip().lower()
            if file_type:
                return file_type
        return None

    def _read_crossloc_records(self, csl_path):
        """Read [CrossSection] records from a cross-section location file."""
        records = []
        for block in self._parse_repeated_ini_sections(csl_path):
            if block["section"].strip().lower() != "crosssection":
                continue

            values = block["values"]
            record = {
                "id": values.get("id", "").strip(),
                "branchId": values.get("branchId", "").strip(),
                "definitionId": values.get("definitionId", "").strip(),
            }

            if not record["id"] or not record["branchId"] or not record["definitionId"]:
                continue

            try:
                record["chainage"] = float(values.get("chainage", "0"))
                record["shift"] = float(values.get("shift", "0"))
            except ValueError:
                continue

            records.append(record)

        return records

    def _read_crossdef_records(self, csd_path):
        """Read [Definition] records keyed by definition id."""
        definitions = {}
        for block in self._parse_repeated_ini_sections(csd_path):
            if block["section"].strip().lower() != "definition":
                continue

            values = block["values"]
            definition_id = values.get("id", "").strip()
            if not definition_id:
                continue

            normalized = {}
            for key, value in values.items():
                normalized[key.strip().lower()] = value.strip()

            definitions[definition_id.lower()] = normalized

        return definitions

    def _definition_to_text(self, definition):
        """Serialize a cross-section definition dictionary to text."""
        if not definition:
            return ""

        parts = []
        for key in sorted(definition.keys()):
            parts.append(f"{key}={definition[key]}")
        return " | ".join(parts)

    def _read_mesh_branch_profiles_from_grid(self, grid_path):
        """Read mesh1d branches from grid file and build branch chainage profiles."""
        try:
            import netCDF4 as nc
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS."
            ) from exc

        with nc.Dataset(grid_path, "r") as ds:
            mesh1d_data = self._read_mesh1d_data(ds) if self._detect_mesh1d_exists(ds) else None
            if mesh1d_data is None:
                raise RuntimeError("No mesh1d data found in the selected grid")

            epsg = self._read_epsg_from_nc(ds)
            if epsg is None:
                epsg = 28992

        branch_lookup = self._build_branch_lookup(mesh1d_data)
        return branch_lookup, epsg

    def _build_branch_lookup(self, mesh1d_data):
        """Build a case-insensitive branch lookup with cumulative chainage profiles."""
        import numpy as np

        node_x = mesh1d_data["node_x"]
        node_y = mesh1d_data["node_y"]
        edges = mesh1d_data["edges"]
        edge_branch = mesh1d_data["edge_branch"]
        branch_names = mesh1d_data.get("branch_names")

        lookup = {}
        unique_branches = np.unique(edge_branch)

        for branch_id in sorted(unique_branches):
            branch_edge_indices = np.where(edge_branch == branch_id)[0]
            if len(branch_edge_indices) == 0:
                continue

            adjacency = {}
            branch_edges = []
            for edge_idx in branch_edge_indices:
                edge = edges[edge_idx]
                start_node = int(edge[0])
                end_node = int(edge[1])
                branch_edges.append((start_node, end_node))

                adjacency.setdefault(start_node, []).append(end_node)
                adjacency.setdefault(end_node, []).append(start_node)

            if not branch_edges:
                continue

            start_node = None
            for node_id, neighbors in adjacency.items():
                if len(neighbors) == 1:
                    start_node = node_id
                    break
            if start_node is None:
                start_node = branch_edges[0][0]

            ordered_nodes = [start_node]
            previous_node = None
            current_node = start_node
            while len(ordered_nodes) < len(adjacency):
                neighbors = adjacency.get(current_node, [])
                next_node = None
                for neighbor in neighbors:
                    if neighbor != previous_node:
                        next_node = neighbor
                        break
                if next_node is None:
                    break

                ordered_nodes.append(next_node)
                previous_node = current_node
                current_node = next_node

            if len(ordered_nodes) < 2:
                continue

            points = []
            for node_id in ordered_nodes:
                points.append((float(node_x[node_id]), float(node_y[node_id])))

            cumlen = [0.0]
            for idx in range(1, len(points)):
                x0, y0 = points[idx - 1]
                x1, y1 = points[idx]
                cumlen.append(cumlen[-1] + math.hypot(x1 - x0, y1 - y0))

            branch_name = f"Branch_{int(branch_id)}"
            branch_index = int(branch_id)
            if branch_names and 0 <= branch_index < len(branch_names):
                candidate = str(branch_names[branch_index]).strip()
                if candidate:
                    branch_name = candidate

            profile = {
                "name": branch_name,
                "points": points,
                "cumlen": cumlen,
                "length": cumlen[-1],
            }

            for key in (branch_name, f"branch_{int(branch_id)}", str(int(branch_id))):
                lookup[key.strip().lower()] = profile

        return lookup

    def _interpolate_point_on_branch(self, profile, target_distance):
        """Interpolate x/y coordinate on a branch profile at the requested chainage distance."""
        points = profile.get("points", [])
        cumlen = profile.get("cumlen", [])
        total_length = profile.get("length", 0.0)

        if len(points) < 2 or len(cumlen) != len(points):
            return None

        if not isinstance(target_distance, (int, float)):
            return None
        if not isinstance(total_length, (int, float)):
            return None
        if not math.isfinite(float(target_distance)) or not math.isfinite(float(total_length)):
            return None

        target_distance = float(target_distance)
        total_length = float(total_length)
        tolerance = max(1e-6, 1e-9 * max(1.0, abs(total_length)))

        if target_distance < -tolerance or target_distance > total_length + tolerance:
            return None

        # Snap tiny floating-point overshoots/undershoots to branch endpoints.
        if target_distance <= tolerance:
            return points[0]
        if abs(target_distance - total_length) <= tolerance:
            return points[-1]

        target_distance = min(max(target_distance, 0.0), total_length)

        if target_distance == 0.0:
            return points[0]
        if target_distance == total_length:
            return points[-1]

        for idx in range(len(points) - 1):
            start_dist = cumlen[idx]
            end_dist = cumlen[idx + 1]
            if target_distance < start_dist or target_distance > end_dist:
                continue

            seg_len = end_dist - start_dist
            if seg_len <= 0.0:
                continue

            t = (target_distance - start_dist) / seg_len
            x0, y0 = points[idx]
            x1, y1 = points[idx + 1]
            return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))

        return None

    def _pliz_column_count(self, filepath):
        """Return the declared data column count from a .pliz header, or None."""
        try:
            lines = self._read_non_empty_lines(filepath)

            if len(lines) < 2:
                return False

            header_parts = lines[1].split()
            if len(header_parts) < 2:
                return None

            return int(header_parts[1])
        except (OSError, ValueError, IndexError):
            return None

    def _pliz_has_extra_columns(self, filepath):
        """Backward-compatible helper retained for tests and older call paths."""
        column_count = self._pliz_column_count(filepath)
        if column_count is None:
            return False
        return column_count > 2

    def _read_non_empty_lines(self, filepath):
        """Read a text file and return stripped non-empty lines."""
        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                return [line.strip() for line in handle if line.strip()]
        except UnicodeDecodeError:
            with open(filepath, "r") as handle:
                return [line.strip() for line in handle if line.strip()]

    def _parse_pliz_blocks(self, filepath, expected_columns, block_label):
        """Parse PLIZ-like blocks and return a list of (name, rows) pairs."""
        lines = self._read_non_empty_lines(filepath)
        if not lines:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "File is empty or contains no content",
            )
            return None

        blocks = []
        i = 0

        while i < len(lines):
            block_name = lines[i]
            i += 1

            if i >= len(lines):
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Malformed file: block '{block_name}' has no header line",
                )
                return None

            header_parts = lines[i].split()
            if len(header_parts) < 2:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Malformed file: block '{block_name}' has invalid header at line {i+1}",
                )
                return None

            try:
                nrows = int(header_parts[0])
                ncols = int(header_parts[1])
            except ValueError:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Malformed file: block '{block_name}' has non-integer header values",
                )
                return None

            if ncols != expected_columns:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Malformed {block_label} file: block '{block_name}' expected {expected_columns} columns but found {ncols}.",
                )
                return None

            i += 1
            rows = []
            for row_idx in range(nrows):
                if i >= len(lines):
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Malformed file: block '{block_name}' expected {nrows} rows but ended at {row_idx}.",
                    )
                    return None

                parts = lines[i].split()
                if len(parts) < expected_columns:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Malformed file: block '{block_name}' row {row_idx+1} has fewer than {expected_columns} values.",
                    )
                    return None

                try:
                    rows.append([float(value) for value in parts[:expected_columns]])
                except ValueError as exc:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Malformed file: block '{block_name}' row {row_idx+1} has non-numeric values: {exc}",
                    )
                    return None
                i += 1

            blocks.append((block_name, rows))

        return blocks

    def load_bridge_file(self, filepath):
        """Parse bridge .pliz file and create line and point layers."""
        base_name = os.path.splitext(os.path.basename(filepath))[0]

        line_layer = QgsVectorLayer(f"LineString?crs=EPSG:28992", base_name, "memory")
        line_provider = line_layer.dataProvider()
        line_provider.addAttributes([QgsField("bridge_name", QVariant.String)])
        line_layer.updateFields()

        point_layer = QgsVectorLayer(f"Point?crs=EPSG:28992", f"{base_name}_points", "memory")
        point_provider = point_layer.dataProvider()
        point_provider.addAttributes(
            [
                QgsField("bridge_name", QVariant.String),
                QgsField("width", QVariant.Double),
                QgsField("drag_cd", QVariant.Double),
            ]
        )
        point_layer.updateFields()

        blocks = self._parse_pliz_blocks(filepath, expected_columns=4, block_label="bridge")
        if blocks is None:
            return

        line_feature_count = 0
        point_feature_count = 0

        for bridge_name, rows in blocks:
            vertices = []
            for row in rows:
                x_coord, y_coord, width, drag_cd = row
                point = QgsPointXY(x_coord, y_coord)
                vertices.append(point)

                point_feature = QgsFeature(point_layer.fields())
                point_feature.setGeometry(QgsGeometry.fromPointXY(point))
                point_feature.setAttributes([bridge_name, width, drag_cd])
                point_provider.addFeature(point_feature)
                point_feature_count += 1

            if len(vertices) >= 2:
                line_feature = QgsFeature(line_layer.fields())
                line_feature.setGeometry(QgsGeometry.fromPolylineXY(vertices))
                line_feature.setAttributes([bridge_name])
                line_provider.addFeature(line_feature)
                line_feature_count += 1

        line_layer.updateExtents()
        point_layer.updateExtents()
        QgsProject.instance().addMapLayer(line_layer)
        QgsProject.instance().addMapLayer(point_layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {line_feature_count} bridge polyline(s) and {point_feature_count} bridge point(s)",
        )

    def load_fixed_weir_file(self, filepath):
        """Parse fixed-weir text file and create both polyline and point layers"""
        base_name = os.path.splitext(os.path.basename(filepath))[0]

        # --- Polyline layer ---
        poly_layer = QgsVectorLayer(f"LineString?crs=EPSG:28992", base_name + "_lines", "memory")
        poly_pr = poly_layer.dataProvider()
        poly_pr.addAttributes([QgsField("weir_name", QVariant.String)])
        poly_layer.updateFields()

        # --- Point layer ---
        point_layer = QgsVectorLayer(f"Point?crs=EPSG:28992", base_name + "_points", "memory")
        point_pr = point_layer.dataProvider()
        point_fields = [
            QgsField("weir_name", QVariant.String),
            QgsField("crest_lvl", QVariant.Double),
            QgsField("sill_hL", QVariant.Double),
            QgsField("sill_hR", QVariant.Double),
            QgsField("crest_w", QVariant.Double),
            QgsField("slope_L", QVariant.Double),
            QgsField("slope_R", QVariant.Double),
            QgsField("rough_cd", QVariant.Double)
        ]
        point_pr.addAttributes(point_fields)
        point_layer.updateFields()

        blocks = self._parse_pliz_blocks(filepath, expected_columns=9, block_label="fixed-weir")
        if blocks is None:
            return

        for weir_name, rows in blocks:
            pts = []

            for row in rows:
                x_coord = row[0]
                y_coord = row[1]
                vals = row[2:]
                pts.append(QgsPointXY(x_coord, y_coord))

                point_feat = QgsFeature()
                point_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x_coord, y_coord)))
                point_feat.setAttributes([weir_name] + vals)
                point_pr.addFeature(point_feat)

            if len(pts) >= 2:
                poly_feat = QgsFeature()
                poly_feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
                poly_feat.setAttributes([weir_name])
                poly_pr.addFeature(poly_feat)

        # Add layers to project
        poly_layer.updateExtents()
        point_layer.updateExtents()
        QgsProject.instance().addMapLayer(poly_layer)
        QgsProject.instance().addMapLayer(point_layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {poly_layer.featureCount()} weirs and {point_layer.featureCount()} points"
        )

    def load_polyline_file(self, filepath):
        """Parse polyline file (.pli, .ldb, .pol, .pliz) and create line layer."""
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        # Create line layer
        line_layer = QgsVectorLayer(f"LineString?crs=EPSG:28992", base_name, "memory")
        line_pr = line_layer.dataProvider()
        line_pr.addAttributes([QgsField("weir_name", QVariant.String)])
        line_layer.updateFields()
        
        # Read file
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
        except UnicodeDecodeError:
            # Fallback to system encoding if UTF-8 fails
            with open(filepath, 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
        
        if not lines:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "File is empty or contains no content"
            )
            return
        
        feature_count = 0
        i = 0
        
        try:
            while i < len(lines):
                block_name = lines[i]
                i += 1
                
                if i >= len(lines):
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Malformed file: block '{block_name}' has no header line"
                    )
                    return
                
                # Parse header line: "<npoints> 2"
                header_parts = lines[i].split()
                if len(header_parts) < 2:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Malformed file: block '{block_name}' has invalid header at line {i+1}"
                    )
                    return
                
                try:
                    npoints = int(header_parts[0])
                except ValueError:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Malformed file: block '{block_name}' has non-integer point count at line {i+1}"
                    )
                    return
                
                i += 1
                pts = []
                
                for pt_idx in range(npoints):
                    if i >= len(lines):
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Malformed file: block '{block_name}' expected {npoints} points but found {pt_idx} at line {i+1}"
                        )
                        return
                    
                    try:
                        parts = lines[i].split()
                        if len(parts) < 2:
                            QMessageBox.warning(
                                self.iface.mainWindow(),
                                "Delft3D File Manager",
                                f"Malformed file: block '{block_name}' point {pt_idx} has insufficient coordinates at line {i+1}"
                            )
                            return
                        x, y = float(parts[0]), float(parts[1])
                        pts.append(QgsPointXY(x, y))
                    except ValueError as e:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Malformed file: block '{block_name}' point {pt_idx} has non-numeric coordinates at line {i+1}: {e}"
                        )
                        return
                    
                    i += 1
                
                # Add polyline feature
                if len(pts) >= 2:
                    poly_feat = QgsFeature()
                    poly_feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
                    poly_feat.setAttributes([block_name])
                    line_pr.addFeature(poly_feat)
                    feature_count += 1
        
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Error parsing file: {e}"
            )
            return
        
        # Add layer to project
        line_layer.updateExtents()
        QgsProject.instance().addMapLayer(line_layer)
        
        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {feature_count} polyline(s) from {os.path.basename(filepath)}"
        )

    def load_xyn_file(self, filepath):
        """Parse point file (.xyn) and create point layer with x, y, name."""
        self._load_point_cloud_file(filepath, file_type="xyn")

    def load_xyz_file(self, filepath):
        """Parse point file (.xyz) and create point layer with x, y, z."""
        self._load_point_cloud_file(filepath, file_type="xyz")

    def _load_point_cloud_file(self, filepath, file_type):
        """Parse point-cloud files (.xyn or .xyz) into a memory point layer."""
        base_name = os.path.splitext(os.path.basename(filepath))[0]

        point_layer = QgsVectorLayer(f"Point?crs=EPSG:28992", base_name, "memory")
        point_pr = point_layer.dataProvider()

        if file_type == "xyz":
            fields = [
                QgsField("x", QVariant.Double),
                QgsField("y", QVariant.Double),
                QgsField("z", QVariant.Double),
            ]
        else:
            fields = [
                QgsField("x", QVariant.Double),
                QgsField("y", QVariant.Double),
                QgsField("name", QVariant.String),
            ]

        point_pr.addAttributes(fields)
        point_layer.updateFields()

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
        except UnicodeDecodeError:
            with open(filepath, "r") as f:
                lines = [line.strip() for line in f if line.strip()]

        if not lines:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "File is empty or contains no content",
            )
            return

        features = []
        generated_name_count = 1

        try:
            for line_number, line in enumerate(lines, start=1):
                parts = line.split()

                if file_type == "xyz":
                    if len(parts) != 3:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Malformed file: line {line_number} must contain exactly x y z values",
                        )
                        return

                    try:
                        x_value = float(parts[0])
                        y_value = float(parts[1])
                        z_value = float(parts[2])
                    except ValueError as e:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Malformed file: line {line_number} has non-numeric coordinates: {e}",
                        )
                        return

                    attributes = [x_value, y_value, z_value]
                else:
                    if len(parts) < 2:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Malformed file: line {line_number} has insufficient coordinates",
                        )
                        return

                    try:
                        x_value = float(parts[0])
                        y_value = float(parts[1])
                    except ValueError as e:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Malformed file: line {line_number} has non-numeric coordinates: {e}",
                        )
                        return

                    if len(parts) >= 3:
                        point_name = " ".join(parts[2:])
                    else:
                        point_name = f"obs_{generated_name_count}"
                        generated_name_count += 1

                    attributes = [x_value, y_value, point_name]

                point_feat = QgsFeature(point_layer.fields())
                point_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x_value, y_value)))
                point_feat.setAttributes(attributes)
                features.append(point_feat)

        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Error parsing file: {e}",
            )
            return

        if not features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid points were found in the selected file",
            )
            return

        point_pr.addFeatures(features)
        point_layer.updateExtents()
        QgsProject.instance().addMapLayer(point_layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Loaded {len(features)} point(s) from {os.path.basename(filepath)}",
        )

    def export_lines(self):
        """Export active line layer into custom text format."""
        layer = self.iface.activeLayer()
        if not layer or layer.type() != QgsMapLayerType.VectorLayer:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Please select a vector line layer first"
            )
            return

        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Active layer must contain line geometries"
            )
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save exported weir file",
            "",
            "Polyline (*.pli *.ldb *.spl *.pol);;XY files (*.xy);;All files (*)"
        )
        if not output_path:
            return

        allowed_extensions = (".pli", ".ldb", ".spl", ".pol", ".xy")
        if not output_path.lower().endswith(allowed_extensions):
            output_path = output_path + ".pli"

        selected_layers = self._selected_bridge_line_layers()
        source_layers = selected_layers if len(selected_layers) > 1 else [layer]

        exported_count = 0
        export_as_xy = output_path.lower().endswith(".xy")

        with open(output_path, "w", encoding="utf-8") as handle:
            is_first_polyline = True
            for source_layer in source_layers:
                layer_polylines = []
                for feature in source_layer.getFeatures():
                    geometry = feature.geometry()
                    if not geometry or geometry.isEmpty():
                        continue

                    polylines = self._extract_polylines(geometry)
                    if not polylines:
                        continue

                    for polyline in polylines:
                        if len(polyline) < 2:
                            continue
                        layer_polylines.append(polyline)

                if not layer_polylines:
                    continue

                if export_as_xy:
                    for polyline in layer_polylines:
                        if not is_first_polyline:
                            handle.write("NaN NaN\n")
                        is_first_polyline = False
                        for point in polyline:
                            handle.write(f"{point.x():.6f} {point.y():.6f}\n")
                        exported_count += 1
                    continue

                layer_name = str(source_layer.name() or "").strip() or "layer"
                use_suffix = len(layer_polylines) > 1
                for index, polyline in enumerate(layer_polylines, start=1):
                    block_name = f"{layer_name}_{index}" if use_suffix else layer_name
                    handle.write(f"{block_name}\n")
                    handle.write(f"{len(polyline)} 2\n")
                    for point in polyline:
                        handle.write(f"{point.x():.6f} {point.y():.6f}\n")
                    exported_count += 1

        if exported_count == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid line features were exported"
            )
            return

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Exported {exported_count} line feature(s) to {os.path.basename(output_path)}"
        )

    def export_active_layer(self):
        """Export the active layer to the appropriate Delft3D format."""
        layer = self.iface.activeLayer()
        if not layer or layer.type() != QgsMapLayerType.VectorLayer:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Please select a vector layer first",
            )
            return

        if layer.geometryType() == QgsWkbTypes.LineGeometry:
            self.export_lines()
            return

        if layer.geometryType() == QgsWkbTypes.PointGeometry:
            if self._is_fixed_weir_point_layer(layer):
                self.export_fixed_weir_pliz(layer)
            elif self._is_bridge_point_layer(layer):
                self.export_bridge_pliz(layer)
            else:
                self.iface.messageBar().pushWarning(
                    "Delft3D File Manager",
                    "Point layers without bridge/fixed-weir fields should be exported with 'Export Point Cloud (.xyn)'",
                )
            return

        self.iface.messageBar().pushWarning(
            "Delft3D File Manager",
            "Export supports line layers, bridge point layers, and fixed-weir point layers",
        )

    def export_bridge_pliz(self, layer):
        """Export a compatible point layer to bridge .pliz format."""
        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save Bridge PLIZ file",
            "",
            "Bridge files (*.pliz);;All files (*)",
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".pliz"):
            output_path = output_path + ".pliz"

        field_names = self._resolved_bridge_point_fields(layer)
        grouped_rows = {}
        group_order = []
        exported_count = 0

        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue

            points = self._extract_points(geometry)
            if not points:
                continue

            bridge_name = feature[field_names["bridge_name"]]
            if bridge_name is None or not str(bridge_name).strip():
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Feature {feature.id()} has an empty 'bridge_name' and cannot be exported to .pliz",
                )
                return

            bridge_name = str(bridge_name).strip()
            if bridge_name not in grouped_rows:
                grouped_rows[bridge_name] = []
                group_order.append(bridge_name)

            try:
                width = float(feature[field_names["width"]])
                drag_cd = float(feature[field_names["drag_cd"]])
            except (TypeError, ValueError):
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Feature {feature.id()} has non-numeric bridge width/drag_cd values and cannot be exported to .pliz",
                )
                return

            if not math.isfinite(width) or not math.isfinite(drag_cd):
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Feature {feature.id()} has non-finite bridge width/drag_cd values and cannot be exported to .pliz",
                )
                return

            for point in points:
                grouped_rows[bridge_name].append((point, width, drag_cd))
                exported_count += 1

        if exported_count == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid bridge point features were exported",
            )
            return

        with open(output_path, "w", encoding="utf-8") as handle:
            for bridge_name in group_order:
                rows = grouped_rows[bridge_name]
                handle.write(f"{bridge_name}\n")
                handle.write(f"{len(rows)} 4\n")
                for point, width, drag_cd in rows:
                    handle.write(f"{point.x():.6f} {point.y():.6f} {width:.6f} {drag_cd:.6f}\n")

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Exported {exported_count} bridge point(s) to {os.path.basename(output_path)}",
        )

    def export_fixed_weir_pliz(self, layer):
        """Export a compatible point layer to fixed-weir .pliz format."""
        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save PLIZ file",
            "",
            "Fixed weir files (*.pliz);;All files (*)",
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".pliz"):
            output_path = output_path + ".pliz"

        field_names = self._resolved_fixed_weir_fields(layer)
        grouped_rows = {}
        group_order = []
        exported_count = 0

        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue

            points = self._extract_points(geometry)
            if not points:
                continue

            weir_name = feature[field_names["weir_name"]]
            if weir_name is None or not str(weir_name).strip():
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Feature {feature.id()} has an empty 'weir_name' and cannot be exported to .pliz",
                )
                return

            weir_name = str(weir_name).strip()
            if weir_name not in grouped_rows:
                grouped_rows[weir_name] = []
                group_order.append(weir_name)

            numeric_values = []
            for required_name in self._fixed_weir_field_names()[1:]:
                value = feature[field_names[required_name]]
                if value is None:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Feature {feature.id()} is missing '{required_name}' and cannot be exported to .pliz",
                    )
                    return
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Feature {feature.id()} has a non-numeric '{required_name}' value and cannot be exported to .pliz",
                    )
                    return
                if not math.isfinite(numeric_value):
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Feature {feature.id()} has a non-finite '{required_name}' value and cannot be exported to .pliz",
                    )
                    return
                numeric_values.append(numeric_value)

            for point in points:
                grouped_rows[weir_name].append((point, numeric_values))
                exported_count += 1

        if exported_count == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid fixed-weir point features were exported",
            )
            return

        with open(output_path, "w", encoding="utf-8") as handle:
            for weir_name in group_order:
                rows = grouped_rows[weir_name]
                handle.write(f"{self._normalize_fxw_name(weir_name)}\n")
                handle.write(f"{len(rows)} 9\n")
                for point, numeric_values in rows:
                    numeric_text = " ".join(f"{value:.6f}" for value in numeric_values)
                    handle.write(f"{point.x():.6f} {point.y():.6f} {numeric_text}\n")

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Exported {exported_count} fixed-weir point(s) to {os.path.basename(output_path)}",
        )

    def _bridge_point_field_names(self):
        """Return required bridge point-layer fields."""
        return ["bridge_name", "width", "drag_cd"]

    def _is_bridge_point_layer(self, layer):
        """Return True when a point layer has the full bridge schema."""
        return self._resolved_bridge_point_fields(layer) is not None

    def _resolved_bridge_point_fields(self, layer):
        """Resolve required bridge point fields case-insensitively."""
        return self._resolve_required_fields(layer, self._bridge_point_field_names())

    def _selected_bridge_line_layers(self):
        """Return selected vector line layers from the layer tree, if available."""
        selected_layers = []
        try:
            tree_view = self.iface.layerTreeView()
            selected_layers = list(tree_view.selectedLayers())
        except Exception:
            selected_layers = []

        valid_selected = [
            layer
            for layer in selected_layers
            if layer is not None
            and layer.type() == QgsMapLayerType.VectorLayer
            and layer.geometryType() == QgsWkbTypes.LineGeometry
        ]
        return valid_selected

    def _find_point_layer_by_name(self, layer_name):
        """Find a point layer by exact layer name."""
        for layer in QgsProject.instance().mapLayers().values():
            try:
                if layer.type() != QgsMapLayerType.VectorLayer:
                    continue
                if layer.geometryType() != QgsWkbTypes.PointGeometry:
                    continue
            except (AttributeError, RuntimeError):
                continue
            if layer.name() == layer_name:
                return layer
        return None

    def _line_layer_has_bridge_companion(self, line_layer):
        """Return True if a line layer has a valid companion bridge points layer."""
        if line_layer is None:
            return False
        point_layer = self._find_point_layer_by_name(f"{line_layer.name()}_points")
        if point_layer is None:
            return False
        return self._resolved_bridge_point_fields(point_layer) is not None

    def export_bridge_pliz_from_selected_layers(self, selected_line_layers=None):
        """Export selected bridge line layers into one combined bridge .pliz file."""
        selected_line_layers = list(selected_line_layers or self._selected_bridge_line_layers())
        if not selected_line_layers:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Select one or more line layers in the layer tree to export bridge .pliz.",
            )
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save Bridge PLIZ file",
            "",
            "Bridge files (*.pliz);;All files (*)",
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".pliz"):
            output_path = output_path + ".pliz"

        blocks = []

        for line_layer in selected_line_layers:
            point_layer_name = f"{line_layer.name()}_points"
            point_layer = self._find_point_layer_by_name(point_layer_name)
            if point_layer is None:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Missing companion point layer '{point_layer_name}' for line layer '{line_layer.name()}'.",
                )
                return

            point_fields = self._resolved_bridge_point_fields(point_layer)
            if point_fields is None:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Point layer '{point_layer_name}' must contain bridge_name, width, and drag_cd fields.",
                )
                return

            grouped_point_rows = {}
            grouped_order = {}
            for point_feature in point_layer.getFeatures():
                geometry = point_feature.geometry()
                if not geometry or geometry.isEmpty():
                    continue
                points = self._extract_points(geometry)
                if not points:
                    continue

                bridge_name = point_feature[point_fields["bridge_name"]]
                if bridge_name is None or not str(bridge_name).strip():
                    continue
                bridge_name = str(bridge_name).strip()
                if bridge_name not in grouped_point_rows:
                    grouped_point_rows[bridge_name] = []
                    grouped_order[bridge_name] = len(grouped_order)

                width_value = point_feature[point_fields["width"]]
                drag_value = point_feature[point_fields["drag_cd"]]
                try:
                    width = float(width_value)
                    drag_cd = float(drag_value)
                except (TypeError, ValueError):
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Point layer '{point_layer_name}' has non-numeric width/drag_cd for bridge '{bridge_name}'.",
                    )
                    return
                if not math.isfinite(width) or not math.isfinite(drag_cd):
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Point layer '{point_layer_name}' has non-finite width/drag_cd for bridge '{bridge_name}'.",
                    )
                    return

                for point in points:
                    grouped_point_rows[bridge_name].append((float(point.x()), float(point.y()), width, drag_cd))

            name_field = self._get_name_field(line_layer)
            for line_feature in line_layer.getFeatures():
                geometry = line_feature.geometry()
                if not geometry or geometry.isEmpty():
                    continue

                polylines = self._extract_polylines(geometry)
                if not polylines:
                    continue

                base_name = self._feature_name(line_feature, name_field)
                for part_idx, polyline in enumerate(polylines):
                    if len(polyline) < 2:
                        continue
                    bridge_name = base_name if len(polylines) == 1 else f"{base_name}_{part_idx + 1}"

                    point_rows = grouped_point_rows.get(bridge_name)
                    if point_rows is None:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"No bridge points found for '{bridge_name}' in layer '{point_layer_name}'.",
                        )
                        return

                    if len(point_rows) != len(polyline):
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"Bridge '{bridge_name}' has {len(polyline)} vertices but {len(point_rows)} point rows in '{point_layer_name}'.",
                        )
                        return

                    blocks.append((bridge_name, point_rows, grouped_order.get(bridge_name, 0)))

        if not blocks:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid bridge features were exported.",
            )
            return

        with open(output_path, "w", encoding="utf-8") as handle:
            for bridge_name, rows, _ in blocks:
                handle.write(f"{bridge_name}\n")
                handle.write(f"{len(rows)} 4\n")
                for x_coord, y_coord, width, drag_cd in rows:
                    handle.write(f"{x_coord:.6f} {y_coord:.6f} {width:.6f} {drag_cd:.6f}\n")

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Exported {len(blocks)} bridge block(s) to {os.path.basename(output_path)}",
        )

    def export_point_cloud_xyn(self):
        """Export active point layer to ASCII .xyn format (x y name)."""
        layer = self.iface.activeLayer()
        if not layer or layer.type() != QgsMapLayerType.VectorLayer:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Please select a vector point layer first",
            )
            return

        if layer.geometryType() != QgsWkbTypes.PointGeometry:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "Active layer must contain point geometries",
            )
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save XYN file",
            "",
            "XYN files (*.xyn);;All files (*)",
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".xyn"):
            output_path = output_path + ".xyn"

        name_field = self._get_name_field(layer)
        exported_count = 0
        generated_name_count = 1

        with open(output_path, "w", encoding="ascii") as handle:
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if not geometry or geometry.isEmpty():
                    continue

                points = self._extract_points(geometry)
                if not points:
                    continue

                feature_name = None
                if name_field:
                    value = feature[name_field]
                    if value is not None:
                        text = str(value).strip()
                        if text:
                            feature_name = text

                for point in points:
                    if feature_name:
                        point_name = feature_name
                        try:
                            point_name.encode("ascii")
                        except UnicodeEncodeError:
                            point_name = f"obs_{generated_name_count}"
                            generated_name_count += 1
                    else:
                        point_name = f"obs_{generated_name_count}"
                        generated_name_count += 1

                    handle.write(f"{point.x():.6f} {point.y():.6f} {point_name}\n")
                    exported_count += 1

        if exported_count == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid point features were exported",
            )
            return

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Exported {exported_count} point feature(s) to {os.path.basename(output_path)}",
        )

    def _get_name_field(self, layer):
        """Find a likely name field to use in export blocks."""
        field_names = [field.name() for field in layer.fields()]
        preferred = ["weir_name", "name", "naam", "id"]
        for candidate in preferred:
            for existing in field_names:
                if existing.lower() == candidate:
                    return existing
        return field_names[0] if field_names else None

    def _feature_name(self, feature, name_field):
        """Resolve export block name from attribute or fallback id."""
        if name_field:
            value = feature[name_field]
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return f"feature_{feature.id()}"

    def _extract_polylines(self, geometry):
        """Return a list of QgsPoint sequences for single/multi line geometries."""
        if geometry.isMultipart():
            return geometry.asMultiPolyline()
        line = geometry.asPolyline()
        return [line] if line else []

    def _extract_points(self, geometry):
        """Return a list of QgsPoint for single/multi point geometries."""
        if geometry.isMultipart():
            return geometry.asMultiPoint()
        point = geometry.asPoint()
        return [point] if point is not None else []

    def _fixed_weir_field_names(self):
        """Return the required fixed-weir point field names in export order."""
        return [
            "weir_name",
            "crest_lvl",
            "sill_hL",
            "sill_hR",
            "crest_w",
            "slope_L",
            "slope_R",
            "rough_cd",
        ]

    def _is_fixed_weir_point_layer(self, layer):
        """Return True when a point layer has the full fixed-weir schema."""
        return self._resolved_fixed_weir_fields(layer) is not None

    def _resolved_fixed_weir_fields(self, layer):
        """Return actual field names for the fixed-weir schema, resolved case-insensitively."""
        return self._resolve_required_fields(layer, self._fixed_weir_field_names())

    def _resolve_required_fields(self, layer, required_fields):
        """Resolve required field names from a layer case-insensitively."""
        field_lookup = {field.name().lower(): field.name() for field in layer.fields()}
        resolved = {}
        for field_name in required_fields:
            actual_name = field_lookup.get(field_name.lower())
            if actual_name is None:
                return None
            resolved[field_name] = actual_name
        return resolved

    def _normalize_fxw_name(self, name):
        """Ensure exported fixed-weir block names remain compatible with the importer."""
        name = str(name).strip()
        return name if name.endswith(":") else f"{name}:"

    def _collect_polyline_vertices_with_names(self, line_layer):
        """Return vertex list tuples (name, x, y) from a line layer."""
        layer_name = str(line_layer.name() or "").strip() or "layer"
        collected_polylines = []

        for feature in line_layer.getFeatures():
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue

            polylines = self._extract_polylines(geometry)
            if not polylines:
                continue

            for polyline in polylines:
                if not polyline:
                    continue
                collected_polylines.append(polyline)

        rows = []

        use_suffix = len(collected_polylines) > 1
        for polyline_index, polyline in enumerate(collected_polylines, start=1):
            row_name = f"{layer_name}_{polyline_index}" if use_suffix else layer_name
            for point in polyline:
                rows.append((row_name, float(point.x()), float(point.y())))

        return rows

    def _create_point_layer_from_polyline_vertices(self, line_layer, output_name, output_fields, prompt_values, success_label):
        """Create a point layer by copying line vertices and appending default prompted values."""
        crs_authid = "EPSG:28992"
        try:
            layer_crs = line_layer.crs()
            if layer_crs is not None and layer_crs.isValid():
                authid = layer_crs.authid()
                if authid:
                    crs_authid = authid
        except (AttributeError, RuntimeError):
            pass

        point_layer = QgsVectorLayer(f"Point?crs={crs_authid}", output_name, "memory")
        provider = point_layer.dataProvider()
        provider.addAttributes(output_fields)
        point_layer.updateFields()

        features = []
        for base_name, x_coord, y_coord in self._collect_polyline_vertices_with_names(line_layer):
            feat = QgsFeature(point_layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x_coord, y_coord)))
            feat.setAttributes([base_name] + [float(value) for value in prompt_values])
            features.append(feat)

        if not features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid vertices were found in the active polyline layer.",
            )
            return

        provider.addFeatures(features)
        point_layer.updateExtents()
        QgsProject.instance().addMapLayer(point_layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Created {success_label} layer '{output_name}' with {len(features)} point(s)",
        )

    def _set_status_message(self, message):
        """Show an import status message when a QGIS status bar is available."""
        try:
            self.iface.statusBarIface().showMessage(str(message))
            QApplication.processEvents()
        except (AttributeError, RuntimeError):
            # Keep import flow resilient in test/mocked environments.
            pass

    def _clear_status_message(self):
        """Clear status message when supported by the QGIS interface."""
        try:
            self.iface.statusBarIface().clearMessage()
            QApplication.processEvents()
        except (AttributeError, RuntimeError):
            pass

    def _create_progress_dialog(self, title):
        """Create and show a progress dialog for long-running netCDF imports."""
        self._close_orphan_loading_progress_dialogs()
        self._close_progress_dialog(self._active_progress_dialog)

        # QGIS 4 / Qt6 can keep native/MDAL "Initializing..." windows alive.
        # Use status-bar progress only to avoid sticky popup regressions.
        if _is_qt6_runtime():
            self._active_progress_dialog = None
            return None

        try:
            dialog = QProgressDialog("Initializing...", None, 0, 100, self.iface.mainWindow())
            dialog.setObjectName(_IMPORT_PROGRESS_DIALOG_OBJECT_NAME)
            dialog.setWindowTitle(title)
            dialog.setAutoClose(True)
            dialog.setAutoReset(False)
            dialog.setMinimumDuration(0)
            dialog.setWindowModality(Qt.WindowModal)
            dialog.setValue(0)
            dialog.show()
            self._active_progress_dialog = dialog
            QApplication.processEvents()
            return dialog
        except Exception:
            self._active_progress_dialog = None
            return None

    def _schedule_orphan_progress_cleanup(self, delays_ms=None):
        """Schedule deferred orphan cleanup sweeps for late-spawned dialogs."""
        delays = list(delays_ms) if delays_ms is not None else [180]
        for delay_ms in delays:
            try:
                QTimer.singleShot(delay_ms, self._close_orphan_loading_progress_dialogs)
            except (RuntimeError, AttributeError):
                pass

    def _update_progress_dialog(self, dialog, value, text=None):
        """Update progress dialog value and optional label text."""
        if dialog is None:
            return
        try:
            dialog.setValue(max(0, min(100, int(value))))
            if text:
                dialog.setLabelText(str(text))
            QApplication.processEvents()
        except (RuntimeError, AttributeError):
            pass

    def _close_progress_dialog(self, dialog):
        """Close the import progress dialog when available."""
        if dialog is None:
            return
        # Make shutdown robust across Qt5/Qt6: one failing call should not
        # prevent the remaining cleanup steps from executing.
        for action in (
            lambda: dialog.setValue(100),
            lambda: dialog.reset(),
            lambda: dialog.hide(),
            lambda: dialog.close(),
            lambda: dialog.deleteLater(),
        ):
            try:
                action()
            except (RuntimeError, AttributeError):
                pass

        if dialog is self._active_progress_dialog:
            self._active_progress_dialog = None

        self._close_orphan_loading_progress_dialogs()

        try:
            QApplication.processEvents()
        except RuntimeError:
            pass

    def _close_orphan_loading_progress_dialogs(self):
        """Best-effort cleanup of orphan top-level loading dialogs.

        In some QGIS/Qt6 runs, a progress dialog can outlive the tracked
        reference. Sweep top-level widgets and close matching loading dialogs.
        """
        widgets = []
        try:
            widgets.extend(list(QApplication.topLevelWidgets() or []))
        except (RuntimeError, AttributeError):
            pass
        try:
            widgets.extend(list(QApplication.allWidgets() or []))
        except (RuntimeError, AttributeError):
            pass
        if not widgets:
            return

        try:
            main_window = self.iface.mainWindow()
        except Exception:
            main_window = None

        seen = set()
        for widget in widgets:
            try:
                wid = id(widget)
                if wid in seen:
                    continue
                seen.add(wid)

                object_name = ""
                try:
                    object_name = str(widget.objectName() or "")
                except Exception:
                    object_name = ""

                title = str(widget.windowTitle() or "")
                label_text = ""
                try:
                    label_text = str(widget.labelText() or "")
                except Exception:
                    label_text = ""

                has_progress_methods = all(
                    callable(getattr(widget, method_name, None))
                    for method_name in ("setValue", "reset", "close")
                )

                parent_widget = None
                try:
                    parent_widget = widget.parentWidget()
                except Exception:
                    parent_widget = None

                window_modality = None
                try:
                    window_modality = widget.windowModality()
                except Exception:
                    window_modality = None

                qt_window_modal = getattr(Qt, "WindowModal", None)
                qt_app_modal = getattr(Qt, "ApplicationModal", None)
                is_modal_progress = window_modality in (qt_window_modal, qt_app_modal)

                is_marked_dialog = object_name == _IMPORT_PROGRESS_DIALOG_OBJECT_NAME
                title_loading = title.strip().lower().startswith("loading")
                label_loading = label_text.strip().lower().startswith("initializing") or label_text.strip().lower().startswith("loading")
                label_import = "import" in label_text.strip().lower()

                if main_window is not None and not is_marked_dialog and parent_widget is not None and parent_widget is not main_window:
                    continue

                if not is_marked_dialog and not title_loading and not label_loading and not label_import:
                    if main_window is None or not has_progress_methods:
                        continue

                    if parent_widget is not main_window and not (parent_widget is None and is_modal_progress):
                        continue

                try:
                    widget.reset()
                except (RuntimeError, AttributeError):
                    pass

                for action in (
                    lambda: widget.setValue(100),
                    lambda: widget.hide(),
                    lambda: widget.close(),
                    lambda: widget.deleteLater(),
                ):
                    try:
                        action()
                    except (RuntimeError, AttributeError):
                        pass
            except (RuntimeError, AttributeError):
                continue

        try:
            QApplication.processEvents()
        except RuntimeError:
            pass

    def load_netcdf_file(self, filepath):
        """Route NetCDF files to HIS importer or existing UGRID mesh importer."""
        try:
            if self._is_his_netcdf_file(filepath):
                self.load_fm_his_file(filepath)
                return
        except ModuleNotFoundError:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS.",
            )
            return
        except Exception as exc:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                f"HIS detection failed, trying UGRID mesh import: {exc}",
            )

        self.load_ugrid_mesh_file(filepath)

    def _is_his_netcdf_file(self, filepath):
        """Return True when file appears to be a Delft3D FM HIS NetCDF output."""
        import netCDF4 as nc

        with nc.Dataset(filepath, "r") as ds:
            schema = self._resolve_his_schema(ds)
            if schema is None:
                return False

            # HIS detection must rely on observation schema, not generic global
            # time-series variables that are also present in regular map outputs.
            has_station_schema = any(
                [
                    schema.get("station_dim"),
                    schema.get("station_name_var"),
                    schema.get("station_x_var"),
                    schema.get("station_y_var"),
                    schema.get("station_geom_count_var"),
                ]
            )
            has_cross_section_schema = any(
                [
                    schema.get("cross_section_dim"),
                    schema.get("cross_name_var"),
                    schema.get("cross_geom_count_var"),
                ]
            )
            has_obs_schema = has_station_schema or has_cross_section_schema
            has_obs_entities = schema["station_count"] > 0 or schema["cross_section_count"] > 0
            return bool(has_obs_schema and has_obs_entities)

    def _resolve_his_schema(self, nc_dataset):
        """Resolve Delft3D FM HIS variable/dimension names into one schema map."""
        time_var = self._find_variable_name(nc_dataset, "time")
        if time_var is None:
            return None

        time_dimensions = tuple(getattr(nc_dataset.variables[time_var], "dimensions", ()))
        if not time_dimensions:
            return None
        time_dim = time_dimensions[0]

        if "station" in nc_dataset.dimensions:
            station_dim = "station"
        else:
            station_dim = None

        if "cross_section" in nc_dataset.dimensions:
            cross_section_dim = "cross_section"
        else:
            cross_section_dim = None

        station_name_var = self._find_variable_name(nc_dataset, "station_name")
        station_id_var = self._find_variable_name(nc_dataset, "station_id")
        station_x_var = self._find_variable_name(nc_dataset, "station_x_coordinate")
        station_y_var = self._find_variable_name(nc_dataset, "station_y_coordinate")
        station_geom_count_var = self._find_variable_name(nc_dataset, "station_geom_node_count")
        station_geom_x_var = self._find_variable_name(nc_dataset, "station_geom_node_coordx")
        station_geom_y_var = self._find_variable_name(nc_dataset, "station_geom_node_coordy")

        cross_name_var = self._find_variable_name(nc_dataset, "cross_section_name")
        cross_geom_count_var = self._find_variable_name(nc_dataset, "cross_section_geom_node_count")
        cross_geom_x_var = self._find_variable_name(nc_dataset, "cross_section_geom_node_coordx")
        cross_geom_y_var = self._find_variable_name(nc_dataset, "cross_section_geom_node_coordy")

        station_count = int(len(nc_dataset.dimensions[station_dim])) if station_dim in nc_dataset.dimensions else 0
        cross_section_count = int(len(nc_dataset.dimensions[cross_section_dim])) if cross_section_dim in nc_dataset.dimensions else 0

        station_variables = self._build_his_variable_catalog(nc_dataset, time_dim, station_dim)
        cross_section_variables = self._build_his_variable_catalog(nc_dataset, time_dim, cross_section_dim)
        global_variables = self._build_his_variable_catalog(nc_dataset, time_dim, None)

        return {
            "time_var": time_var,
            "time_dim": time_dim,
            "time_name": time_var,
            "time_units": getattr(nc_dataset.variables[time_var], "units", ""),
            "station_dim": station_dim,
            "station_count": station_count,
            "station_name_var": station_name_var,
            "station_id_var": station_id_var,
            "station_x_var": station_x_var,
            "station_y_var": station_y_var,
            "station_geom_count_var": station_geom_count_var,
            "station_geom_x_var": station_geom_x_var,
            "station_geom_y_var": station_geom_y_var,
            "cross_section_dim": cross_section_dim,
            "cross_section_count": cross_section_count,
            "cross_name_var": cross_name_var,
            "cross_geom_count_var": cross_geom_count_var,
            "cross_geom_x_var": cross_geom_x_var,
            "cross_geom_y_var": cross_geom_y_var,
            "station_variables": station_variables,
            "cross_section_variables": cross_section_variables,
            "global_variables": global_variables,
        }

    def _build_his_variable_catalog(self, nc_dataset, time_dim, obs_dim):
        """Build variable metadata list for one HIS scope."""
        catalog = []
        excluded_names = {
            "time",
            "time_bds",
            "projected_coordinate_system",
            "station_name",
            "station_id",
            "station_x_coordinate",
            "station_y_coordinate",
            "station_geom",
            "station_geom_node_count",
            "station_geom_node_coordx",
            "station_geom_node_coordy",
            "cross_section_name",
            "cross_section_geom",
            "cross_section_geom_node_count",
            "cross_section_geom_node_coordx",
            "cross_section_geom_node_coordy",
        }

        for name, variable in nc_dataset.variables.items():
            if name.lower() in excluded_names:
                continue
            if not self._is_numeric_netcdf_variable(variable):
                continue

            dims = tuple(getattr(variable, "dimensions", ()))
            if time_dim not in dims:
                continue

            if obs_dim is None:
                if dims != (time_dim,):
                    continue
            else:
                if obs_dim not in dims or len(dims) != 2:
                    continue

            unit_text = str(getattr(variable, "units", "") or "").strip()
            long_name = str(getattr(variable, "long_name", "") or "").strip()
            label = long_name or name
            if unit_text:
                label = f"{label} [{unit_text}]"
            if label != name:
                label = f"{name} | {label}"

            catalog.append(
                {
                    "name": name,
                    "label": label,
                    "long_name": long_name,
                    "units": unit_text,
                    "dimensions": dims,
                }
            )

        return sorted(catalog, key=lambda entry: entry["name"].lower())

    def _to_numpy_float_array(self, value):
        """Return value as a finite-compatible float numpy array."""
        import numpy as np

        if value is None:
            return None

        if isinstance(value, np.ma.MaskedArray):
            value = value.filled(np.nan)
        return np.asarray(value, dtype=float)

    def _his_geometry_centroids(self, counts_array, x_array, y_array, item_count):
        """Return centroid coordinates for geometry-node encoded HIS entities."""
        import numpy as np

        centroids = [(math.nan, math.nan)] * item_count
        if counts_array is None or x_array is None or y_array is None:
            return centroids

        counts = np.asarray(counts_array, dtype=int)
        xs = np.asarray(x_array, dtype=float)
        ys = np.asarray(y_array, dtype=float)

        offset = 0
        for idx in range(min(item_count, len(counts))):
            node_count = int(counts[idx])
            if node_count <= 0:
                continue
            end_idx = offset + node_count
            if end_idx > len(xs) or end_idx > len(ys):
                break

            segment_x = xs[offset:end_idx]
            segment_y = ys[offset:end_idx]
            offset = end_idx

            finite = np.isfinite(segment_x) & np.isfinite(segment_y)
            if not finite.any():
                continue

            centroids[idx] = (
                float(np.mean(segment_x[finite])),
                float(np.mean(segment_y[finite])),
            )

        return centroids

    def _his_geometry_lines(self, counts_array, x_array, y_array, item_count):
        """Return per-item line coordinate sequences from HIS geometry-node arrays."""
        import numpy as np

        lines = [[] for _ in range(item_count)]
        if counts_array is None or x_array is None or y_array is None:
            return lines

        counts = np.asarray(counts_array, dtype=int)
        xs = np.asarray(x_array, dtype=float)
        ys = np.asarray(y_array, dtype=float)

        offset = 0
        for idx in range(min(item_count, len(counts))):
            node_count = int(counts[idx])
            if node_count <= 0:
                continue
            end_idx = offset + node_count
            if end_idx > len(xs) or end_idx > len(ys):
                break

            segment_x = xs[offset:end_idx]
            segment_y = ys[offset:end_idx]
            offset = end_idx

            points = []
            for x_coord, y_coord in zip(segment_x, segment_y):
                if not (math.isfinite(float(x_coord)) and math.isfinite(float(y_coord))):
                    continue
                points.append((float(x_coord), float(y_coord)))

            lines[idx] = points

        return lines

    def _his_station_rows(self, nc_dataset, schema):
        """Build station row dictionaries with index/name/coordinates."""
        station_count = int(schema.get("station_count") or 0)
        if station_count <= 0:
            return []

        names = self._read_string_array(nc_dataset, schema.get("station_name_var"))
        ids = self._read_string_array(nc_dataset, schema.get("station_id_var"))
        if not names:
            names = ids

        x_values = None
        y_values = None
        x_var = schema.get("station_x_var")
        y_var = schema.get("station_y_var")
        if x_var and y_var and x_var in nc_dataset.variables and y_var in nc_dataset.variables:
            x_values = self._to_numpy_float_array(nc_dataset.variables[x_var][:])
            y_values = self._to_numpy_float_array(nc_dataset.variables[y_var][:])

        if x_values is None or y_values is None:
            count_var = schema.get("station_geom_count_var")
            geom_x_var = schema.get("station_geom_x_var")
            geom_y_var = schema.get("station_geom_y_var")
            geom_counts = (
                self._to_numpy_float_array(nc_dataset.variables[count_var][:])
                if count_var and count_var in nc_dataset.variables
                else None
            )
            geom_x = (
                self._to_numpy_float_array(nc_dataset.variables[geom_x_var][:])
                if geom_x_var and geom_x_var in nc_dataset.variables
                else None
            )
            geom_y = (
                self._to_numpy_float_array(nc_dataset.variables[geom_y_var][:])
                if geom_y_var and geom_y_var in nc_dataset.variables
                else None
            )
            centroids = self._his_geometry_centroids(geom_counts, geom_x, geom_y, station_count)
            x_values = [value[0] for value in centroids]
            y_values = [value[1] for value in centroids]

        rows = []
        for idx in range(station_count):
            x_coord = float(x_values[idx]) if idx < len(x_values) else math.nan
            y_coord = float(y_values[idx]) if idx < len(y_values) else math.nan
            if not (math.isfinite(x_coord) and math.isfinite(y_coord)):
                continue

            obs_name = ""
            if names and idx < len(names):
                obs_name = str(names[idx] or "").strip()
            if not obs_name:
                obs_name = f"station_{idx + 1}"

            obs_id = ""
            if ids and idx < len(ids):
                obs_id = str(ids[idx] or "").strip()

            rows.append(
                {
                    "obs_index": idx,
                    "obs_name": obs_name,
                    "obs_id": obs_id,
                    "x": x_coord,
                    "y": y_coord,
                }
            )

        return rows

    def _his_cross_section_rows(self, nc_dataset, schema):
        """Build cross-section row dictionaries with index/name/line coordinates."""
        cross_count = int(schema.get("cross_section_count") or 0)
        if cross_count <= 0:
            return []

        names = self._read_string_array(nc_dataset, schema.get("cross_name_var"))
        count_var = schema.get("cross_geom_count_var")
        geom_x_var = schema.get("cross_geom_x_var")
        geom_y_var = schema.get("cross_geom_y_var")

        geom_counts = (
            self._to_numpy_float_array(nc_dataset.variables[count_var][:])
            if count_var and count_var in nc_dataset.variables
            else None
        )
        geom_x = (
            self._to_numpy_float_array(nc_dataset.variables[geom_x_var][:])
            if geom_x_var and geom_x_var in nc_dataset.variables
            else None
        )
        geom_y = (
            self._to_numpy_float_array(nc_dataset.variables[geom_y_var][:])
            if geom_y_var and geom_y_var in nc_dataset.variables
            else None
        )

        line_points_by_index = self._his_geometry_lines(geom_counts, geom_x, geom_y, cross_count)

        rows = []
        for idx in range(cross_count):
            line_points = line_points_by_index[idx] if idx < len(line_points_by_index) else []
            if len(line_points) < 2:
                continue

            obs_name = ""
            if names and idx < len(names):
                obs_name = str(names[idx] or "").strip()
            if not obs_name:
                obs_name = f"cross_section_{idx + 1}"

            rows.append(
                {
                    "obs_index": idx,
                    "obs_name": obs_name,
                    "obs_id": "",
                    "line_points": line_points,
                }
            )

        return rows

    def _create_his_observation_layer(self, layer_name, rows, epsg, source_path, obs_type, geometry_kind="point"):
        """Create one HIS observation layer from prepared rows."""
        geometry_kind = str(geometry_kind or "point").strip().lower()
        if geometry_kind == "line":
            uri = f"LineString?crs=EPSG:{epsg}"
        else:
            uri = f"Point?crs=EPSG:{epsg}"

        layer = QgsVectorLayer(uri, layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("his_source", QVariant.String),
                QgsField("obs_type", QVariant.String),
                QgsField("obs_index", QVariant.Int),
                QgsField("obs_name", QVariant.String),
                QgsField("obs_id", QVariant.String),
            ]
        )
        layer.updateFields()

        features = []
        for row in rows:
            feat = QgsFeature(layer.fields())
            if geometry_kind == "line":
                line_points = row.get("line_points") or []
                if len(line_points) < 2:
                    continue
                geometry_points = [QgsPointXY(float(x_coord), float(y_coord)) for x_coord, y_coord in line_points]
                feat.setGeometry(QgsGeometry.fromPolylineXY(geometry_points))
            else:
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(row["x"]), float(row["y"]))))
            feat.setAttributes(
                [
                    str(source_path),
                    str(obs_type),
                    int(row["obs_index"]),
                    str(row["obs_name"]),
                    str(row.get("obs_id", "") or ""),
                ]
            )
            features.append(feat)

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def load_fm_his_file(self, filepath):
        """Load Delft3D FM HIS NetCDF by creating lightweight observation layers only."""
        try:
            import netCDF4 as nc
        except ModuleNotFoundError:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS.",
            )
            return

        base_name = os.path.splitext(os.path.basename(filepath))[0]
        source_path = os.path.abspath(filepath)

        progress_dialog = self._create_progress_dialog(f"Loading HIS {base_name}")
        try:
            self._update_progress_dialog(progress_dialog, 10, "Opening HIS netCDF")
            self._set_status_message(f"Loading HIS file {os.path.basename(source_path)}")

            with nc.Dataset(source_path, "r") as ds:
                schema = self._resolve_his_schema(ds)
                if schema is None:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"Could not detect HIS schema in {os.path.basename(source_path)}",
                    )
                    return

                epsg = self._read_epsg_from_nc(ds)
                if epsg is None:
                    epsg = 28992

                self._update_progress_dialog(progress_dialog, 35, "Reading station metadata")
                station_rows = self._his_station_rows(ds, schema)

                self._update_progress_dialog(progress_dialog, 60, "Reading cross-section metadata")
                cross_rows = self._his_cross_section_rows(ds, schema)

            self._update_progress_dialog(progress_dialog, 75, "Creating HIS layers")

            loaded_layers = []
            if station_rows:
                stations_layer_name = f"{base_name}_his_stations"
                self._create_his_observation_layer(
                    stations_layer_name,
                    station_rows,
                    epsg,
                    source_path,
                    obs_type="station",
                )
                loaded_layers.append(f"stations({len(station_rows)})")

            if cross_rows:
                cross_layer_name = f"{base_name}_his_cross_sections"
                self._create_his_observation_layer(
                    cross_layer_name,
                    cross_rows,
                    epsg,
                    source_path,
                    obs_type="cross_section",
                    geometry_kind="line",
                )
                loaded_layers.append(f"cross_sections({len(cross_rows)})")

            self._his_sources[source_path] = {
                "path": source_path,
                "base_name": base_name,
                "epsg": epsg,
                "time_var": schema["time_var"],
                "time_dim": schema["time_dim"],
                "time_name": schema["time_name"],
                "time_units": schema["time_units"],
                "station_dim": schema["station_dim"],
                "cross_section_dim": schema["cross_section_dim"],
                "station_variables": schema["station_variables"],
                "cross_section_variables": schema["cross_section_variables"],
                "global_variables": schema["global_variables"],
            }

            stale_cache_keys = [
                key for key in self._his_series_cache.keys() if key and key[0] == source_path
            ]
            for cache_key in stale_cache_keys:
                self._his_series_cache.pop(cache_key, None)

            self._refresh_his_dialog_state(keep_current=True)

            if loaded_layers:
                self._update_progress_dialog(progress_dialog, 100, "HIS import complete")
                self.iface.messageBar().pushSuccess(
                    "Delft3D File Manager",
                    f"Loaded HIS observations from {os.path.basename(source_path)}: {', '.join(loaded_layers)}",
                )
            else:
                self.iface.messageBar().pushWarning(
                    "Delft3D File Manager",
                    f"No station or cross-section locations found in {os.path.basename(source_path)}",
                )
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not import HIS file: {exc}",
            )
        finally:
            self._close_progress_dialog(progress_dialog)
            self._clear_status_message()
            self._schedule_orphan_progress_cleanup([180])

    def load_ugrid_mesh_file(self, filepath):
        """Load UGRID netCDF mesh file with 1D/2D components."""
        try:
            import netCDF4 as nc
        except ModuleNotFoundError:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS."
            )
            return

        base_name = os.path.splitext(os.path.basename(filepath))[0]
        loaded_layers = []
        mesh2d_source_path = filepath
        flattened_sidecar_path = None  # Track sidecar separately for both-file loading
        partition_input_files = [filepath]
        partition_mode = False
        partition_render_mode = "masked"
        progress_dialog = self._create_progress_dialog(f"Loading {base_name}")
        try:
            try:
                self._update_progress_dialog(progress_dialog, 5, "Opening netCDF file")
                self._set_status_message(f"Loading {os.path.basename(filepath)}")
                with nc.Dataset(filepath, 'r') as ds:
                    # Read CRS
                    self._update_progress_dialog(progress_dialog, 15, "Reading CRS and topology")
                    self._set_status_message("Reading CRS and topology")
                    epsg = self._read_epsg_from_nc(ds)
                    if epsg is None:
                        epsg = 28992  # Default fallback

                    # Detect components
                    mesh2d_topology_names = self._find_mesh2d_topology_names(ds)
                    has_mesh2d = bool(mesh2d_topology_names)
                    if has_mesh2d:
                        partition_input_files = self._discover_partition_mesh_files(filepath)
                        partition_mode = len(partition_input_files) > 1
                    mesh1d_data = self._read_mesh1d_data(ds) if self._detect_mesh1d_exists(ds) else None
                    geom_data = self._read_geometry_data(ds) if self._detect_geometry_exists(ds) else None
                    self._update_progress_dialog(progress_dialog, 25, "Analyzing netCDF variables")
                    self._set_status_message("Analyzing netCDF variables")
                    variable_analysis = self._analyze_ugrid_data_variables(ds)

                    if not has_mesh2d and mesh1d_data is None and geom_data is None:
                        QMessageBox.warning(
                            self.iface.mainWindow(),
                            "Delft3D File Manager",
                            f"No mesh2d, mesh1d, or geometry components found in {os.path.basename(filepath)}"
                        )
                        return

                    # Prompt for layer names
                    self._update_progress_dialog(progress_dialog, 35, "Preparing layer names")
                    layer_names = self._prompt_for_layer_names(base_name, has_mesh2d, mesh1d_data, geom_data)
                    if layer_names is None:
                        return

            except Exception as exc:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Error loading mesh file: {exc}"
                )
                return

            # ── Prompt phase: collect all choices before any file I/O ────────────
            selected_variables = []
            if has_mesh2d and variable_analysis["has_morphodynamic"]:
                self._update_progress_dialog(progress_dialog, 40, "Select variables to flatten")
                self._set_status_message("Select morphodynamic variables")
                # Only show variables that can be flattened (those with extra dimensions)
                flattenable_vars = variable_analysis.get("flattenable_names", [])
                selected_variables = self._prompt_for_morphodynamic_variables(
                    flattenable_vars,
                    default_selected=flattenable_vars,
                )
                if selected_variables is None:
                    return

            partition_render_mode = None
            if has_mesh2d and partition_mode:
                partition_render_mode = self._prompt_for_partition_render_mode(partition_input_files)
                if partition_render_mode is None:
                    return

            # ── Source-preparation phase: flatten and/or ghost-mask ───────────
            partition_source_paths = None
            if partition_mode:
                self._update_progress_dialog(progress_dialog, 45, "Preparing partition mesh sources")
                self._set_status_message("Preparing partition mesh sources")
                if partition_render_mode == "raw":
                    partition_source_paths = list(partition_input_files)
                    self._set_status_message("Loading original partition files (ghost overlap enabled)")
                else:
                    # masked: flatten each partition then ghost-mask it.
                    partition_warnings = []
                    try:
                        partition_source_paths, partition_warnings = self._prepare_partition_mesh_sources(
                            partition_input_files,
                            selected_variables,
                        )
                    except Exception as exc:
                        partition_source_paths = None
                        partition_warnings.append(f"partition preparation failed: {exc}")

                    if partition_warnings:
                        warning_text = "; ".join(str(item) for item in partition_warnings)
                        self.iface.messageBar().pushWarning(
                            "Delft3D File Manager",
                            f"Partition ownership filtering fallback: {warning_text}",
                        )
            elif selected_variables:
                # Single file with morphodynamic variables: flatten now.
                self._update_progress_dialog(progress_dialog, 45, "Flattening selected variables")
                self._set_status_message("Flattening selected variables")
                progress_step = max(1, len(selected_variables) // 20)

                def _flatten_progress(done, total, label=None):
                    if total <= 0:
                        return
                    fraction = min(1.0, max(0.0, float(done) / float(total)))
                    self._update_progress_dialog(
                        progress_dialog,
                        45 + int(20 * fraction),
                        f"Flattening variables {done}/{total}",
                    )
                    if done < total and (done % progress_step) != 0:
                        return
                    suffix = f": {label}" if label else ""
                    self._set_status_message(f"Flattening variables {done}/{total}{suffix}")

                try:
                    flattened_sidecar_path = self._prepare_flattened_ugrid_sidecar(
                        filepath,
                        selected_variables,
                        progress_callback=_flatten_progress,
                    )
                except Exception as exc:
                    self.iface.messageBar().pushWarning(
                        "Delft3D File Manager",
                        f"Could not flatten morphodynamic variables, loading original mesh: {exc}",
                    )
            else:
                self._update_progress_dialog(progress_dialog, 65, "Loading mesh layers")

            # Load mesh2d
            if has_mesh2d:
                try:
                    self._update_progress_dialog(progress_dialog, 75, "Loading mesh2d layer")
                    self._set_status_message("Loading mesh2d layer")
                    if flattened_sidecar_path:
                        # Load both original and flattened files as separate layer groups
                        if partition_source_paths:
                            if partition_render_mode == "raw":
                                flattened_partition_paths = []
                                n = len(partition_source_paths)
                                for idx, pf in enumerate(partition_source_paths):
                                    self._update_progress_dialog(
                                        progress_dialog,
                                        75 + int(10 * idx / max(n, 1)),
                                        f"Flattening partition {idx + 1}/{n}",
                                    )
                                    try:
                                        flattened_partition_paths.append(
                                            self._prepare_flattened_ugrid_sidecar(pf, selected_variables)
                                        )
                                    except Exception as exc:
                                        self.iface.messageBar().pushWarning(
                                            "Delft3D File Manager",
                                            f"Could not flatten {os.path.basename(pf)}, using original: {exc}",
                                        )
                                        flattened_partition_paths.append(pf)
                            else:
                                flattened_partition_paths = partition_source_paths

                            self._load_partitioned_mesh2d_with_flattened_sidecars(
                                partition_input_files,
                                flattened_partition_paths,
                                base_name,
                                epsg,
                                layer_names["mesh2d"],
                                topology_names=mesh2d_topology_names,
                                expect_data_variables=bool(variable_analysis["candidate_names"]),
                            )
                        else:
                            # Single file with flattening: load both original and sidecar
                            self._load_mesh2d_with_flattened_sidecar(
                                mesh2d_source_path,
                                flattened_sidecar_path,
                                base_name,
                                epsg,
                                layer_names["mesh2d"],
                                topology_names=mesh2d_topology_names,
                                expect_data_variables=bool(variable_analysis["candidate_names"]),
                            )
                    elif partition_source_paths:
                        self._load_partitioned_mesh2d_layers(
                            partition_source_paths,
                            base_name,
                            epsg,
                            layer_names["mesh2d"],
                            topology_names=mesh2d_topology_names,
                            expect_data_variables=bool(variable_analysis["candidate_names"]),
                        )
                    else:
                        self._load_mesh2d_layer(
                            mesh2d_source_path,
                            base_name,
                            epsg,
                            layer_names["mesh2d"],
                            topology_names=mesh2d_topology_names,
                            expect_data_variables=bool(variable_analysis["candidate_names"]),
                        )
                    loaded_layers.append("mesh2d")
                except Exception as exc:
                    self.iface.messageBar().pushWarning(
                        "Delft3D File Manager",
                        f"Could not load mesh2d: {exc}"
                    )

            # Load mesh1d branches
            if mesh1d_data:
                try:
                    self._update_progress_dialog(progress_dialog, 85, "Loading mesh1d branches")
                    self._set_status_message("Loading mesh1d branches")
                    self._load_mesh1d_branches_layer(
                        mesh1d_data["node_x"], mesh1d_data["node_y"],
                        mesh1d_data["edges"], mesh1d_data["edge_branch"],
                        mesh1d_data["branch_names"],
                        epsg, layer_names["mesh1d_branches"]
                    )
                    loaded_layers.append("mesh1d_branches")
                except Exception as exc:
                    self.iface.messageBar().pushWarning(
                        "Delft3D File Manager",
                        f"Could not load mesh1d branches: {exc}"
                    )

            # Load geometry edges
            if geom_data:
                try:
                    self._update_progress_dialog(progress_dialog, 92, "Loading geometry edges")
                    self._set_status_message("Loading geometry edges")
                    self._load_geometry_edges_layer(
                        geom_data["geom_node_x"], geom_data["geom_node_y"],
                        geom_data["geom_node_count"], geom_data["edge_names"],
                        epsg, layer_names["geometry_edges"]
                    )
                    loaded_layers.append("geometry_edges")
                except Exception as exc:
                    self.iface.messageBar().pushWarning(
                        "Delft3D File Manager",
                        f"Could not load geometry edges: {exc}"
                    )

                # Load geometry nodes
                try:
                    self._update_progress_dialog(progress_dialog, 97, "Loading geometry nodes")
                    self._set_status_message("Loading geometry nodes")
                    self._load_geometry_nodes_layer(
                        geom_data["node_x"], geom_data["node_y"],
                        geom_data["node_names"],
                        epsg, layer_names["geometry_nodes"]
                    )
                    loaded_layers.append("geometry_nodes")
                except Exception as exc:
                    self.iface.messageBar().pushWarning(
                        "Delft3D File Manager",
                        f"Could not load geometry nodes: {exc}"
                    )

            if loaded_layers:
                self._update_progress_dialog(progress_dialog, 100, "Import complete")
                self.iface.messageBar().pushSuccess(
                    "Delft3D File Manager",
                    f"Loaded {', '.join(loaded_layers)} from {os.path.basename(filepath)}"
                )
        finally:
            self._close_progress_dialog(progress_dialog)
            self._clear_status_message()
            self._schedule_orphan_progress_cleanup([180])

    def _partition_id_from_filename(self, filepath):
        """Extract a 4-digit partition id from a partitioned netCDF filename."""
        name = os.path.basename(str(filepath))

        explicit = re.search(r"_(\d{4})_(?:map|fou|his|rst)(?:_|\.nc)", name, re.IGNORECASE)
        if explicit:
            return int(explicit.group(1))

        generic = re.search(r"_(\d{4})_", name)
        if generic:
            return int(generic.group(1))
        return None

    def _discover_partition_mesh_files(self, filepath):
        """Discover sibling partition files for a selected partitioned map/fou/his/rst file."""
        abs_path = os.path.abspath(str(filepath))
        dirname = os.path.dirname(abs_path)
        basename = os.path.basename(abs_path)

        match = re.match(r"^(?P<prefix>.*_)(?P<part>\d{4})(?P<suffix>_.*\.nc)$", basename, re.IGNORECASE)
        if not match:
            return [abs_path]

        pattern = os.path.join(dirname, f"{match.group('prefix')}????{match.group('suffix')}")
        siblings = []
        for candidate in sorted(glob.glob(pattern)):
            candidate_base = os.path.basename(candidate)
            if re.match(rf"^{re.escape(match.group('prefix'))}\d{{4}}{re.escape(match.group('suffix'))}$", candidate_base, re.IGNORECASE):
                siblings.append(os.path.abspath(candidate))

        if not siblings:
            return [abs_path]
        return siblings

    def _partition_filtered_path(self, source_path):
        """Return deterministic sidecar path for owner-domain filtered partition datasets."""
        base, ext = os.path.splitext(source_path)
        return f"{base}_qgis_owner{ext}"

    def _prepare_partition_mesh_sources(self, partition_files, selected_variables=None):
        """Prepare source paths per partition, including optional flattening and owner-domain filtering."""
        selected_variables = list(selected_variables or [])
        prepared_paths = []
        warnings = []

        for partition_file in partition_files:
            source_path = partition_file
            if selected_variables:
                source_path = self._prepare_flattened_ugrid_sidecar(source_path, selected_variables)

            filtered_path, status = self._prepare_partition_ghost_sidecar(source_path)
            prepared_paths.append(filtered_path)
            if status != "ok":
                warnings.append(f"{os.path.basename(partition_file)} ({status})")

        return prepared_paths, warnings

    def _prepare_partition_ghost_sidecar(self, source_path):
        """Create or reuse an owner-domain filtered sidecar for one partition source file."""
        import numpy as np
        import netCDF4 as nc

        source_path = os.path.abspath(source_path)
        partition_id = self._partition_id_from_filename(source_path)
        if partition_id is None:
            return source_path, "no partition id in filename"

        sidecar_path = os.path.abspath(self._partition_filtered_path(source_path))
        source_mtime = str(int(os.path.getmtime(source_path)))
        signature = f"v1|partition={partition_id}|source={source_mtime}"

        if os.path.exists(sidecar_path):
            try:
                with nc.Dataset(sidecar_path, "r") as sidecar_ds:
                    if str(getattr(sidecar_ds, "qgis_partition_filter_signature", "")) == signature:
                        return sidecar_path, "ok"
            except (OSError, RuntimeError):
                pass

        with nc.Dataset(source_path, "r") as source_ds:
            domain_var_name = self._find_variable_name(source_ds, "mesh2d_flowelem_domain")
            if not domain_var_name:
                return source_path, "missing mesh2d_flowelem_domain"

            domain_var = source_ds.variables[domain_var_name]
            if len(domain_var.dimensions) < 1:
                return source_path, "invalid mesh2d_flowelem_domain"

            face_dim = domain_var.dimensions[0]
            domain_values = np.asarray(domain_var[:])
            if isinstance(domain_values, np.ma.MaskedArray):
                domain_values = domain_values.filled(-999999)

            face_owner_mask = np.asarray(domain_values).astype(int) == int(partition_id)

            if not face_owner_mask.any():
                return source_path, "no owned faces for partition"

            with nc.Dataset(sidecar_path, "w", format="NETCDF4") as sidecar_ds:
                for attr_name in source_ds.ncattrs():
                    sidecar_ds.setncattr(attr_name, getattr(source_ds, attr_name))

                for dim_name, dim in source_ds.dimensions.items():
                    if dim.isunlimited():
                        sidecar_ds.createDimension(dim_name, None)
                    else:
                        sidecar_ds.createDimension(dim_name, len(dim))

                for var_name, src_var in source_ds.variables.items():
                    fill_value = getattr(src_var, "_FillValue", None)
                    if fill_value is None:
                        out_var = sidecar_ds.createVariable(var_name, src_var.datatype, src_var.dimensions)
                    else:
                        out_var = sidecar_ds.createVariable(
                            var_name,
                            src_var.datatype,
                            src_var.dimensions,
                            fill_value=fill_value,
                        )

                    for attr_name in src_var.ncattrs():
                        if attr_name == "_FillValue":
                            continue
                        out_var.setncattr(attr_name, getattr(src_var, attr_name))

                    data = src_var[:]
                    is_numeric = np.dtype(src_var.dtype).kind in ("i", "u", "f")
                    if face_dim in src_var.dimensions and is_numeric:
                        if isinstance(data, np.ma.MaskedArray):
                            data_arr = data.filled(fill_value if fill_value is not None else np.nan)
                        else:
                            data_arr = np.asarray(data)

                        axis = src_var.dimensions.index(face_dim)
                        reshaped_mask = face_owner_mask.reshape(
                            tuple(face_owner_mask.size if idx == axis else 1 for idx in range(data_arr.ndim))
                        )

                        if fill_value is not None:
                            masked_data = np.where(reshaped_mask, data_arr, fill_value)
                        elif np.dtype(src_var.dtype).kind in ("f",):
                            masked_data = np.where(reshaped_mask, data_arr, np.nan)
                        else:
                            fallback_fill = np.iinfo(src_var.dtype).min if np.dtype(src_var.dtype).kind in ("i", "u") else 0
                            masked_data = np.where(reshaped_mask, data_arr, fallback_fill)

                        out_var[:] = masked_data
                    else:
                        out_var[:] = data

                sidecar_ds.setncattr("qgis_partition_filter_signature", signature)
                sidecar_ds.setncattr("qgis_partition_filter_partition", int(partition_id))
                sidecar_ds.setncattr("qgis_partition_filter_source", source_path)

        return sidecar_path, "ok"

    def _unique_group_name(self, group_name):
        """Return a non-colliding layer-tree group name."""
        from qgis.core import QgsProject

        root = QgsProject.instance().layerTreeRoot()
        if root.findGroup(group_name) is None:
            return group_name

        suffix = 2
        while root.findGroup(f"{group_name}_{suffix}") is not None:
            suffix += 1
        return f"{group_name}_{suffix}"

    def _set_morpho_tag(self, obj, tag):
        """Attach a lightweight morpho tag to a layer or layer-tree node."""
        if obj is None or tag is None:
            return

        try:
            if hasattr(obj, "setCustomProperty"):
                obj.setCustomProperty("delft3d_tag", tag)
        except (RuntimeError, AttributeError):
            pass

    def _load_partitioned_mesh2d_layers_into_group(
        self,
        source_paths,
        target_group,
        base_name,
        epsg,
        layer_name,
        topology_names=None,
        expect_data_variables=False,
        layer_tag=None,
    ):
        """Load partitioned mesh files into an existing layer-tree group."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        root = project.layerTreeRoot()

        loaded_layers = []
        for idx, source_path in enumerate(source_paths, start=1):
            partition_id = self._partition_id_from_filename(source_path)
            if partition_id is None:
                child_name = f"{layer_name}_{layer_tag}_part_{idx:02d}" if layer_tag else f"{layer_name}_part_{idx:02d}"
            else:
                child_name = f"{layer_name}_{layer_tag}_p{partition_id:04d}" if layer_tag else f"{layer_name}_p{partition_id:04d}"

            mesh_layer = self._load_mesh2d_layer(
                source_path,
                base_name,
                epsg,
                child_name,
                topology_names=topology_names,
                expect_data_variables=expect_data_variables,
            )
            self._set_morpho_tag(mesh_layer, layer_tag)
            loaded_layers.append(mesh_layer)

            try:
                node = root.findLayer(mesh_layer.id())
                if node is not None and node.parent() is not None:
                    cloned = node.clone()
                    self._set_morpho_tag(cloned, layer_tag)
                    target_group.addChildNode(cloned)
                    node.parent().removeChildNode(node)
            except (RuntimeError, AttributeError):
                # Keep layer loaded even if moving to group fails.
                pass

        self._setup_partition_mesh_sync(loaded_layers)
        return loaded_layers

    def _load_partitioned_mesh2d_layers(
        self,
        source_paths,
        base_name,
        epsg,
        layer_name,
        topology_names=None,
        expect_data_variables=False,
    ):
        """Load multiple partitioned mesh files and group them as one logical result."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.addGroup(self._unique_group_name(layer_name))
        self._load_partitioned_mesh2d_layers_into_group(
            source_paths,
            group,
            base_name,
            epsg,
            layer_name,
            topology_names=topology_names,
            expect_data_variables=expect_data_variables,
            layer_tag=None,
        )

    def _load_partitioned_mesh2d_with_flattened_sidecars(
        self,
        original_paths,
        flattened_paths,
        base_name,
        epsg,
        layer_name,
        topology_names=None,
        expect_data_variables=False,
    ):
        """Load partitioned regular and flattened files into separate top-level groups."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        root = project.layerTreeRoot()

        regular_group = root.addGroup(self._unique_group_name(f"{layer_name}_regular"))
        morpho_group = root.addGroup(self._unique_group_name(f"{layer_name}_morpho"))
        self._set_morpho_tag(morpho_group, "morpho")

        self._load_partitioned_mesh2d_layers_into_group(
            original_paths,
            regular_group,
            base_name,
            epsg,
            layer_name,
            topology_names=topology_names,
            expect_data_variables=expect_data_variables,
            layer_tag="regular",
        )
        self._load_partitioned_mesh2d_layers_into_group(
            flattened_paths,
            morpho_group,
            base_name,
            epsg,
            layer_name,
            topology_names=topology_names,
            expect_data_variables=expect_data_variables,
            layer_tag="morpho",
        )

    def _load_mesh2d_with_flattened_sidecar(
        self,
        original_path,
        sidecar_path,
        base_name,
        epsg,
        layer_name,
        topology_names=None,
        expect_data_variables=False,
    ):
        """Load original mesh and flattened sidecar as separate layer groups."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        root = project.layerTreeRoot()
        
        # Create main group
        main_group = root.addGroup(self._unique_group_name(layer_name))
        self._set_morpho_tag(main_group, "morpho")
        
        # Load original file in "regular" subgroup
        regular_group = main_group.addGroup("regular")
        self._set_morpho_tag(regular_group, "regular")
        original_layer = self._load_mesh2d_layer(
            original_path,
            base_name,
            epsg,
            f"{layer_name}_regular",
            topology_names=topology_names,
            expect_data_variables=expect_data_variables,
        )
        self._set_morpho_tag(original_layer, "regular")
        
        try:
            node = root.findLayer(original_layer.id())
            if node is not None and node.parent() is not None:
                cloned = node.clone()
                self._set_morpho_tag(cloned, "regular")
                regular_group.addChildNode(cloned)
                node.parent().removeChildNode(node)
        except (RuntimeError, AttributeError):
            pass
        
        # Load sidecar file in "morpho" subgroup
        morpho_group = main_group.addGroup("morpho")
        self._set_morpho_tag(morpho_group, "morpho")
        morpho_layer = self._load_mesh2d_layer(
            sidecar_path,
            base_name,
            epsg,
            f"{layer_name}_morpho",
            topology_names=topology_names,
            expect_data_variables=expect_data_variables,
        )
        self._set_morpho_tag(morpho_layer, "morpho")
        
        try:
            node = root.findLayer(morpho_layer.id())
            if node is not None and node.parent() is not None:
                cloned = node.clone()
                self._set_morpho_tag(cloned, "morpho")
                morpho_group.addChildNode(cloned)
                node.parent().removeChildNode(node)
        except (RuntimeError, AttributeError):
            pass

    def _setup_partition_mesh_sync(self, mesh_layers):
        """Best-effort synchronization of dataset-group and renderer settings across partition layers."""
        if len(mesh_layers) < 2:
            return

        session_key = ",".join(sorted([str(layer.id()) for layer in mesh_layers if layer is not None]))
        session = {"updating": False, "layers": [layer for layer in mesh_layers if layer is not None]}
        self._partition_mesh_sync_sessions[session_key] = session

        def _broadcast(source_layer):
            if session["updating"]:
                return
            session["updating"] = True
            try:
                scalar_group = None
                vector_group = None
                renderer_settings = None

                try:
                    if hasattr(source_layer, "activeScalarDatasetGroup"):
                        scalar_group = source_layer.activeScalarDatasetGroup()
                except Exception:
                    scalar_group = None

                try:
                    if hasattr(source_layer, "activeVectorDatasetGroup"):
                        vector_group = source_layer.activeVectorDatasetGroup()
                except Exception:
                    vector_group = None

                try:
                    if hasattr(source_layer, "rendererSettings"):
                        renderer_settings = source_layer.rendererSettings()
                except Exception:
                    renderer_settings = None

                for target_layer in session["layers"]:
                    if target_layer is source_layer:
                        continue

                    try:
                        if scalar_group is not None and hasattr(target_layer, "setActiveScalarDatasetGroup"):
                            target_layer.setActiveScalarDatasetGroup(int(scalar_group))
                    except (RuntimeError, AttributeError):
                        pass

                    try:
                        if vector_group is not None and hasattr(target_layer, "setActiveVectorDatasetGroup"):
                            target_layer.setActiveVectorDatasetGroup(int(vector_group))
                    except (RuntimeError, AttributeError):
                        pass

                    try:
                        if renderer_settings is not None and hasattr(target_layer, "setRendererSettings"):
                            target_layer.setRendererSettings(renderer_settings)
                            if hasattr(target_layer, "triggerRepaint"):
                                target_layer.triggerRepaint()
                    except (RuntimeError, AttributeError):
                        pass
            finally:
                session["updating"] = False

        for layer in session["layers"]:
            for signal_name in (
                "activeScalarDatasetGroupChanged",
                "activeVectorDatasetGroupChanged",
                "rendererChanged",
            ):
                signal = getattr(layer, signal_name, None)
                if hasattr(signal, "connect"):
                    signal.connect(lambda *args, _layer=layer: _broadcast(_layer))

        _broadcast(session["layers"][0])

    def _prompt_for_layer_names(self, base_name, has_mesh2d, mesh1d_data, geom_data):
        """Prompt user for layer names."""
        layer_names = {}

        # For simplicity, auto-generate names with sensible defaults
        if has_mesh2d:
            layer_names["mesh2d"] = f"{base_name}_mesh2d"

        if mesh1d_data:
            layer_names["mesh1d_branches"] = f"{base_name}_mesh1d_branches"

        if geom_data:
            layer_names["geometry_edges"] = f"{base_name}_geometry_edges"
            layer_names["geometry_nodes"] = f"{base_name}_geometry_nodes"

        return layer_names

    def _prompt_for_partition_render_mode(self, partition_files):
        """Prompt user to choose partition rendering mode.

        Returns:
            "masked" for owner-filtered rendering,
            "raw" for direct partition rendering,
            None if canceled.
        """
        partition_count = len(partition_files or [])
        title = "Partitioned Mesh Import"
        message = (
            f"Detected {partition_count} partition files.\n\n"
            "Choose how to render partitioned results:"
        )

        dialog = QMessageBox(self.iface.mainWindow())
        icon_question = _qmessagebox_icon_question()
        if icon_question is not None:
            dialog.setIcon(icon_question)
        dialog.setWindowTitle(title)
        dialog.setText(message)

        accept_role = _qmessagebox_button_role("AcceptRole")
        action_role = _qmessagebox_button_role("ActionRole")
        reject_role = _qmessagebox_button_role("RejectRole")
        cancel_standard = _qmessagebox_standard_button("Cancel")

        masked_role = accept_role or _qmessagebox_button_role("YesRole") or _qmessagebox_button_role("ActionRole")
        if masked_role is not None:
            masked_button = dialog.addButton(
                "Mask ghost cells (create/reuse *_qgis_owner.nc)",
                masked_role,
            )
        else:
            masked_button = dialog.addButton("Mask ghost cells (create/reuse *_qgis_owner.nc)")

        raw_role = action_role or _qmessagebox_button_role("NoRole") or _qmessagebox_button_role("AcceptRole")
        if raw_role is not None:
            raw_button = dialog.addButton(
                "Load original partition files (show ghost overlap)",
                raw_role,
            )
        else:
            raw_button = dialog.addButton("Load original partition files (show ghost overlap)")

        if cancel_standard is not None:
            cancel_button = dialog.addButton(cancel_standard)
        elif reject_role is not None:
            cancel_button = dialog.addButton("Cancel", reject_role)
        else:
            cancel_button = dialog.addButton("Cancel")
        dialog.setDefaultButton(masked_button)
        _dialog_exec(dialog)

        clicked = dialog.clickedButton()
        if clicked is cancel_button:
            return None
        if clicked is raw_button:
            return "raw"
        return "masked"

    def _detect_mesh2d_exists(self, nc_dataset):
        """Check if mesh2d topology exists in dataset."""
        return bool(self._find_mesh2d_topology_names(nc_dataset))

    def _find_mesh2d_topology_names(self, nc_dataset):
        """Return candidate 2D mesh topology variable names in preferred order."""
        names = []

        for variable_name, variable in nc_dataset.variables.items():
            try:
                cf_role = str(getattr(variable, "cf_role", "")).strip().lower()
                topology_dimension = int(getattr(variable, "topology_dimension", -1))
                if cf_role == "mesh_topology" and topology_dimension == 2:
                    names.append(variable_name)
            except (AttributeError, ValueError):
                continue

        for fallback_name in ("Mesh2d", "mesh2d"):
            found_name = self._find_variable_name(nc_dataset, fallback_name)
            if found_name is not None:
                names.append(found_name)

        unique_names = []
        for name in names:
            if name not in unique_names:
                unique_names.append(name)
        return unique_names

    def _detect_mesh1d_exists(self, nc_dataset):
        """Check if mesh1d topology exists in dataset."""
        return self._find_variable_name(nc_dataset, "mesh1d_node_x") is not None and self._find_variable_name(nc_dataset, "mesh1d_node_y") is not None

    def _detect_geometry_exists(self, nc_dataset):
        """Check if network geometry exists in dataset."""
        return self._find_variable_name(nc_dataset, "network_geom_x") is not None and self._find_variable_name(nc_dataset, "network_geom_y") is not None

    def _find_variable_name(self, nc_dataset, expected_name):
        """Return actual variable name for a case-insensitive lookup, or None."""
        if expected_name in nc_dataset.variables:
            return expected_name

        expected_lower = expected_name.lower()
        for name in nc_dataset.variables.keys():
            if name.lower() == expected_lower:
                return name
        return None

    def _analyze_ugrid_data_variables(self, nc_dataset):
        """Return selectable data variables and whether any require flattening."""
        candidate_names = []
        flattenable_names = []
        has_morphodynamic = False

        for name, variable in nc_dataset.variables.items():
            if self._is_topology_or_metadata_variable(name, variable):
                continue
            if not self._is_numeric_netcdf_variable(variable):
                continue

            candidate_names.append(name)
            if self._variable_has_extra_dimensions(variable.dimensions):
                has_morphodynamic = True
                flattenable_names.append(name)

        return {
            "candidate_names": sorted(candidate_names),
            "flattenable_names": sorted(flattenable_names),
            "default_selected": sorted(flattenable_names),
            "has_morphodynamic": has_morphodynamic,
        }

    def _is_topology_or_metadata_variable(self, name, variable):
        """Return True when the variable belongs to topology, geometry, or metadata."""
        name_lower = name.lower()
        topology_exact_names = {
            "time",
            "timestep",
            "projected_coordinate_system",
            "wgs84",
            "crs",
            "mesh2d",
            "mesh1d",
        }

        topology_suffixes = (
            "_node_x",
            "_node_y",
            "_node_z",
            "_edge_x",
            "_edge_y",
            "_face_x",
            "_face_y",
            "_face_x_bnd",
            "_face_y_bnd",
            "_edge_nodes",
            "_face_nodes",
            "_edge_faces",
            "_edge_type",
            "_flowelem_domain",
            "_flowelem_globalnr",
        )

        if name_lower in topology_exact_names:
            return True

        if name_lower.startswith("network_"):
            return True

        if name_lower.endswith(topology_suffixes):
            return True

        try:
            cf_role = str(getattr(variable, "cf_role", "")).strip().lower()
            if cf_role == "mesh_topology":
                return True
        except AttributeError:
            pass

        return False

    def _is_numeric_netcdf_variable(self, variable):
        """Return True if a netCDF variable stores numeric values."""
        import numpy as np

        try:
            dtype = np.dtype(variable.dtype)
        except Exception:
            return False
        return dtype.kind in ("i", "u", "f")

    def _is_time_dimension(self, dim_name):
        """Return True if the dimension appears to represent time."""
        value = str(dim_name).strip().lower()
        if value in ("time", "times", "ntime", "ntimes", "timestep", "timesteps"):
            return True
        return "time" in value

    def _is_space_dimension(self, dim_name):
        """Return True if the dimension appears to represent mesh space."""
        value = str(dim_name).strip().lower()
        tokens = (
            "mesh2d_n",
            "mesh1d_n",
            "mesh2d_face",
            "mesh2d_node",
            "mesh2d_edge",
            "mesh1d_face",
            "mesh1d_node",
            "mesh1d_edge",
            "network_node",
            "network_geom",
            "nmesh2d",
            "nmesh1d",
            "nnetwork",
        )
        return any(token in value for token in tokens)

    def _variable_extra_dimensions(self, dimensions):
        """Return dimensions that are not recognized as time or space dimensions."""
        extras = []
        for dim_name in dimensions:
            if self._is_time_dimension(dim_name) or self._is_space_dimension(dim_name):
                continue
            extras.append(dim_name)
        return extras

    def _variable_has_extra_dimensions(self, dimensions):
        """Return True when a variable has dimensions beyond time/space."""
        return bool(self._variable_extra_dimensions(dimensions))

    def _prompt_for_morphodynamic_variables(self, candidate_names, default_selected=None):
        """Prompt user to choose which data variables to include in the flattened file."""
        if not candidate_names:
            return []

        default_set = set(default_selected or [])

        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Select NetCDF Variables")
        dialog.resize(520, 480)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select data variables to include in the flattened file:"))

        # Qt6 moved flag/state enums into sub-namespaces; fall back gracefully.
        _item_checkable = getattr(Qt, "ItemIsUserCheckable", None) or getattr(getattr(Qt, "ItemFlag", None), "ItemIsUserCheckable", None)
        _checked = getattr(Qt, "Checked", None) or getattr(getattr(Qt, "CheckState", None), "Checked", None)
        _unchecked = getattr(Qt, "Unchecked", None) or getattr(getattr(Qt, "CheckState", None), "Unchecked", None)
        _ok = getattr(QDialogButtonBox, "Ok", None) or getattr(getattr(QDialogButtonBox, "StandardButton", None), "Ok", None)
        _cancel = getattr(QDialogButtonBox, "Cancel", None) or getattr(getattr(QDialogButtonBox, "StandardButton", None), "Cancel", None)
        _action_role = getattr(QDialogButtonBox, "ActionRole", None) or getattr(getattr(QDialogButtonBox, "ButtonRole", None), "ActionRole", None)
        _dlg_accepted = getattr(QDialog, "Accepted", None) or getattr(getattr(QDialog, "DialogCode", None), "Accepted", None)

        list_widget = QListWidget(dialog)
        for name in candidate_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | _item_checkable)
            if name in default_set:
                item.setCheckState(_checked)
            else:
                item.setCheckState(_unchecked)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(_ok | _cancel, parent=dialog)
        select_all_button = buttons.addButton("Select all", _action_role)
        unselect_all_button = buttons.addButton("Unselect all", _action_role)

        def _set_all_checks(state):
            for row in range(list_widget.count()):
                list_widget.item(row).setCheckState(state)

        select_all_button.clicked.connect(lambda: _set_all_checks(_checked))
        unselect_all_button.clicked.connect(lambda: _set_all_checks(_unchecked))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if _dialog_exec(dialog) != _dlg_accepted:
            return None

        selected = []
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item.checkState() == _checked:
                selected.append(item.text())

        return selected

    def _sidecar_flattened_path(self, source_path):
        """Return deterministic sidecar path for flattened datasets."""
        base, ext = os.path.splitext(source_path)
        return f"{base}_qgis_flat{ext}"

    def _prepare_flattened_ugrid_sidecar(self, source_path, selected_variables, progress_callback=None):
        """Create or reuse a sidecar netCDF with selected variables flattened to time/space."""
        import netCDF4 as nc
        import numpy as np

        source_path = os.path.abspath(source_path)
        sidecar_path = os.path.abspath(self._sidecar_flattened_path(source_path))
        source_mtime = str(int(os.path.getmtime(source_path)))
        signature = "v3|" + "|".join(sorted(selected_variables))

        if os.path.exists(sidecar_path):
            try:
                with nc.Dataset(sidecar_path, "r") as sidecar_ds:
                    sidecar_signature = str(getattr(sidecar_ds, "qgis_flatten_signature", ""))
                    sidecar_mtime = str(getattr(sidecar_ds, "qgis_flatten_source_mtime", ""))
                    if sidecar_signature == signature and sidecar_mtime == source_mtime:
                        if progress_callback is not None:
                            progress_callback(len(selected_variables), len(selected_variables), "reuse")
                        return sidecar_path
            except (OSError, RuntimeError):
                pass

        with nc.Dataset(source_path, "r") as source_ds, nc.Dataset(sidecar_path, "w", format="NETCDF4") as sidecar_ds:
            for attr_name in source_ds.ncattrs():
                sidecar_ds.setncattr(attr_name, getattr(source_ds, attr_name))

            created_dims = set()

            def _ensure_dimensions(dimensions):
                for dim_name in dimensions:
                    if dim_name in created_dims:
                        continue
                    src_dim = source_ds.dimensions[dim_name]
                    if src_dim.isunlimited():
                        sidecar_ds.createDimension(dim_name, None)
                    else:
                        sidecar_ds.createDimension(dim_name, len(src_dim))
                    created_dims.add(dim_name)

            def _copy_variable(src_name, dst_name=None):
                dst_name = dst_name or src_name
                if dst_name in sidecar_ds.variables or src_name not in source_ds.variables:
                    return

                src_var = source_ds.variables[src_name]
                _ensure_dimensions(src_var.dimensions)

                fill_value = getattr(src_var, "_FillValue", None)
                if fill_value is None:
                    dst_var = sidecar_ds.createVariable(dst_name, src_var.datatype, src_var.dimensions)
                else:
                    dst_var = sidecar_ds.createVariable(
                        dst_name,
                        src_var.datatype,
                        src_var.dimensions,
                        fill_value=fill_value,
                    )

                for attr_name in src_var.ncattrs():
                    if attr_name == "_FillValue":
                        continue
                    dst_var.setncattr(attr_name, getattr(src_var, attr_name))

                dst_var[:] = src_var[:]

            def _referenced_variable_tokens(variable):
                """Return variable names referenced by standard UGRID metadata attributes."""
                tokens = set()
                for attr_name in (
                    "grid_mapping",
                    "mesh",
                    "coordinates",
                    "node_coordinates",
                    "edge_coordinates",
                    "face_coordinates",
                    "face_node_connectivity",
                    "edge_node_connectivity",
                    "edge_face_connectivity",
                    "node_dimension",
                    "edge_dimension",
                    "face_dimension",
                    "time",
                ):
                    attr_value = getattr(variable, attr_name, None)
                    if not attr_value:
                        continue

                    for token in re.split(r"[\s,;]+", str(attr_value).strip()):
                        token = token.strip()
                        if token and token in source_ds.variables:
                            tokens.add(token)
                return tokens

            required_variable_names = set()
            for var_name, src_var in source_ds.variables.items():
                if self._is_topology_or_metadata_variable(var_name, src_var):
                    required_variable_names.add(var_name)
                    continue

                try:
                    cf_role = str(getattr(src_var, "cf_role", "")).strip().lower()
                    if cf_role in (
                        "mesh_topology",
                        "edge_node_connectivity",
                        "face_node_connectivity",
                        "edge_face_connectivity",
                    ):
                        required_variable_names.add(var_name)
                except AttributeError:
                    pass

            for selected_name in selected_variables:
                selected_var = source_ds.variables.get(selected_name)
                if selected_var is None:
                    continue

                required_variable_names.update(_referenced_variable_tokens(selected_var))

                for dim_name in selected_var.dimensions:
                    if dim_name in source_ds.variables:
                        required_variable_names.add(dim_name)

            pending = list(required_variable_names)
            while pending:
                current_name = pending.pop()
                current_var = source_ds.variables.get(current_name)
                if current_var is None:
                    continue

                for referenced_name in _referenced_variable_tokens(current_var):
                    if referenced_name not in required_variable_names:
                        required_variable_names.add(referenced_name)
                        pending.append(referenced_name)

                for dim_name in current_var.dimensions:
                    if dim_name in source_ds.variables and dim_name not in required_variable_names:
                        required_variable_names.add(dim_name)
                        pending.append(dim_name)

            spatial_dimensions = {
                dim_name
                for dim_name in source_ds.dimensions.keys()
                if self._is_space_dimension(dim_name)
            }
            for required_name in required_variable_names:
                required_var = source_ds.variables.get(required_name)
                if required_var is None:
                    continue
                for dim_name in required_var.dimensions:
                    if not self._is_time_dimension(dim_name):
                        spatial_dimensions.add(dim_name)

            for required_name in sorted(required_variable_names):
                _copy_variable(required_name)

            generated_names = []
            used_names = set(sidecar_ds.variables.keys())

            total_variables = len(selected_variables)
            for variable_index, variable_name in enumerate(selected_variables, start=1):
                if progress_callback is not None:
                    progress_callback(variable_index, total_variables, variable_name)

                if variable_name not in source_ds.variables:
                    continue

                variable = source_ds.variables[variable_name]
                if not self._is_numeric_netcdf_variable(variable):
                    continue

                extra_dims = [
                    dim_name
                    for dim_name in variable.dimensions
                    if not self._is_time_dimension(dim_name) and dim_name not in spatial_dimensions
                ]
                if not extra_dims:
                    _copy_variable(variable_name)
                    continue

                keep_dims = tuple(dim for dim in variable.dimensions if dim not in extra_dims)
                if len(keep_dims) > 2:
                    continue

                labels_by_dim = {
                    dim_name: self._dimension_labels(source_ds, dim_name)
                    for dim_name in extra_dims
                }
                dim_positions = {dim_name: idx for idx, dim_name in enumerate(variable.dimensions)}

                data = variable[:]
                if isinstance(data, np.ma.MaskedArray):
                    fill_value = getattr(variable, "_FillValue", np.nan)
                    data = data.filled(fill_value)

                index_ranges = [range(len(labels_by_dim[dim_name])) for dim_name in extra_dims]
                for dim_indices in itertools.product(*index_ranges):
                    index_slices = [slice(None)] * len(variable.dimensions)
                    label_parts = []

                    for dim_name, index_value in zip(extra_dims, dim_indices):
                        index_slices[dim_positions[dim_name]] = index_value
                        label_token = self._sanitize_netcdf_token(
                            labels_by_dim[dim_name][index_value],
                            fallback=f"{dim_name}_{index_value + 1}"
                        )
                        label_parts.append(label_token)

                    flattened_name = self._build_flattened_variable_name(variable_name, label_parts, used_names)
                    fill_value = getattr(variable, "_FillValue", None)
                    _ensure_dimensions(keep_dims)
                    if fill_value is None:
                        out_var = sidecar_ds.createVariable(
                            flattened_name,
                            variable.datatype,
                            keep_dims,
                        )
                    else:
                        out_var = sidecar_ds.createVariable(
                            flattened_name,
                            variable.datatype,
                            keep_dims,
                            fill_value=fill_value,
                        )

                    for attr_name in variable.ncattrs():
                        if attr_name == "_FillValue":
                            continue
                        attr_value = getattr(variable, attr_name)
                        if attr_name in ("long_name", "standard_name"):
                            attr_value = f"{attr_value} ({', '.join(label_parts)})"
                        out_var.setncattr(attr_name, attr_value)

                    out_var[:] = data[tuple(index_slices)]
                    generated_names.append(flattened_name)

            for variable_name, variable in sidecar_ds.variables.items():
                for referenced_name in _referenced_variable_tokens(variable):
                    if referenced_name not in sidecar_ds.variables:
                        raise RuntimeError(
                            f"Invalid sidecar linkage: variable '{variable_name}' references "
                            f"missing variable '{referenced_name}'."
                        )

            sidecar_ds.setncattr("qgis_flatten_signature", signature)
            sidecar_ds.setncattr("qgis_flatten_source_mtime", source_mtime)
            sidecar_ds.setncattr("qgis_flatten_generated", "|".join(generated_names))

        if progress_callback is not None and selected_variables:
            progress_callback(len(selected_variables), len(selected_variables), "done")

        return sidecar_path

    def _dimension_labels(self, nc_dataset, dim_name):
        """Return preferred labels for a dimension, using coordinate variables when available."""
        size = len(nc_dataset.dimensions[dim_name])

        if dim_name in nc_dataset.variables:
            labels = self._labels_from_variable(nc_dataset.variables[dim_name], size)
            if labels:
                return labels

        for variable_name, variable in nc_dataset.variables.items():
            if len(variable.dimensions) != 1 or variable.dimensions[0] != dim_name:
                continue
            if variable_name.lower() == dim_name.lower():
                continue
            labels = self._labels_from_variable(variable, size)
            if labels:
                return labels

        return [str(index + 1) for index in range(size)]

    def _labels_from_variable(self, variable, expected_size):
        """Return string labels extracted from a 1D coordinate-like variable."""
        import netCDF4 as nc
        import numpy as np

        try:
            values = variable[:]
        except Exception:
            return None

        if isinstance(values, np.ma.MaskedArray):
            fill_value = b"" if values.dtype.kind == "S" else ""
            values = values.filled(fill_value)

        values_array = np.asarray(values)
        if values_array.size != expected_size:
            return None

        if values_array.dtype.kind in ("S", "U") and values_array.ndim > 1:
            values_array = nc.chartostring(values_array)

        if values_array.dtype.kind not in ("S", "U", "i", "u", "f"):
            return None

        result = []
        for value in np.asarray(values_array).tolist():
            if isinstance(value, float):
                if math.isfinite(value) and float(value).is_integer():
                    value = int(value)
            result.append(str(value).replace("\x00", "").strip())
        return result

    def _sanitize_netcdf_token(self, value, fallback):
        """Normalize arbitrary values into safe netCDF variable-name tokens."""
        token = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip())
        token = token.strip("_").lower()
        if not token:
            token = re.sub(r"[^0-9A-Za-z_]+", "_", str(fallback).strip()).strip("_").lower()
        if token and token[0].isdigit():
            token = f"v_{token}"
        return token or "value"

    def _build_flattened_variable_name(self, base_name, label_parts, used_names):
        """Build a unique flattened variable name that preserves the original variable name."""
        base_token = self._sanitize_netcdf_token(base_name, fallback="var")
        label_token = "_".join(part for part in label_parts if part) or "flat"
        candidate = f"{base_token}_{label_token}"
        candidate = candidate[:180]

        suffix = 2
        unique_name = candidate
        while unique_name in used_names:
            unique_name = f"{candidate}_{suffix}"
            suffix += 1

        used_names.add(unique_name)
        return unique_name

    def _has_nonempty_strings(self, values):
        """Return True when the sequence contains at least one non-empty string."""
        if not values:
            return False
        return any(str(value).strip() for value in values)

    def _read_mesh1d_data(self, nc_dataset):
        """Read mesh1d node coordinates and edge connectivity."""
        import numpy as np

        node_x = nc_dataset.variables["mesh1d_node_x"][:]
        node_y = nc_dataset.variables["mesh1d_node_y"][:]

        # Handle masked arrays
        if isinstance(node_x, np.ma.MaskedArray):
            node_x = node_x.filled(np.nan)
        if isinstance(node_y, np.ma.MaskedArray):
            node_y = node_y.filled(np.nan)

        node_x = np.asarray(node_x, dtype=float)
        node_y = np.asarray(node_y, dtype=float)

        # Read edge connectivity
        edges = nc_dataset.variables["mesh1d_edge_nodes"][:] if "mesh1d_edge_nodes" in nc_dataset.variables else None
        edge_branch = nc_dataset.variables["mesh1d_edge_branch"][:] if "mesh1d_edge_branch" in nc_dataset.variables else None
        branch_names = self._read_string_array(nc_dataset, "network_branch_long_name")
        if not self._has_nonempty_strings(branch_names):
            branch_names = self._read_string_array(nc_dataset, "network_branch_id")

        if edges is None or edge_branch is None:
            return None

        return {
            "node_x": node_x,
            "node_y": node_y,
            "edges": edges,
            "edge_branch": edge_branch,
            "branch_names": branch_names,
        }

    def _read_geometry_data(self, nc_dataset):
        """Read network geometry data."""
        import numpy as np

        # Geometry nodes
        geom_x = nc_dataset.variables["network_geom_x"][:]
        geom_y = nc_dataset.variables["network_geom_y"][:]

        if isinstance(geom_x, np.ma.MaskedArray):
            geom_x = geom_x.filled(np.nan)
        if isinstance(geom_y, np.ma.MaskedArray):
            geom_y = geom_y.filled(np.nan)

        geom_x = np.asarray(geom_x, dtype=float)
        geom_y = np.asarray(geom_y, dtype=float)

        node_x = nc_dataset.variables["network_node_x"][:] if "network_node_x" in nc_dataset.variables else None
        node_y = nc_dataset.variables["network_node_y"][:] if "network_node_y" in nc_dataset.variables else None
        if node_x is not None and node_y is not None:
            if isinstance(node_x, np.ma.MaskedArray):
                node_x = node_x.filled(np.nan)
            if isinstance(node_y, np.ma.MaskedArray):
                node_y = node_y.filled(np.nan)
            node_x = np.asarray(node_x, dtype=float)
            node_y = np.asarray(node_y, dtype=float)

        # Geometry node count and indices
        geom_node_count = nc_dataset.variables["network_geom_node_count"][:] if "network_geom_node_count" in nc_dataset.variables else None

        # Edge names
        edge_names = self._read_string_array(nc_dataset, "network_branch_long_name")
        if not self._has_nonempty_strings(edge_names):
            edge_names = self._read_string_array(nc_dataset, "network_branch_id")

        node_names = self._read_string_array(nc_dataset, "network_node_long_name")
        if not self._has_nonempty_strings(node_names):
            node_names = self._read_string_array(nc_dataset, "network_node_id")

        return {
            "geom_node_x": geom_x,
            "geom_node_y": geom_y,
            "node_x": node_x,
            "node_y": node_y,
            "geom_node_count": geom_node_count,
            "edge_names": edge_names,
            "node_names": node_names,
        }

    def _read_string_array(self, nc_dataset, var_name):
        """Read a string array variable (e.g., 'network_branch_long_name')."""
        import netCDF4 as nc
        import numpy as np

        if var_name not in nc_dataset.variables:
            return None

        var = nc_dataset.variables[var_name]
        raw_data = var[:]

        if isinstance(raw_data, np.ma.MaskedArray):
            fill_value = b" " if raw_data.dtype.kind == "S" else " "
            raw_data = raw_data.filled(fill_value)

        raw_array = np.asarray(raw_data)

        if raw_array.dtype.kind in ("S", "U") and raw_array.ndim > 1:
            string_array = nc.chartostring(raw_array)
        elif raw_array.dtype.kind == "S":
            string_array = raw_array.astype("U")
        elif raw_array.dtype.kind == "U":
            string_array = raw_array
        else:
            if not hasattr(raw_array, "__len__"):
                return None
            string_array = raw_array

        values = np.asarray(string_array).tolist()
        if not isinstance(values, list):
            values = [values]

        return [str(value).replace("\x00", "").strip() for value in values]

    def _load_mesh2d_layer(
        self,
        filepath,
        base_name,
        epsg,
        layer_name,
        topology_names=None,
        expect_data_variables=False,
    ):
        """Load 2D mesh as native QGIS mesh layer."""
        try:
            from qgis.core import QgsMeshLayer, QgsCoordinateReferenceSystem, QgsProject
        except ImportError:
            raise RuntimeError("Could not import QgsMeshLayer from QGIS")

        import os

        # Ensure absolute path
        filepath = os.path.abspath(filepath)
        if not os.path.exists(filepath):
            raise RuntimeError(f"File does not exist: {filepath}")

        def _dataset_group_count(layer):
            try:
                provider = layer.dataProvider()
                if provider is not None and hasattr(provider, "datasetGroupCount"):
                    return int(provider.datasetGroupCount())
            except (AttributeError, RuntimeError):
                pass

            try:
                if hasattr(layer, "datasetGroupCount"):
                    return int(layer.datasetGroupCount())
            except (AttributeError, RuntimeError):
                pass

            return None

        def _apply_crs_if_missing(layer):
            if layer is not None and layer.isValid() and not layer.crs().isValid():
                crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
                layer.setCrs(crs)

        def _is_usable_2d_mesh(layer, require_datasets=False):
            if layer is None or not layer.isValid():
                return False

            has_geometry = False
            try:
                if layer.meshFaceCount() > 0:
                    has_geometry = True
            except (AttributeError, RuntimeError):
                pass

            if not has_geometry:
                try:
                    ext = layer.extent()
                    has_geometry = ext is not None and not ext.isEmpty()
                except Exception:
                    has_geometry = False

            if not has_geometry:
                return False

            if not require_datasets:
                return True

            dataset_groups = _dataset_group_count(layer)
            if dataset_groups is None:
                return True
            return dataset_groups > 0

        def _source_matches(layer_source, target_path):
            if not layer_source:
                return False
            source = layer_source.split("|")[0]
            if source.lower().startswith("file:///"):
                source = source[8:]
            source = source.replace("/", os.sep)
            try:
                return os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target_path))
            except Exception:
                return False

        def _dispose_candidate_layer(layer):
            """Release temporary mesh layers created during URI probing."""
            if layer is None:
                return

            try:
                delete_later = getattr(layer, "deleteLater", None)
                if callable(delete_later):
                    delete_later()
            except (RuntimeError, AttributeError):
                pass

            try:
                QApplication.processEvents()
            except (RuntimeError, AttributeError):
                pass

        # Prefer explicit topology URIs first and keep retries minimal.
        quoted_file = f'"{filepath}"'
        ordered_topology_names = []
        for topology_name in (topology_names or []):
            if topology_name and topology_name not in ordered_topology_names:
                ordered_topology_names.append(topology_name)
        for fallback_name in ("Mesh2d", "mesh2d"):
            if fallback_name not in ordered_topology_names:
                ordered_topology_names.append(fallback_name)

        attempt_candidates = []
        for topology_name in ordered_topology_names:
            attempt_candidates.append((f'mdal:{quoted_file}:{topology_name}', "mdal"))

        attempt_candidates.extend(
            [
                (f"mdal:{filepath}", "mdal"),
                (filepath, "mdal"),
                # Last-resort fallback for environments where provider autodetection is required.
                (filepath, ""),
            ]
        )

        unique_attempts = []
        for candidate in attempt_candidates:
            if candidate not in unique_attempts:
                unique_attempts.append(candidate)

        for uri, provider in unique_attempts:
            mesh_layer = QgsMeshLayer(uri, layer_name, provider)
            if not mesh_layer.isValid():
                _dispose_candidate_layer(mesh_layer)
                continue

            if _is_usable_2d_mesh(mesh_layer, require_datasets=expect_data_variables):
                _apply_crs_if_missing(mesh_layer)
                QgsProject.instance().addMapLayer(mesh_layer)
                return mesh_layer

            _dispose_candidate_layer(mesh_layer)

        # Avoid false-negative warning if a valid mesh from this same source is already loaded.
        for existing_layer in QgsProject.instance().mapLayers().values():
            if isinstance(existing_layer, QgsMeshLayer) and existing_layer.isValid():
                if _source_matches(existing_layer.source(), filepath) and _is_usable_2d_mesh(
                    existing_layer,
                    require_datasets=expect_data_variables,
                ):
                    _apply_crs_if_missing(existing_layer)
                    return existing_layer

        raise RuntimeError(
            f"Failed to load mesh from {filepath}. "
            f"Tried topology names: {', '.join(ordered_topology_names)}. "
            "Ensure the file is a valid UGRID mesh in netCDF format with mesh-linked datasets. "
            "Use native QGIS mesh import with mesh topology + variable to compare behavior. "
            "Try opening directly in QGIS (File > Open Mesh) to verify."
        )

    def _load_mesh1d_branches_layer(self, node_x, node_y, edges, edge_branch, branch_names, epsg, layer_name):
        """Load mesh1d branches as polyline layer."""
        import numpy as np

        layer = QgsVectorLayer(f"LineString?crs=EPSG:{epsg}", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        layer.updateFields()

        # Group edges by branch
        unique_branches = np.unique(edge_branch)
        features = []

        for branch_id in sorted(unique_branches):
            branch_edge_indices = np.where(edge_branch == branch_id)[0]
            if len(branch_edge_indices) == 0:
                continue

            # Build adjacency graph from edges
            adjacency = {}  # node -> list of connected nodes
            branch_edges = []
            for edge_idx in branch_edge_indices:
                edge = edges[edge_idx]
                start_node, end_node = int(edge[0]), int(edge[1])
                branch_edges.append((start_node, end_node))
                
                if start_node not in adjacency:
                    adjacency[start_node] = []
                if end_node not in adjacency:
                    adjacency[end_node] = []
                
                adjacency[start_node].append(end_node)
                adjacency[end_node].append(start_node)

            if not branch_edges or not adjacency:
                continue

            # Find start node (node with degree 1, or just first node)
            start_node = None
            for node, neighbors in adjacency.items():
                if len(neighbors) == 1:
                    start_node = node
                    break
            
            if start_node is None:
                # No start node with degree 1, use first node
                start_node = branch_edges[0][0]

            # Traverse the chain to build ordered node list
            ordered_nodes = [start_node]
            current_node = start_node
            prev_node = None

            while len(ordered_nodes) < len(adjacency):
                neighbors = adjacency.get(current_node, [])
                next_node = None
                
                for neighbor in neighbors:
                    if neighbor != prev_node:  # Don't go back
                        next_node = neighbor
                        break
                
                if next_node is None:
                    break  # End of chain
                
                ordered_nodes.append(next_node)
                prev_node = current_node
                current_node = next_node

            if len(ordered_nodes) < 2:
                continue

            # Build polyline geometry from ordered nodes
            points = [QgsPointXY(float(node_x[n]), float(node_y[n])) for n in ordered_nodes]
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPolylineXY(points))

            branch_name = f"Branch_{branch_id}"
            branch_index = int(branch_id)
            if branch_names and 0 <= branch_index < len(branch_names):
                if branch_names[branch_index]:
                    branch_name = branch_names[branch_index]

            feat.setAttributes([branch_name])
            features.append(feat)

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

    def _load_geometry_edges_layer(self, geom_node_x, geom_node_y, geom_node_count, edge_names, epsg, layer_name):
        """Load network geometry edges as polyline layer from geometry nodes."""
        import numpy as np

        if geom_node_x is None or geom_node_y is None or geom_node_count is None:
            raise ValueError("Missing geometry node or node count data")

        layer = QgsVectorLayer(f"LineString?crs=EPSG:{epsg}", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        layer.updateFields()

        features = []
        
        # Reconstruct polylines from geometry nodes using node counts
        geom_idx = 0
        for branch_idx, node_count in enumerate(geom_node_count):
            if node_count < 1:
                continue
            
            # Extract geometry nodes for this branch
            node_indices = np.arange(geom_idx, geom_idx + node_count)
            
            # Validate indices
            if np.any(node_indices >= len(geom_node_x)):
                break
            
            # Build polyline from these nodes
            points = [
                QgsPointXY(float(geom_node_x[i]), float(geom_node_y[i]))
                for i in node_indices
            ]
            
            if len(points) >= 2:
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPolylineXY(points))
                
                # Use edge name if available
                edge_name = f"Branch_{branch_idx}"
                if edge_names and branch_idx < len(edge_names):
                    name = edge_names[branch_idx]
                    if name:
                        edge_name = name
                
                feat.setAttributes([edge_name])
                features.append(feat)
            
            geom_idx += node_count

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

    def _load_geometry_nodes_layer(self, geom_node_x, geom_node_y, geom_node_names, epsg, layer_name):
        """Load network geometry nodes as point layer."""
        layer = QgsVectorLayer(f"Point?crs=EPSG:{epsg}", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        layer.updateFields()

        features = []

        for idx, (x, y) in enumerate(zip(geom_node_x, geom_node_y)):
            if not (float('-inf') < float(x) < float('inf') and float('-inf') < float(y) < float('inf')):
                continue

            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))

            node_name = "node"
            if geom_node_names and idx < len(geom_node_names):
                name = geom_node_names[idx]
                if name:
                    node_name = name

            feat.setAttributes([node_name])
            features.append(feat)

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

    def load_shorelines_mat_file(self, filepath):
        """Load ShorelineS results from a .mat file into separate line layers."""
        try:
            from scipy.io import loadmat
        except ModuleNotFoundError:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "The 'scipy' package is required. Use 'Install Python Dependencies' and restart QGIS."
            )
            return

        import numpy as np

        try:
            mat_data = loadmat(filepath, squeeze_me=True)
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Error reading .mat file: {e}"
            )
            return

        # Find the data source - try different possible locations
        data_source = None
        
        # Try 'O' key first (common for ShorelineS output)
        if 'O' in mat_data:
            O_data = mat_data['O']
            # With squeeze_me=True, (1,1) becomes 0-d array; with squeeze_me=False, it stays (1,1)
            if isinstance(O_data, np.ndarray):
                if O_data.ndim == 0:
                    # 0-d array from squeeze_me=True, it's already the void record
                    data_source = O_data
                elif O_data.shape == (1, 1):
                    # (1,1) array from squeeze_me=False
                    data_source = O_data[0, 0]
                else:
                    data_source = O_data
            else:
                # Already a scalar/void object
                data_source = O_data
        
        # Try output.O structure (alternative nesting)
        if data_source is None and 'output' in mat_data:
            output = mat_data['output']
            if hasattr(output, 'O'):
                O_data = output.O
                if isinstance(O_data, np.ndarray):
                    if O_data.ndim == 0:
                        data_source = O_data
                    elif O_data.shape == (1, 1):
                        data_source = O_data[0, 0]
                    else:
                        data_source = O_data
                else:
                    data_source = O_data
            elif isinstance(output, dict) and 'O' in output:
                O_data = output['O']
                if isinstance(O_data, np.ndarray):
                    if O_data.ndim == 0:
                        data_source = O_data
                    elif O_data.shape == (1, 1):
                        data_source = O_data[0, 0]
                    else:
                        data_source = O_data
                else:
                    data_source = O_data

        # Validate ShorelineS structure
        required_fields = {"x", "y", "timenum"}
        
        # Detect available keys by checking for specific fields using the same method as _field_exists
        available_keys = set()
        all_possible_fields = ["x", "y", "timenum", "xhard", "yhard", "x_groyne", "y_groyne"]
        
        for attr in all_possible_fields:
            # Use the same detection logic as _field_exists
            try:
                # Try indexed access first (for numpy.void and dicts)
                if hasattr(data_source, '__getitem__'):
                    try:
                        data_source[attr]
                        available_keys.add(attr)
                        continue
                    except (KeyError, TypeError, IndexError):
                        pass
                
                # Try attribute access (for regular objects)
                if hasattr(data_source, attr):
                    available_keys.add(attr)
            except (AttributeError, TypeError):
                pass
        
        if not required_fields.issubset(available_keys):
            # Debug: print structure contents for diagnostics
            debug_info = []
            debug_info.append("Available data structure contents:")
            
            # Try different methods to see what's available
            if isinstance(data_source, dict):
                debug_info.append(f"  Dict keys: {list(data_source.keys())}")
            if hasattr(data_source, "dtype"):
                debug_info.append(f"  dtype names: {list(data_source.dtype.names) if hasattr(data_source.dtype, 'names') else 'N/A'}")
            if hasattr(data_source, "_fields"):
                debug_info.append(f"  _fields: {list(data_source._fields)}")
            
            debug_str = "\n".join(debug_info)
            
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"File does not appear to be a ShorelineS results file.\n\n"
                f"Required fields: {', '.join(sorted(required_fields))}\n"
                f"Found fields: {', '.join(sorted(available_keys)) if available_keys else 'None'}\n\n"
                f"Debug info:\n{debug_str}"
            )
            return

        # Validate array shapes and values
        try:
            x = np.asarray(self._get_field(data_source, "x"), dtype=float)
            y = np.asarray(self._get_field(data_source, "y"), dtype=float)
            timenum = np.asarray(self._get_field(data_source, "timenum"), dtype=float)

            if x.ndim != 2 or y.ndim != 2 or timenum.ndim != 1:
                raise ValueError(
                    f"Invalid ShorelineS structure: x ({x.ndim}D), y ({y.ndim}D), "
                    f"timenum ({timenum.ndim}D); expected x/y 2D, timenum 1D"
                )

            if x.shape != y.shape:
                raise ValueError(
                    f"x and y shape mismatch: {x.shape} vs {y.shape}"
                )

            if x.shape[1] != len(timenum):
                raise ValueError(
                    f"x/y column count ({x.shape[1]}) does not match timenum length ({len(timenum)})"
                )

        except (TypeError, ValueError) as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Error validating ShorelineS arrays: {e}"
            )
            return

        base_name = os.path.splitext(os.path.basename(filepath))[0]
        epsg = 28992  # Default RD New CRS
        loaded_layers = []

        # Load coastline layer (one feature per timestep)
        try:
            coastline_count = self._load_coastline_layer(
                x, y, timenum, base_name, epsg
            )
            if coastline_count > 0:
                loaded_layers.append(f"coastline ({coastline_count} timesteps)")
        except Exception as e:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                f"Could not load coastline: {e}"
            )

        # Load hard structures layer (optional)
        if self._field_exists(data_source, "xhard") and self._field_exists(data_source, "yhard"):
            try:
                xhard = np.asarray(self._get_field(data_source, "xhard"), dtype=float)
                yhard = np.asarray(self._get_field(data_source, "yhard"), dtype=float)
                
                # Flatten 2D arrays to 1D (take first timestep if time-varying)
                if xhard.ndim == 2:
                    xhard = xhard[:, 0].flatten()
                elif xhard.ndim > 2:
                    xhard = xhard.flatten()
                
                if yhard.ndim == 2:
                    yhard = yhard[:, 0].flatten()
                elif yhard.ndim > 2:
                    yhard = yhard.flatten()
                
                hard_count = self._load_hard_features_layer(
                    xhard, yhard, "hard_structures", base_name, epsg
                )
                if hard_count > 0:
                    loaded_layers.append(f"hard structures ({hard_count})")
            except Exception as e:
                self.iface.messageBar().pushWarning(
                    "Delft3D File Manager",
                    f"Could not load hard structures: {e}"
                )

        # Load groynes layer (optional)
        if self._field_exists(data_source, "x_groyne") and self._field_exists(data_source, "y_groyne"):
            try:
                x_groyne = np.asarray(self._get_field(data_source, "x_groyne"), dtype=float)
                y_groyne = np.asarray(self._get_field(data_source, "y_groyne"), dtype=float)
                
                # Flatten 2D arrays to 1D (take first timestep if time-varying)
                if x_groyne.ndim == 2:
                    x_groyne = x_groyne[:, 0].flatten()
                elif x_groyne.ndim > 2:
                    x_groyne = x_groyne.flatten()
                
                if y_groyne.ndim == 2:
                    y_groyne = y_groyne[:, 0].flatten()
                elif y_groyne.ndim > 2:
                    y_groyne = y_groyne.flatten()
                
                groyne_count = self._load_hard_features_layer(
                    x_groyne, y_groyne, "groynes", base_name, epsg
                )
                if groyne_count > 0:
                    loaded_layers.append(f"groynes ({groyne_count})")
            except Exception as e:
                self.iface.messageBar().pushWarning(
                    "Delft3D File Manager",
                    f"Could not load groynes: {e}"
                )

        if loaded_layers:
            self.iface.messageBar().pushSuccess(
                "Delft3D File Manager",
                f"Loaded ShorelineS data: {', '.join(loaded_layers)}"
            )
        else:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid ShorelineS data could be imported from the file"
            )

    def _load_coastline_layer(self, x, y, timenum, base_name, epsg):
        """Load coastline as one feature per timestep."""
        import numpy as np

        layer = QgsVectorLayer(
            f"LineString?crs=EPSG:{epsg}",
            f"{base_name}_coastline",
            "memory"
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("t_index", QVariant.Int),
            QgsField("timenum", QVariant.Double),
            QgsField("datetime", QVariant.DateTime)
        ])
        layer.updateFields()

        features = []
        for t_idx in range(x.shape[1]):
            x_vals = x[:, t_idx]
            y_vals = y[:, t_idx]

            # Extract polylines from this timestep, handling NaN separators
            polylines = self._extract_polylines_from_arrays(x_vals, y_vals)
            if not polylines:
                continue

            for polyline in polylines:
                if len(polyline) < 2:
                    continue

                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPolylineXY(polyline))
                feat.setAttributes([
                    t_idx,
                    float(timenum[t_idx]),
                    QDateTime(self._matlab_datenum_to_datetime(timenum[t_idx]))
                ])
                features.append(feat)

        if not features:
            return 0

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return len(features)

    def _matlab_datenum_to_datetime(self, matlab_datenum):
        """Convert MATLAB datenum to a Python datetime."""
        serial_date = float(matlab_datenum)
        return datetime.fromordinal(int(serial_date)) + timedelta(days=serial_date % 1) - timedelta(days=366)

    def _load_hard_features_layer(self, x_array, y_array, feature_type, base_name, epsg):
        """Load hard features (structures or groynes) as polylines."""
        import numpy as np

        layer_name = f"{base_name}_{feature_type}"
        layer = QgsVectorLayer(
            f"LineString?crs=EPSG:{epsg}",
            layer_name,
            "memory"
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("kind", QVariant.String),
            QgsField("segment_id", QVariant.Int)
        ])
        layer.updateFields()

        # Extract polylines from hard feature arrays
        polylines = self._extract_polylines_from_arrays(x_array, y_array)
        if not polylines:
            return 0

        features = []
        for seg_idx, polyline in enumerate(polylines):
            if len(polyline) < 2:
                continue

            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPolylineXY(polyline))
            feat.setAttributes([
                feature_type.rstrip("s"),  # "hard_structures" -> "hard_structure", "groynes" -> "groyne"
                seg_idx
            ])
            features.append(feat)

        if not features:
            return 0

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return len(features)

    def _extract_polylines_from_arrays(self, x_array, y_array):
        """Extract polylines from 1D arrays, handling NaN-separated segments."""
        import numpy as np

        x_array = np.asarray(x_array, dtype=float)
        y_array = np.asarray(y_array, dtype=float)

        polylines = []
        current_line = []

        for i in range(len(x_array)):
            x_val = x_array[i]
            y_val = y_array[i]

            # Check for NaN separator or check if values are finite
            if not (np.isfinite(x_val) and np.isfinite(y_val)):
                # End current line if it has enough points
                if len(current_line) >= 2:
                    polylines.append(current_line)
                current_line = []
            else:
                current_line.append(QgsPointXY(float(x_val), float(y_val)))

        # Add final line if it has enough points
        if len(current_line) >= 2:
            polylines.append(current_line)

        return polylines

    def _field_exists(self, source, field_name):
        """Check if a field exists in a structured array, dict, or object."""
        try:
            # Try indexed access first (for structured arrays and dicts)
            if hasattr(source, '__getitem__'):
                try:
                    source[field_name]
                    return True
                except (KeyError, TypeError, IndexError):
                    pass
            
            # Try attribute access (for regular objects)
            if hasattr(source, field_name):
                return True
            
            return False
        except Exception:
            return False

    def _get_field(self, source, field_name):
        """Extract field from structured array, dict, or object."""
        import numpy as np
        
        # Try indexed access first (for structured arrays and dicts)
        if hasattr(source, '__getitem__'):
            try:
                value = source[field_name]
                # Handle 0-d arrays with object dtype (from squeeze_me=True in loadmat)
                if isinstance(value, np.ndarray) and value.ndim == 0 and value.dtype == object:
                    value = value.item()
                return value
            except (KeyError, TypeError, IndexError):
                pass
        
        # Try attribute access (for regular objects)
        if hasattr(source, field_name):
            value = getattr(source, field_name)
            # Handle 0-d arrays with object dtype
            if isinstance(value, np.ndarray) and value.ndim == 0 and value.dtype == object:
                value = value.item()
            return value
        
        raise AttributeError(f"Field {field_name} not found")

    def create_trachytopes_from_mesh(self):
        """Create a trachytopes point layer from mesh edge coordinates."""
        mesh_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select UGRID mesh file",
            "",
            "NetCDF files (*.nc);;All files (*)",
        )
        if not mesh_path:
            return

        try:
            edge_x, edge_y, epsg = self._read_mesh_edge_coordinates(mesh_path)
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not read mesh edge coordinates:\n{exc}",
            )
            return

        if edge_x.size == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No valid edge coordinates found in the selected mesh file.",
            )
            return

        base_name = os.path.splitext(os.path.basename(mesh_path))[0]
        default_layer_name = f"{base_name}_trachytopes"
        layer_name, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Trachytopes Layer",
            "Layer name:",
            text=default_layer_name,
        )
        if not ok:
            return
        layer_name = (layer_name or "").strip() or default_layer_name

        if epsg is None:
            epsg, ok = QInputDialog.getInt(
                self.iface.mainWindow(),
                "Mesh CRS",
                "EPSG code for the new layer:",
                value=28992,
                min=1,
                max=999999,
            )
            if not ok:
                return

        self._create_trachytopes_layer(layer_name, edge_x, edge_y, epsg)

    def create_bridge_points_from_polyline(self):
        """Create a bridge point layer from vertices of the active polyline layer."""
        line_layer = self.iface.activeLayer()
        if line_layer is None or line_layer.type() != QgsMapLayerType.VectorLayer:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Select a polyline layer as active layer first.",
            )
            return

        if line_layer.geometryType() != QgsWkbTypes.LineGeometry:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Active layer must be a polyline layer.",
            )
            return

        width, ok = QInputDialog.getDouble(
            self.iface.mainWindow(),
            "Bridge Width",
            "Default width value for all bridge points:",
            value=2.5,
            min=-1e12,
            max=1e12,
            decimals=6,
        )
        if not ok:
            return

        drag_cd, ok = QInputDialog.getDouble(
            self.iface.mainWindow(),
            "Bridge Drag Coefficient",
            "Default drag_cd value for all bridge points:",
            value=1.0,
            min=-1e12,
            max=1e12,
            decimals=6,
        )
        if not ok:
            return
        self._create_point_layer_from_polyline_vertices(
            line_layer=line_layer,
            output_name=f"{line_layer.name()}_points",
            output_fields=[
                QgsField("bridge_name", QVariant.String),
                QgsField("width", QVariant.Double),
                QgsField("drag_cd", QVariant.Double),
            ],
            prompt_values=[width, drag_cd],
            success_label="bridge points",
        )

    def create_fixed_weir_points_from_polyline(self):
        """Create a fixed-weir point layer from vertices of the active polyline layer."""
        line_layer = self.iface.activeLayer()
        if line_layer is None or line_layer.type() != QgsMapLayerType.VectorLayer:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Select a polyline layer as active layer first.",
            )
            return

        if line_layer.geometryType() != QgsWkbTypes.LineGeometry:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Active layer must be a polyline layer.",
            )
            return

        prompt_specs = [
            ("Fixed Weir Crest Level", "Default crest_lvl value for all fixed-weir points:", 1.0),
            ("Fixed Weir Left Sill Height", "Default sill_hL value for all fixed-weir points:", 0.0),
            ("Fixed Weir Right Sill Height", "Default sill_hR value for all fixed-weir points:", 0.0),
            ("Fixed Weir Crest Width", "Default crest_w value for all fixed-weir points:", 10.0),
            ("Fixed Weir Left Slope", "Default slope_L value for all fixed-weir points:", 4.0),
            ("Fixed Weir Right Slope", "Default slope_R value for all fixed-weir points:", 4.0),
            ("Fixed Weir Roughness", "Default rough_cd value for all fixed-weir points:", 0.0),
        ]

        values = []
        for title, label, default_value in prompt_specs:
            value, ok = QInputDialog.getDouble(
                self.iface.mainWindow(),
                title,
                label,
                value=default_value,
                min=-1e12,
                max=1e12,
                decimals=6,
            )
            if not ok:
                return
            values.append(value)

        self._create_point_layer_from_polyline_vertices(
            line_layer=line_layer,
            output_name=f"{line_layer.name()}_weir_points",
            output_fields=[
                QgsField("weir_name", QVariant.String),
                QgsField("crest_lvl", QVariant.Double),
                QgsField("sill_hL", QVariant.Double),
                QgsField("sill_hR", QVariant.Double),
                QgsField("crest_w", QVariant.Double),
                QgsField("slope_L", QVariant.Double),
                QgsField("slope_R", QVariant.Double),
                QgsField("rough_cd", QVariant.Double),
            ],
            prompt_values=values,
            success_label="fixed-weir points",
        )

    def create_1d_network(self):
        """Create a 1D network NetCDF from branch lines, geometry nodes, and optional structures."""
        branch_layer = self._select_vector_layer_by_geometry(
            title="Create 1D Network",
            prompt="Select branch polyline layer:",
            geometry_type=QgsWkbTypes.LineGeometry,
            allow_none=False,
        )
        if branch_layer is None:
            return

        field_names = [field.name() for field in branch_layer.fields()]
        if not field_names:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Branch layer must contain at least one attribute field for branch names.",
            )
            return

        default_name_field = self._get_name_field(branch_layer)
        default_index = field_names.index(default_name_field) if default_name_field in field_names else 0
        branch_name_field, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Create 1D Network",
            "Select branch name field:",
            field_names,
            default_index,
            False,
        )
        if not ok or not branch_name_field:
            return

        branch_length_field = self._prompt_optional_field(
            title="Create 1D Network",
            prompt="Optional branch length field (imposed length):",
            field_names=field_names,
            default_field=None,
        )
        if branch_length_field is False:
            return

        geometry_nodes_layer = self._select_vector_layer_by_geometry(
            title="Create 1D Network",
            prompt="Select geometry nodes point layer:",
            geometry_type=QgsWkbTypes.PointGeometry,
            allow_none=False,
        )
        if geometry_nodes_layer is None:
            return

        node_field_names = [field.name() for field in geometry_nodes_layer.fields()]
        if not node_field_names:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Geometry nodes layer must contain a node-name attribute field.",
            )
            return

        default_node_field = self._get_name_field(geometry_nodes_layer)
        node_default_index = node_field_names.index(default_node_field) if default_node_field in node_field_names else 0
        node_name_field, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Create 1D Network",
            "Select geometry node name field:",
            node_field_names,
            node_default_index,
            False,
        )
        if not ok or not node_name_field:
            return

        spacing_m, ok = QInputDialog.getDouble(
            self.iface.mainWindow(),
            "Create 1D Network",
            "Constant spacing [m]:",
            value=50.0,
            min=0.000001,
            max=1e12,
            decimals=6,
        )
        if not ok:
            return

        special_layer = self._select_vector_layer_by_geometry(
            title="Create 1D Network",
            prompt="Optional structures points layer:",
            geometry_type=QgsWkbTypes.PointGeometry,
            allow_none=True,
        )
        if special_layer is False:
            return

        offset_m = 10.0
        snap_tolerance_m = 0.25
        if special_layer is not None:
            offset_m, ok = QInputDialog.getDouble(
                self.iface.mainWindow(),
                "Create 1D Network",
                "Structure offset distance [m] (+/- from closest mesh node):",
                value=10.0,
                min=0.0,
                max=1e12,
                decimals=6,
            )
            if not ok:
                return

            snap_tolerance_m, ok = QInputDialog.getDouble(
                self.iface.mainWindow(),
                "Create 1D Network",
                "Maximum snap distance [m] for structure points:",
                value=0.25,
                min=0.0,
                max=1e12,
                decimals=6,
            )
            if not ok:
                return

        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save 1D Network NetCDF",
            "",
            "NetCDF files (*.nc);;All Files (*)",
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".nc"):
            output_path = f"{output_path}.nc"

        try:
            result = self.create_1d_network_from_layers(
                branch_layer=branch_layer,
                branch_name_field=branch_name_field,
                spacing_m=spacing_m,
                geometry_nodes_layer=geometry_nodes_layer,
                node_name_field=node_name_field,
                output_path=output_path,
                branch_length_field=branch_length_field,
                structures_layer=special_layer,
                structure_offset_m=offset_m,
                structure_snap_tolerance_m=snap_tolerance_m,
                create_diagnostics_layer=True,
            )
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Failed to create 1D network: {exc}",
            )
            return

        mesh_data = result["mesh_data"]
        structure_constraints = result["structure_constraints"]
        accepted_special = sum(1 for item in structure_constraints if item.get("valid_flag", 0) == 1)
        rejected_special = sum(1 for item in structure_constraints if item.get("valid_flag", 0) != 1)
        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            (
                f"Created 1D network: branches={mesh_data['n_branches']}, nodes={mesh_data['n_nodes']}, "
                f"edges={mesh_data['n_edges']}, structures accepted={accepted_special}, "
                f"structures rejected={rejected_special}."
            ),
        )

    def _prompt_optional_field(self, title, prompt, field_names, default_field=None):
        """Prompt for an optional field and return selected field name or None."""
        labels = ["<None>"] + list(field_names)
        default_index = 0
        if default_field and default_field in field_names:
            default_index = labels.index(default_field)

        selected_label, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            title,
            prompt,
            labels,
            default_index,
            False,
        )
        if not ok:
            return False
        if selected_label == "<None>":
            return None
        return selected_label

    def create_1d_network_from_paths(
        self,
        branch_layer_path,
        branch_name_field,
        spacing_m,
        geometry_nodes_layer_path,
        node_name_field,
        output_path,
        branch_length_field=None,
        structures_layer_path=None,
        structure_offset_m=10.0,
        structure_snap_tolerance_m=0.25,
        log_path=None,
        create_diagnostics_layer=False,
    ):
        """Create a 1D network from file paths and write NetCDF and log outputs."""
        branch_layer = self._load_vector_layer_from_path(
            branch_layer_path,
            QgsWkbTypes.LineGeometry,
            "branch",
        )
        geometry_nodes_layer = self._load_vector_layer_from_path(
            geometry_nodes_layer_path,
            QgsWkbTypes.PointGeometry,
            "geometry nodes",
        )

        structures_layer = None
        if structures_layer_path:
            structures_layer = self._load_vector_layer_from_path(
                structures_layer_path,
                QgsWkbTypes.PointGeometry,
                "structures",
            )

        return self.create_1d_network_from_layers(
            branch_layer=branch_layer,
            branch_name_field=branch_name_field,
            spacing_m=spacing_m,
            geometry_nodes_layer=geometry_nodes_layer,
            node_name_field=node_name_field,
            output_path=output_path,
            branch_length_field=branch_length_field,
            structures_layer=structures_layer,
            structure_offset_m=structure_offset_m,
            structure_snap_tolerance_m=structure_snap_tolerance_m,
            log_path=log_path,
            create_diagnostics_layer=create_diagnostics_layer,
        )

    def _load_vector_layer_from_path(self, layer_path, geometry_type, label):
        """Load and validate a vector layer from disk."""
        layer = QgsVectorLayer(str(layer_path), os.path.basename(str(layer_path)), "ogr")
        if layer is None or not layer.isValid():
            raise RuntimeError(f"Could not load {label} layer from path: {layer_path}")
        if layer.geometryType() != geometry_type:
            raise RuntimeError(f"Layer '{layer_path}' is not a valid {label} geometry type.")
        return layer

    def create_1d_network_from_layers(
        self,
        branch_layer,
        branch_name_field,
        spacing_m,
        geometry_nodes_layer,
        node_name_field,
        output_path,
        branch_length_field=None,
        structures_layer=None,
        structure_offset_m=10.0,
        structure_snap_tolerance_m=0.25,
        log_path=None,
        create_diagnostics_layer=False,
    ):
        """Create a 1D network from QGIS layers and write NetCDF and log outputs."""
        if branch_layer is None or not branch_layer.isValid():
            raise RuntimeError("Branch layer is invalid.")
        if geometry_nodes_layer is None or not geometry_nodes_layer.isValid():
            raise RuntimeError("Geometry nodes layer is invalid.")
        if branch_name_field not in [field.name() for field in branch_layer.fields()]:
            raise RuntimeError(f"Branch name field '{branch_name_field}' is not present in branch layer.")
        if node_name_field not in [field.name() for field in geometry_nodes_layer.fields()]:
            raise RuntimeError(f"Node name field '{node_name_field}' is not present in geometry nodes layer.")
        if spacing_m is None or float(spacing_m) <= 0.0:
            raise RuntimeError("Spacing must be greater than zero.")
        if branch_length_field and branch_length_field not in [field.name() for field in branch_layer.fields()]:
            raise RuntimeError(f"Branch length field '{branch_length_field}' is not present in branch layer.")

        geometry_nodes = self._read_geometry_nodes_from_layer(geometry_nodes_layer, node_name_field)
        if not geometry_nodes:
            raise RuntimeError("No valid geometry nodes were found in the selected node layer.")

        branch_profiles, epsg = self._read_branch_profiles_from_line_layer(
            branch_layer=branch_layer,
            branch_name_field=branch_name_field,
            geometry_nodes=geometry_nodes,
            branch_length_field=branch_length_field,
        )
        if not branch_profiles:
            raise RuntimeError("No valid branches were found in the selected branch layer.")

        structure_constraints = []
        if structures_layer is not None:
            structure_constraints = self._collect_special_point_constraints(
                special_layer=structures_layer,
                branch_profiles=branch_profiles,
                snap_tolerance=structure_snap_tolerance_m,
            )
            if create_diagnostics_layer:
                self._create_special_points_diagnostics_layer(structures_layer, structure_constraints)

        mesh_data = self._build_mesh_from_profiles(
            branch_profiles=branch_profiles,
            spacing=float(spacing_m),
            special_constraints=structure_constraints,
            offset_distance=float(structure_offset_m),
        )
        if mesh_data is None or mesh_data.get("n_edges", 0) == 0:
            raise RuntimeError("Could not generate a valid 1D mesh. Check geometry and spacing.")

        self._write_1d_network_netcdf(output_path, mesh_data, epsg)

        if not log_path:
            log_path = os.path.splitext(output_path)[0] + ".log"
        self._write_1d_network_log(log_path, mesh_data)

        return {
            "mesh_data": mesh_data,
            "branch_profiles": branch_profiles,
            "structure_constraints": structure_constraints,
            "epsg": epsg,
            "log_path": log_path,
            "output_path": output_path,
        }

    def _select_vector_layer_by_geometry(self, title, prompt, geometry_type, allow_none=False):
        """Prompt user to select a vector layer by geometry type."""
        layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and layer.isValid()
            and layer.geometryType() == geometry_type
        ]

        labels = []
        if allow_none:
            labels.append("<None>")
        labels.extend(layer.name() for layer in layers)

        if not labels:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No compatible layers are loaded in the project.",
            )
            return None

        active_layer = self.iface.activeLayer()
        default_index = 0
        if active_layer in layers:
            default_index = labels.index(active_layer.name())

        selected_label, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            title,
            prompt,
            labels,
            default_index,
            False,
        )
        if not ok:
            return False if allow_none else None
        if allow_none and selected_label == "<None>":
            return None

        for layer in layers:
            if layer.name() == selected_label:
                return layer
        return None

    def _build_profile_from_points(self, points, name):
        """Build profile dictionary from an ordered point sequence."""
        if len(points) < 2:
            return None

        cleaned = []
        for x_val, y_val in points:
            x = float(x_val)
            y = float(y_val)
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            cleaned.append((x, y))
        if len(cleaned) < 2:
            return None

        cumlen = [0.0]
        for idx in range(1, len(cleaned)):
            x0, y0 = cleaned[idx - 1]
            x1, y1 = cleaned[idx]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            cumlen.append(cumlen[-1] + seg_len)

        if cumlen[-1] <= 0.0:
            return None

        return {
            "name": str(name),
            "points": cleaned,
            "cumlen": cumlen,
            "length": cumlen[-1],
        }

    def _read_geometry_nodes_from_layer(self, nodes_layer, node_name_field):
        """Read geometry nodes from point layer and enforce unique node names."""
        nodes = []
        used_names = set()

        for feature in nodes_layer.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue

            points = self._extract_points(geometry)
            if not points:
                continue

            point = points[0]
            x = float(point.x())
            y = float(point.y())
            if not (math.isfinite(x) and math.isfinite(y)):
                continue

            name_value = feature[node_name_field]
            node_name = str(name_value).strip() if name_value is not None else ""
            if not node_name:
                node_name = f"node_{feature.id()}"

            key = node_name.lower()
            if key in used_names:
                raise RuntimeError(f"Duplicate geometry node name encountered: '{node_name}'")

            used_names.add(key)
            nodes.append({
                "name": node_name,
                "x": x,
                "y": y,
            })

        return nodes

    def _nearest_geometry_node(self, xy, geometry_nodes):
        """Return nearest geometry node and distance to coordinate tuple (x, y)."""
        x, y = float(xy[0]), float(xy[1])
        best = None
        for node in geometry_nodes:
            dx = x - float(node["x"])
            dy = y - float(node["y"])
            dist = math.hypot(dx, dy)
            if best is None or dist < best["distance"]:
                best = {
                    "name": node["name"],
                    "x": float(node["x"]),
                    "y": float(node["y"]),
                    "distance": dist,
                }
        return best

    def _read_branch_profiles_from_line_layer(self, branch_layer, branch_name_field, geometry_nodes, branch_length_field=None):
        """Read branch profiles from a branch polyline layer."""
        profiles = []
        used_names = set()

        epsg = 28992
        try:
            crs = branch_layer.crs()
            if crs is not None and crs.isValid():
                authid = crs.authid() or ""
                match = re.search(r"(\d+)$", authid)
                if match:
                    epsg = int(match.group(1))
        except (AttributeError, RuntimeError):
            pass

        for feature in branch_layer.getFeatures():
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue

            base_name = str(feature[branch_name_field]).strip() if feature[branch_name_field] is not None else ""
            if not base_name:
                base_name = f"branch_{feature.id()}"

            polylines = self._extract_polylines(geometry)
            if not polylines:
                continue

            use_suffix = len(polylines) > 1
            for idx, polyline in enumerate(polylines, start=1):
                raw_name = f"{base_name}_{idx}" if use_suffix else base_name
                candidate = raw_name
                suffix = 2
                while candidate.lower() in used_names:
                    candidate = f"{raw_name}_{suffix}"
                    suffix += 1
                used_names.add(candidate.lower())

                profile = self._build_profile_from_points(
                    [(pt.x(), pt.y()) for pt in polyline],
                    candidate,
                )
                if profile is not None:
                    points = profile["points"]
                    start_raw = points[0]
                    end_raw = points[-1]

                    start_node = self._nearest_geometry_node(start_raw, geometry_nodes)
                    end_node = self._nearest_geometry_node(end_raw, geometry_nodes)
                    if start_node is None or end_node is None:
                        continue

                    snapped_points = list(points)
                    snapped_points[0] = (start_node["x"], start_node["y"])
                    snapped_points[-1] = (end_node["x"], end_node["y"])

                    snapped_profile = self._build_profile_from_points(snapped_points, candidate)
                    if snapped_profile is None:
                        continue

                    imposed_length = None
                    if branch_length_field:
                        raw_length = feature[branch_length_field]
                        try:
                            imposed = float(raw_length)
                            if math.isfinite(imposed) and imposed > 0.0:
                                imposed_length = imposed
                        except Exception:
                            imposed_length = None

                    snapped_profile["geometry_length"] = float(snapped_profile["length"])
                    snapped_profile["effective_length"] = float(imposed_length) if imposed_length is not None else float(snapped_profile["geometry_length"])
                    snapped_profile["imposed_length"] = imposed_length
                    snapped_profile["terminal_nodes"] = (start_node["name"], end_node["name"])
                    snapped_profile["terminal_snap_distances"] = (float(start_node["distance"]), float(end_node["distance"]))
                    snapped_profile["feature_id"] = feature.id()

                    profiles.append(snapped_profile)

        return profiles, epsg

    def _effective_chainage_to_geometry_chainage(self, profile, effective_chainage):
        """Map effective chainage to geometry chainage for interpolation on original geometry."""
        geometry_length = float(profile.get("geometry_length", profile.get("length", 0.0)))
        effective_length = float(profile.get("effective_length", geometry_length))
        if geometry_length <= 0.0 or effective_length <= 0.0:
            return None

        c_eff = float(effective_chainage)
        c_eff = max(0.0, min(effective_length, c_eff))
        ratio = c_eff / effective_length
        return ratio * geometry_length

    def _project_point_on_profile(self, point_xy, profile):
        """Project point to profile; return chainage, distance, projected xy."""
        px = float(point_xy.x())
        py = float(point_xy.y())
        points = profile.get("points", [])
        cumlen = profile.get("cumlen", [])

        if len(points) < 2 or len(cumlen) != len(points):
            return None

        best = None
        for idx in range(len(points) - 1):
            x0, y0 = points[idx]
            x1, y1 = points[idx + 1]
            dx = x1 - x0
            dy = y1 - y0
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq <= 0.0:
                continue

            t = ((px - x0) * dx + (py - y0) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            proj_x = x0 + t * dx
            proj_y = y0 + t * dy
            dist = math.hypot(px - proj_x, py - proj_y)
            chainage_geom = cumlen[idx] + t * math.sqrt(seg_len_sq)

            geometry_length = float(profile.get("geometry_length", profile.get("length", 0.0)))
            effective_length = float(profile.get("effective_length", geometry_length))
            if geometry_length > 0.0 and effective_length > 0.0:
                chainage_effective = (chainage_geom / geometry_length) * effective_length
            else:
                chainage_effective = chainage_geom

            if best is None or dist < best["distance"]:
                best = {
                    "chainage": chainage_effective,
                    "chainage_geometry": chainage_geom,
                    "distance": dist,
                    "x": proj_x,
                    "y": proj_y,
                }

        return best

    def _collect_special_point_constraints(self, special_layer, branch_profiles, snap_tolerance):
        """Collect snapped special-point constraints and computed chainages."""
        constraints = []
        features = list(special_layer.getFeatures())

        for feature in features:
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                constraints.append({
                    "feature_id": feature.id(),
                    "special_id": f"special_{feature.id()}",
                    "branch_name": "",
                    "chainage": None,
                    "snap_distance": None,
                    "valid_flag": 0,
                    "note": "empty geometry",
                    "point": None,
                })
                continue

            point = geom.asPoint()
            if point is None:
                constraints.append({
                    "feature_id": feature.id(),
                    "special_id": f"special_{feature.id()}",
                    "branch_name": "",
                    "chainage": None,
                    "snap_distance": None,
                    "valid_flag": 0,
                    "note": "non-point geometry",
                    "point": None,
                })
                continue

            best = None
            best_profile = None
            for profile in branch_profiles:
                projected = self._project_point_on_profile(point, profile)
                if projected is None:
                    continue
                if best is None or projected["distance"] < best["distance"]:
                    best = projected
                    best_profile = profile

            if best is None or best_profile is None:
                constraints.append({
                    "feature_id": feature.id(),
                    "special_id": f"special_{feature.id()}",
                    "branch_name": "",
                    "chainage": None,
                    "snap_distance": None,
                    "valid_flag": 0,
                    "note": "no branch found",
                    "point": point,
                })
                continue

            is_valid = 1 if best["distance"] <= float(snap_tolerance) else 0
            note = "ok" if is_valid else f"outside snap tolerance ({snap_tolerance:g} m)"
            constraints.append({
                "feature_id": feature.id(),
                "special_id": f"special_{feature.id()}",
                "branch_name": best_profile["name"],
                "chainage": float(best["chainage"]),
                "snap_distance": float(best["distance"]),
                "valid_flag": is_valid,
                "note": note,
                "point": QgsPointXY(float(best["x"]), float(best["y"])),
            })

        return constraints

    def _create_special_points_diagnostics_layer(self, source_layer, constraints):
        """Create diagnostics layer for special point branch/chainage attribution."""
        if not constraints:
            return

        crs_authid = "EPSG:28992"
        try:
            crs = source_layer.crs()
            if crs is not None and crs.isValid() and crs.authid():
                crs_authid = crs.authid()
        except (AttributeError, RuntimeError):
            pass

        layer_name = f"{source_layer.name()}_special_points_diagnostics"
        layer = QgsVectorLayer(f"Point?crs={crs_authid}", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("special_id", QVariant.String),
            QgsField("branchId", QVariant.String),
            QgsField("chainage_m", QVariant.Double),
            QgsField("snap_dist_m", QVariant.Double),
            QgsField("valid_flag", QVariant.Int),
            QgsField("note", QVariant.String),
        ])
        layer.updateFields()

        features = []
        for item in constraints:
            point = item.get("point")
            if point is None:
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(point))
            feature.setAttributes([
                item.get("special_id", ""),
                item.get("branch_name", ""),
                item.get("chainage"),
                item.get("snap_distance"),
                int(item.get("valid_flag", 0)),
                item.get("note", ""),
            ])
            features.append(feature)

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)

    def _generate_branch_chainages(self, profile, spacing, offset_distance, special_chainages):
        """Generate branch chainages from constant spacing and special-point offsets.
        
        Ensures that the imposed spacing is a minimum cell length:
        - All cells are >= spacing (no cell can be shorter than the imposed value)
        - If dividing evenly would create a short last cell, that cell is extended
        """
        length = float(profile.get("effective_length", profile.get("length", 0.0)))
        if length <= 0.0:
            return []

        chainages = [0.0]

        spacing = float(spacing)
        if spacing > 0.0:
            n_steps = int(math.floor(length / spacing))
            for step in range(1, n_steps + 1):
                c = step * spacing
                if c < length:
                    chainages.append(c)
            
            # Check if the last cell is too short (remainder < spacing)
            # If so, remove the last intermediate chainage to extend the previous cell
            if chainages[-1] > 0.0:  # Only if we have intermediate points
                remainder = length - chainages[-1]
                if 0.0 < remainder < spacing:
                    # Remove the last intermediate chainage, so it absorbs the remainder
                    chainages.pop()

        chainages.append(length)  # Always add the end point

        if special_chainages:
            offset_distance = float(offset_distance)
            for c in special_chainages:
                c = float(c)
                if 0.0 <= c <= length:
                    chainages.append(c)
                if offset_distance > 0.0:
                    c_up = c - offset_distance
                    c_dn = c + offset_distance
                    if 0.0 <= c_up <= length:
                        chainages.append(c_up)
                    if 0.0 <= c_dn <= length:
                        chainages.append(c_dn)

        chainages = sorted(chainages)
        deduped = []
        tolerance = 1e-6
        for c in chainages:
            if not deduped or abs(c - deduped[-1]) > tolerance:
                deduped.append(c)
        return deduped

    def _apply_structure_offsets_to_chainages(self, base_chainages, structure_chainages, offset_distance, branch_length):
        """Insert +/- offset chainages around the closest base mesh node to each structure."""
        chainages = list(base_chainages)
        if not base_chainages:
            return chainages

        offset = float(offset_distance)
        if offset <= 0.0:
            return chainages

        for structure_chainage in structure_chainages:
            target = float(structure_chainage)
            closest = min(base_chainages, key=lambda c: abs(float(c) - target))
            c_up = float(closest) - offset
            c_dn = float(closest) + offset
            if 0.0 <= c_up <= branch_length:
                chainages.append(c_up)
            if 0.0 <= c_dn <= branch_length:
                chainages.append(c_dn)

        chainages = sorted(chainages)
        deduped = []
        tolerance = 1e-6
        for c in chainages:
            if not deduped or abs(c - deduped[-1]) > tolerance:
                deduped.append(c)
        return deduped

    def _build_mesh_from_profiles(self, branch_profiles, spacing, special_constraints, offset_distance):
        """Build mesh node/edge arrays from branch profiles and optional constraints."""
        branch_special = {}
        for item in special_constraints or []:
            if int(item.get("valid_flag", 0)) != 1:
                continue
            branch_name = str(item.get("branch_name", "")).strip().lower()
            chainage = item.get("chainage")
            if not branch_name or chainage is None:
                continue
            branch_special.setdefault(branch_name, []).append(float(chainage))

        nodes = []
        edges = []
        edge_branch = []
        edge_offset = []
        edge_x = []
        edge_y = []
        branch_names = []
        geom_node_x = []
        geom_node_y = []
        geom_node_count = []
        branch_node_chainages = []
        branch_edge_chainages = []
        branch_geometry_lengths = []
        branch_effective_lengths = []

        node_index_by_key = {}
        terminal_node_index_by_name = {}
        key_tol = 1e-3

        for branch_idx, profile in enumerate(branch_profiles):
            branch_name = profile["name"]

            profile_points = profile.get("points", [])
            geom_node_count.append(len(profile_points))
            for x, y in profile_points:
                geom_node_x.append(float(x))
                geom_node_y.append(float(y))

            special_chainages = branch_special.get(branch_name.lower(), [])
            base_chainages = self._generate_branch_chainages(profile, spacing, 0.0, [])
            if not base_chainages:
                continue

            branch_length = float(profile.get("effective_length", profile.get("length", 0.0)))
            chainages = self._apply_structure_offsets_to_chainages(
                base_chainages=base_chainages,
                structure_chainages=special_chainages,
                offset_distance=offset_distance,
                branch_length=branch_length,
            )
            if len(chainages) < 2:
                continue

            branch_node_ids = []
            branch_node_entries = []
            terminal_names = profile.get("terminal_nodes", (None, None))
            for chainage_idx, chainage in enumerate(chainages):
                geom_chainage = self._effective_chainage_to_geometry_chainage(profile, chainage)
                if geom_chainage is None:
                    continue

                xy = self._interpolate_point_on_branch(profile, geom_chainage)
                if xy is None:
                    continue
                x, y = float(xy[0]), float(xy[1])
                key = (int(round(x / key_tol)), int(round(y / key_tol)))

                terminal_name = None
                if chainage_idx == 0:
                    terminal_name = terminal_names[0]
                elif chainage_idx == len(chainages) - 1:
                    terminal_name = terminal_names[1]

                node_id = None
                if terminal_name:
                    node_id = terminal_node_index_by_name.get(str(terminal_name).strip().lower())

                if node_id is None:
                    node_id = node_index_by_key.get(key)

                if node_id is None:
                    node_id = len(nodes)
                    nodes.append((x, y))
                    node_index_by_key[key] = node_id

                if terminal_name:
                    terminal_node_index_by_name[str(terminal_name).strip().lower()] = node_id

                branch_node_ids.append(node_id)
                branch_node_entries.append(
                    {
                        "node_id": int(node_id),
                        "chainage": float(chainage),
                        "geometry_chainage": float(geom_chainage),
                        "terminal_name": terminal_name or "",
                    }
                )

            if len(branch_node_ids) < 2:
                continue

            branch_names.append(branch_name)
            branch_geometry_lengths.append(float(profile.get("geometry_length", profile.get("length", 0.0))))
            branch_effective_lengths.append(float(profile.get("effective_length", profile.get("length", 0.0))))

            branch_edges_for_profile = []
            for idx in range(1, len(branch_node_ids)):
                start_node = int(branch_node_ids[idx - 1])
                end_node = int(branch_node_ids[idx])
                if start_node == end_node:
                    continue
                edges.append((start_node, end_node))
                edge_branch.append(len(branch_names) - 1)
                c0 = float(branch_node_entries[idx - 1]["chainage"])
                c1 = float(branch_node_entries[idx]["chainage"])
                edge_offset.append(0.5 * (c0 + c1))
                x0, y0 = nodes[start_node]
                x1, y1 = nodes[end_node]
                edge_x.append(0.5 * (float(x0) + float(x1)))
                edge_y.append(0.5 * (float(y0) + float(y1)))
                branch_edges_for_profile.append(
                    {
                        "start_node": start_node,
                        "end_node": end_node,
                        "start_chainage": c0,
                        "end_chainage": c1,
                    }
                )

            branch_node_chainages.append(
                {
                    "branch_name": branch_name,
                    "entries": branch_node_entries,
                    "geometry_length": float(profile.get("geometry_length", profile.get("length", 0.0))),
                    "effective_length": float(profile.get("effective_length", profile.get("length", 0.0))),
                    "imposed_length": profile.get("imposed_length"),
                    "terminal_nodes": profile.get("terminal_nodes", ("", "")),
                    "terminal_snap_distances": profile.get("terminal_snap_distances", (None, None)),
                }
            )
            branch_edge_chainages.append({"branch_name": branch_name, "entries": branch_edges_for_profile})

        if not nodes or not edges:
            return None

        node_x = [xy[0] for xy in nodes]
        node_y = [xy[1] for xy in nodes]
        node_ids = [f"node_{idx + 1}" for idx in range(len(nodes))]

        mesh1d_node_branch = [-1] * len(nodes)
        mesh1d_node_offset = [0.0] * len(nodes)
        for branch_idx, branch_info in enumerate(branch_node_chainages):
            for entry in branch_info.get("entries", []):
                node_id = int(entry["node_id"])
                if mesh1d_node_branch[node_id] < 0:
                    mesh1d_node_branch[node_id] = branch_idx
                    mesh1d_node_offset[node_id] = float(entry["chainage"])

        network_node_names = []
        network_node_x = []
        network_node_y = []
        network_node_index_by_name = {}

        def _get_or_create_network_node(node_name, mesh_node_id):
            key = str(node_name or "").strip().lower()
            if not key:
                key = f"network_node_{len(network_node_names) + 1}"
            if key in network_node_index_by_name:
                return network_node_index_by_name[key]

            idx = len(network_node_names)
            network_node_index_by_name[key] = idx
            network_node_names.append(str(node_name) if node_name else f"network_node_{idx + 1}")
            network_node_x.append(float(node_x[int(mesh_node_id)]))
            network_node_y.append(float(node_y[int(mesh_node_id)]))
            return idx

        network_edge_nodes = []
        network_branch_order = []
        network_branch_type = []
        for branch_idx, branch_info in enumerate(branch_node_chainages):
            entries = branch_info.get("entries", [])
            if len(entries) < 2:
                continue

            terminal_nodes = branch_info.get("terminal_nodes", ("", ""))
            n0 = _get_or_create_network_node(terminal_nodes[0], entries[0]["node_id"])
            n1 = _get_or_create_network_node(terminal_nodes[1], entries[-1]["node_id"])
            network_edge_nodes.append((n0, n1))
            network_branch_order.append(branch_idx + 1)
            network_branch_type.append(1)

        return {
            "node_x": node_x,
            "node_y": node_y,
            "node_ids": node_ids,
            "mesh1d_node_branch": mesh1d_node_branch,
            "mesh1d_node_offset": mesh1d_node_offset,
            "edges": edges,
            "edge_branch": edge_branch,
            "edge_offset": edge_offset,
            "edge_x": edge_x,
            "edge_y": edge_y,
            "branch_names": branch_names,
            "network_branch_order": network_branch_order,
            "network_branch_type": network_branch_type,
            "network_edge_nodes": network_edge_nodes,
            "network_edge_length": branch_effective_lengths,
            "network_node_names": network_node_names,
            "network_node_x": network_node_x,
            "network_node_y": network_node_y,
            "geom_node_x": geom_node_x,
            "geom_node_y": geom_node_y,
            "geom_node_count": geom_node_count,
            "branch_node_chainages": branch_node_chainages,
            "branch_edge_chainages": branch_edge_chainages,
            "n_nodes": len(node_x),
            "n_edges": len(edges),
            "n_branches": len(branch_names),
        }

    def _write_1d_network_log(self, log_path, mesh_data):
        """Write detailed 1D network creation diagnostics to a text log."""
        branch_nodes = mesh_data.get("branch_node_chainages", [])
        branch_edges = mesh_data.get("branch_edge_chainages", [])

        node_to_branches = {}
        for branch_info in branch_nodes:
            branch_name = branch_info.get("branch_name", "")
            for entry in branch_info.get("entries", []):
                node_id = int(entry.get("node_id", -1))
                if node_id < 0:
                    continue
                node_to_branches.setdefault(node_id, set()).add(branch_name)

        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("1D Network Creation Log\n")
            handle.write("=======================\n\n")
            handle.write(f"mesh1d_nodes={mesh_data.get('n_nodes', 0)}\n")
            handle.write(f"mesh1d_edges={mesh_data.get('n_edges', 0)}\n")
            handle.write(f"branches={mesh_data.get('n_branches', 0)}\n\n")

            handle.write("Branch Lengths\n")
            handle.write("--------------\n")
            for branch_info in branch_nodes:
                imposed = branch_info.get("imposed_length")
                imposed_text = f"{float(imposed):.6f}" if imposed is not None else "<none>"
                handle.write(
                    f"{branch_info.get('branch_name', '')}: imposed={imposed_text}, "
                    f"geometry={float(branch_info.get('geometry_length', 0.0)):.6f}, "
                    f"effective={float(branch_info.get('effective_length', 0.0)):.6f}\n"
                )

            handle.write("\nNode-Branch Connectivity\n")
            handle.write("------------------------\n")
            for node_id in sorted(node_to_branches.keys()):
                connected = sorted(node_to_branches[node_id])
                handle.write(f"node_{node_id + 1}: {', '.join(connected)}\n")

            handle.write("\nBranch Node Chainages\n")
            handle.write("---------------------\n")
            for branch_info in branch_nodes:
                handle.write(f"[{branch_info.get('branch_name', '')}]\n")
                terminal_nodes = branch_info.get("terminal_nodes", ("", ""))
                terminal_snaps = branch_info.get("terminal_snap_distances", (None, None))
                handle.write(
                    f"terminal_nodes={terminal_nodes[0]}|{terminal_nodes[1]}, "
                    f"terminal_snap_distances={terminal_snaps[0]}|{terminal_snaps[1]}\n"
                )
                for entry in branch_info.get("entries", []):
                    handle.write(
                        f"node_{int(entry['node_id']) + 1}: chainage={float(entry['chainage']):.6f}, "
                        f"geometry_chainage={float(entry['geometry_chainage']):.6f}, "
                        f"terminal={entry.get('terminal_name', '')}\n"
                    )

            handle.write("\nBranch Edge Chainages\n")
            handle.write("---------------------\n")
            for branch_info in branch_edges:
                handle.write(f"[{branch_info.get('branch_name', '')}]\n")
                for entry in branch_info.get("entries", []):
                    handle.write(
                        f"node_{int(entry['start_node']) + 1}->node_{int(entry['end_node']) + 1}: "
                        f"chainage={float(entry['start_chainage']):.6f}->{float(entry['end_chainage']):.6f}\n"
                    )

    def _write_netcdf_string_array(self, nc_dataset, var_name, dim_name, values, strlen_dim=None):
        """Write list of strings to a NetCDF fixed-length char array variable."""
        import numpy as np

        normalized_values = []
        for value in values:
            if value is None:
                normalized_values.append("")
                continue
            if isinstance(value, (bytes, np.bytes_)):
                normalized_values.append(value.decode("utf-8", errors="replace"))
                continue
            normalized_values.append(str(value))

        values = normalized_values
        max_len = max(1, max(len(v) for v in values) if values else 1)
        strlen_dim = strlen_dim or f"{dim_name}_strlen"
        if strlen_dim not in nc_dataset.dimensions:
            nc_dataset.createDimension(strlen_dim, max_len)
        elif len(nc_dataset.dimensions[strlen_dim]) < max_len:
            raise RuntimeError(f"Dimension '{strlen_dim}' is too small for values.")

        target_len = len(nc_dataset.dimensions[strlen_dim])

        # Store char arrays as (nValues, strlen) so NetCDF decoders (MATLAB ncread,
        # netCDF4.chartostring) interpret each row as one string.
        var = nc_dataset.createVariable(var_name, "S1", (dim_name, strlen_dim))
        if values:
            char_matrix = np.full((len(values), target_len), b" ", dtype="S1")
            for idx, value in enumerate(values):
                encoded = value.encode("utf-8", errors="replace")[:target_len]
                if not encoded:
                    continue
                row = np.frombuffer(encoded, dtype="S1")
                char_matrix[idx, : len(row)] = row
            var[:, :] = char_matrix
        return var

    def _write_1d_network_netcdf(self, output_path, mesh_data, epsg):
        """Write generated 1D network and mesh arrays to Delft3D-compatible UGRID 1D NetCDF."""
        try:
            import netCDF4 as nc
            import numpy as np
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS."
            ) from exc

        with nc.Dataset(output_path, "w", format="NETCDF3_CLASSIC") as ds:
            network_nEdges = len(mesh_data.get("network_edge_nodes", []))
            network_nNodes = len(mesh_data.get("network_node_x", []))
            network_nGeometryNodes = len(mesh_data.get("geom_node_x", []))
            mesh1d_nNodes = mesh_data["n_nodes"]
            mesh1d_nEdges = mesh_data["n_edges"]

            ds.createDimension("network_nEdges", network_nEdges)
            ds.createDimension("network_nNodes", network_nNodes)
            ds.createDimension("network_nGeometryNodes", network_nGeometryNodes)
            ds.createDimension("mesh1d_nNodes", mesh1d_nNodes)
            ds.createDimension("mesh1d_nEdges", mesh1d_nEdges)
            ds.createDimension("strLengthIds", 40)
            ds.createDimension("strLengthLongNames", 80)
            ds.createDimension("Two", 2)

            network_var = ds.createVariable("network", "i4")
            network_edge_nodes_var = ds.createVariable("network_edge_nodes", "i4", ("network_nEdges", "Two"))
            network_edge_length_var = ds.createVariable("network_edge_length", "f8", ("network_nEdges",))
            network_node_x_var = ds.createVariable("network_node_x", "f8", ("network_nNodes",))
            network_node_y_var = ds.createVariable("network_node_y", "f8", ("network_nNodes",))

            network_geometry_var = ds.createVariable("network_geometry", "i4")
            network_geom_node_count_var = ds.createVariable("network_geom_node_count", "i4", ("network_nEdges",))
            network_geom_x_var = ds.createVariable("network_geom_x", "f8", ("network_nGeometryNodes",))
            network_geom_y_var = ds.createVariable("network_geom_y", "f8", ("network_nGeometryNodes",))
            network_branch_order_var = ds.createVariable("network_branch_order", "i4", ("network_nEdges",))
            network_branch_type_var = ds.createVariable("network_branch_type", "i4", ("network_nEdges",))

            node_x_var = ds.createVariable("mesh1d_node_x", "f8", ("mesh1d_nNodes",))
            node_y_var = ds.createVariable("mesh1d_node_y", "f8", ("mesh1d_nNodes",))
            edge_nodes_var = ds.createVariable("mesh1d_edge_nodes", "i4", ("mesh1d_nEdges", "Two"))
            edge_branch_var = ds.createVariable("mesh1d_edge_branch", "i4", ("mesh1d_nEdges",))
            node_branch_var = ds.createVariable("mesh1d_node_branch", "i4", ("mesh1d_nNodes",))
            node_offset_var = ds.createVariable("mesh1d_node_offset", "f8", ("mesh1d_nNodes",))
            edge_offset_var = ds.createVariable("mesh1d_edge_offset", "f8", ("mesh1d_nEdges",))
            edge_x_var = ds.createVariable("mesh1d_edge_x", "f8", ("mesh1d_nEdges",))
            edge_y_var = ds.createVariable("mesh1d_edge_y", "f8", ("mesh1d_nEdges",))
            projected_crs = ds.createVariable("projected_coordinate_system", "i4")

            network_var.assignValue(1)
            network_geometry_var.assignValue(1)

            network_edge_nodes_var[:, :] = np.asarray(mesh_data.get("network_edge_nodes", []), dtype=np.int32)
            network_edge_length_var[:] = np.asarray(mesh_data.get("network_edge_length", []), dtype=float)
            network_node_x_var[:] = np.asarray(mesh_data.get("network_node_x", []), dtype=float)
            network_node_y_var[:] = np.asarray(mesh_data.get("network_node_y", []), dtype=float)
            network_geom_node_count_var[:] = np.asarray(mesh_data["geom_node_count"], dtype=np.int32)
            network_geom_x_var[:] = np.asarray(mesh_data["geom_node_x"], dtype=float)
            network_geom_y_var[:] = np.asarray(mesh_data["geom_node_y"], dtype=float)
            network_branch_order_var[:] = np.asarray(mesh_data.get("network_branch_order", []), dtype=np.int32)
            network_branch_type_var[:] = np.asarray(mesh_data.get("network_branch_type", []), dtype=np.int32)

            network_branch_id_var = self._write_netcdf_string_array(
                ds,
                "network_branch_id",
                "network_nEdges",
                mesh_data["branch_names"],
                strlen_dim="strLengthIds",
            )
            network_branch_long_name_var = self._write_netcdf_string_array(
                ds,
                "network_branch_long_name",
                "network_nEdges",
                mesh_data["branch_names"],
                strlen_dim="strLengthLongNames",
            )
            network_node_id_var = self._write_netcdf_string_array(
                ds,
                "network_node_id",
                "network_nNodes",
                mesh_data.get("network_node_names", []),
                strlen_dim="strLengthIds",
            )
            network_node_long_name_var = self._write_netcdf_string_array(
                ds,
                "network_node_long_name",
                "network_nNodes",
                mesh_data.get("network_node_names", []),
                strlen_dim="strLengthLongNames",
            )

            node_x_var[:] = np.asarray(mesh_data["node_x"], dtype=float)
            node_y_var[:] = np.asarray(mesh_data["node_y"], dtype=float)
            edge_nodes_var[:, :] = np.asarray(mesh_data["edges"], dtype=np.int32)
            edge_branch_var[:] = np.asarray(mesh_data["edge_branch"], dtype=np.int32)
            node_branch_var[:] = np.asarray(mesh_data.get("mesh1d_node_branch", []), dtype=np.int32)
            node_offset_var[:] = np.asarray(mesh_data.get("mesh1d_node_offset", []), dtype=float)
            edge_offset_var[:] = np.asarray(mesh_data.get("edge_offset", []), dtype=float)
            edge_x_var[:] = np.asarray(mesh_data.get("edge_x", []), dtype=float)
            edge_y_var[:] = np.asarray(mesh_data.get("edge_y", []), dtype=float)
            mesh_node_id_var = self._write_netcdf_string_array(
                ds,
                "mesh1d_node_id",
                "mesh1d_nNodes",
                mesh_data["node_ids"],
                strlen_dim="strLengthIds",
            )
            mesh_node_long_name_var = self._write_netcdf_string_array(
                ds,
                "mesh1d_node_long_name",
                "mesh1d_nNodes",
                mesh_data["node_ids"],
                strlen_dim="strLengthLongNames",
            )

            projected_crs.assignValue(int(epsg))
            projected_crs.epsg = int(epsg)
            projected_crs.EPSG_code = int(epsg)

            network_var.cf_role = "mesh_topology"
            network_var.long_name = "Topology data of 1D network"
            network_var.edge_dimension = "network_nEdges"
            network_var.edge_geometry = "network_geometry"
            network_var.edge_node_connectivity = "network_edge_nodes"
            network_var.node_coordinates = "network_node_x network_node_y"
            network_var.node_dimension = "network_nNodes"
            network_var.topology_dimension = 1
            network_var.node_id = "network_node_id"
            network_var.node_long_name = "network_node_long_name"
            network_var.branch_id = "network_branch_id"
            network_var.branch_long_name = "network_branch_long_name"
            network_var.edge_length = "network_edge_length"

            network_edge_nodes_var.cf_role = "edge_node_connectivity"
            network_edge_nodes_var.long_name = "Start and end nodes of network edges"
            network_edge_nodes_var.start_index = 0
            network_branch_id_var.long_name = "ID of branch geometries"
            network_branch_long_name_var.long_name = "Long name of branch geometries"
            network_edge_length_var.long_name = "Real length of branch geometries"
            network_edge_length_var.units = "m"
            network_node_id_var.long_name = "ID of network nodes"
            network_node_long_name_var.long_name = "Long name of network nodes"
            network_node_x_var.units = "m"
            network_node_x_var.standard_name = "projection_x_coordinate"
            network_node_x_var.long_name = "x-coordinate of network nodes"
            network_node_y_var.units = "m"
            network_node_y_var.standard_name = "projection_y_coordinate"
            network_node_y_var.long_name = "y-coordinate of network nodes"

            network_geometry_var.geometry_type = "line"
            network_geometry_var.long_name = "1D Geometry"
            network_geometry_var.node_count = "network_geom_node_count"
            network_geometry_var.node_coordinates = "network_geom_x network_geom_y"
            network_geom_node_count_var.long_name = "Number of geometry nodes per branch"
            network_geom_x_var.units = "m"
            network_geom_x_var.standard_name = "projection_x_coordinate"
            network_geom_x_var.long_name = "x-coordinate of branch geometry nodes"
            network_geom_y_var.units = "m"
            network_geom_y_var.standard_name = "projection_y_coordinate"
            network_geom_y_var.long_name = "y-coordinate of branch geometry nodes"
            network_branch_order_var.long_name = "Order of branches for interpolation"
            network_branch_order_var.mesh = "network"
            network_branch_order_var.location = "edge"
            network_branch_type_var.long_name = "Type of branches"
            network_branch_type_var.mesh = "network"
            network_branch_type_var.location = "edge"
            mesh_topology = ds.createVariable("mesh1d", "i4")
            mesh_topology.cf_role = "mesh_topology"
            mesh_topology.long_name = "Topology data of 1D mesh"
            mesh_topology.topology_dimension = 1
            mesh_topology.coordinate_space = "network"
            mesh_topology.edge_node_connectivity = "mesh1d_edge_nodes"
            mesh_topology.node_dimension = "mesh1d_nNodes"
            mesh_topology.edge_dimension = "mesh1d_nEdges"
            mesh_topology.node_coordinates = "mesh1d_node_branch mesh1d_node_offset mesh1d_node_x mesh1d_node_y"
            mesh_topology.edge_coordinates = "mesh1d_edge_branch mesh1d_edge_offset mesh1d_edge_x mesh1d_edge_y"
            mesh_topology.node_id = "mesh1d_node_id"
            mesh_topology.node_long_name = "mesh1d_node_long_name"

            edge_nodes_var.cf_role = "edge_node_connectivity"
            edge_nodes_var.long_name = "Start and end nodes of mesh edges"
            edge_nodes_var.start_index = 0
            edge_branch_var.long_name = "Index of branch on which mesh edges are located"
            edge_branch_var.start_index = 0
            node_branch_var.long_name = "Index of branch on which mesh nodes are located"
            node_branch_var.start_index = 0
            node_offset_var.long_name = "Offset along branch of mesh nodes"
            node_offset_var.units = "m"
            edge_offset_var.long_name = "Offset along branch of mesh edges"
            edge_offset_var.units = "m"
            node_x_var.units = "m"
            node_x_var.standard_name = "projection_x_coordinate"
            node_x_var.long_name = "x-coordinate of mesh nodes"
            node_y_var.units = "m"
            node_y_var.standard_name = "projection_y_coordinate"
            node_y_var.long_name = "y-coordinate of mesh nodes"
            edge_x_var.units = "m"
            edge_x_var.standard_name = "projection_x_coordinate"
            edge_x_var.long_name = "Characteristic x-coordinate of the mesh edge (e.g. midpoint)"
            edge_y_var.units = "m"
            edge_y_var.standard_name = "projection_y_coordinate"
            edge_y_var.long_name = "Characteristic y-coordinate of the mesh edge (e.g. midpoint)"

            ds.institution = "Deltares"
            ds.references = "https://github.com/ugrid-conventions/ugrid-conventions"
            ds.source = "Delft3DFileManager create_1d_network"
            ds.history = "Created by Delft3DFileManager"
            ds.Conventions = "CF-1.8 UGRID-1.0 Deltares-0.10"

    

    def _read_mesh_edge_coordinates(self, mesh_path):
        """Read mesh edge coordinate arrays and return (x, y, epsg)."""
        import numpy as np

        try:
            import netCDF4 as nc
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The 'netCDF4' package is required. Use 'Install Python Dependencies' and restart QGIS."
            ) from exc

        with nc.Dataset(mesh_path, "r") as ds:
            edge_x_var, edge_y_var = self._detect_edge_coordinate_vars(ds)

            raw_x = ds.variables[edge_x_var][:]
            raw_y = ds.variables[edge_y_var][:]

            if isinstance(raw_x, np.ma.MaskedArray):
                raw_x = raw_x.filled(np.nan)
            if isinstance(raw_y, np.ma.MaskedArray):
                raw_y = raw_y.filled(np.nan)

            edge_x = np.asarray(raw_x, dtype=float).ravel()
            edge_y = np.asarray(raw_y, dtype=float).ravel()

            if edge_x.shape[0] != edge_y.shape[0]:
                raise ValueError(
                    f"Edge coordinate sizes differ ({edge_x.shape[0]} vs {edge_y.shape[0]})."
                )

            valid = np.isfinite(edge_x) & np.isfinite(edge_y)
            edge_x = edge_x[valid]
            edge_y = edge_y[valid]

            epsg = self._read_epsg_from_nc(ds)

        return edge_x, edge_y, epsg

    def _detect_edge_coordinate_vars(self, nc_dataset):
        """Detect edge coordinate variable names (x/y) in a UGRID dataset."""
        direct_x = "mesh2d_edge_x"
        direct_y = "mesh2d_edge_y"
        if direct_x in nc_dataset.variables and direct_y in nc_dataset.variables:
            return direct_x, direct_y

        topology_var = None
        for vname, variable in nc_dataset.variables.items():
            if getattr(variable, "cf_role", "") == "mesh_topology":
                topology_var = variable
                break

        if topology_var is not None:
            edge_coordinates = getattr(topology_var, "edge_coordinates", "").split()
            if len(edge_coordinates) >= 2:
                candidate_x = edge_coordinates[0]
                candidate_y = edge_coordinates[1]
                if (
                    candidate_x in nc_dataset.variables
                    and candidate_y in nc_dataset.variables
                ):
                    return candidate_x, candidate_y

        edge_x_var = None
        edge_y_var = None
        for vname in nc_dataset.variables:
            lname = vname.lower()
            if edge_x_var is None and "edge" in lname and lname.endswith("_x"):
                edge_x_var = vname
            if edge_y_var is None and "edge" in lname and lname.endswith("_y"):
                edge_y_var = vname

        if edge_x_var and edge_y_var:
            return edge_x_var, edge_y_var

        raise ValueError(
            "Could not find edge coordinate variables. Expected 'mesh2d_edge_x' and 'mesh2d_edge_y'."
        )

    def _read_epsg_from_nc(self, nc_dataset):
        """Try to read an EPSG code from variables in a NetCDF dataset."""
        def _parse_epsg(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                code = int(value)
                return code if code > 0 else None

            text = str(value).strip()
            matches = re.findall(r"\d+", text)
            for match in reversed(matches):
                code = int(match)
                if code > 0:
                    return code
            return None

        for vname in nc_dataset.variables:
            variable = nc_dataset[vname]
            for attr_name in ("EPSG_code", "epsg", "EPSG"):
                value = getattr(variable, attr_name, None)
                code = _parse_epsg(value)
                if code is not None:
                    return code
        return None

    def _create_trachytopes_layer(self, layer_name, edge_x, edge_y, epsg):
        """Create and populate a trachytopes point layer."""
        layer = QgsVectorLayer(f"Point?crs=EPSG:{epsg}", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("x", QVariant.Double),
                QgsField("y", QVariant.Double),
                QgsField("trachytope_number", QVariant.Int),
                QgsField("fraction", QVariant.Double),
            ]
        )
        layer.updateFields()

        features = []
        for x_coord, y_coord in zip(edge_x, edge_y):
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x_coord), float(y_coord))))
            feat.setAttributes([float(x_coord), float(y_coord), 0, 0.0])
            features.append(feat)

        provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Created trachytopes layer '{layer_name}' with {layer.featureCount()} point(s)",
        )

    def set_trachytopes_in_polygons(self):
        """Set trachytope values for points inside polygons."""
        point_layer = self.iface.activeLayer()
        if point_layer is None or point_layer.type() != QgsMapLayerType.VectorLayer:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Select a trachytopes point layer as active layer first.",
            )
            return
        if point_layer.geometryType() != QgsWkbTypes.PointGeometry:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Active layer must be a point layer.",
            )
            return

        field_names = [field.name() for field in point_layer.fields()]
        required_fields = ["x", "y", "trachytope_number", "fraction"]
        missing = [name for name in required_fields if name not in field_names]
        if missing:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Active point layer is not a trachytopes layer. Missing fields: "
                + ", ".join(missing),
            )
            return

        polygon_layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ]
        if not polygon_layers:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No polygon layers found in the project.",
            )
            return

        labels = [layer.name() for layer in polygon_layers]
        selected_label, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Polygon Layer",
            "Polygon layer used for assignment:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        polygon_layer = polygon_layers[labels.index(selected_label)]

        trachytope_number, ok = QInputDialog.getInt(
            self.iface.mainWindow(),
            "Trachytope Number",
            "Value for trachytope_number:",
            value=0,
            min=-2147483648,
            max=2147483647,
        )
        if not ok:
            return

        fraction, ok = QInputDialog.getDouble(
            self.iface.mainWindow(),
            "Fraction",
            "Value for fraction:",
            value=0.0,
            min=-1e12,
            max=1e12,
            decimals=6,
        )
        if not ok:
            return

        polygon_features = list(polygon_layer.getSelectedFeatures())
        if not polygon_features:
            polygon_features = list(polygon_layer.getFeatures())
        if not polygon_features:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Selected polygon layer has no features.",
            )
            return

        index = QgsSpatialIndex()
        polygon_geometries = {}
        for feature in polygon_features:
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue
            index.addFeature(feature)
            polygon_geometries[feature.id()] = geometry

        if not polygon_geometries:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Polygon layer contains no valid geometries.",
            )
            return

        idx_trachytope = point_layer.fields().indexOf("trachytope_number")
        idx_fraction = point_layer.fields().indexOf("fraction")

        started_edit = False
        if not point_layer.isEditable():
            started_edit = point_layer.startEditing()
            if not started_edit:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    "Could not start edit mode on active trachytopes layer.",
                )
                return

        changed = 0
        for point_feature in point_layer.getFeatures():
            point_geometry = point_feature.geometry()
            if not point_geometry or point_geometry.isEmpty():
                continue

            bbox = point_geometry.boundingBox()
            candidate_ids = index.intersects(bbox)
            if not candidate_ids:
                continue

            inside_polygon = False
            for candidate_id in candidate_ids:
                polygon_geometry = polygon_geometries.get(candidate_id)
                if polygon_geometry is not None and polygon_geometry.contains(point_geometry):
                    inside_polygon = True
                    break

            if not inside_polygon:
                continue

            point_layer.changeAttributeValue(point_feature.id(), idx_trachytope, trachytope_number)
            point_layer.changeAttributeValue(point_feature.id(), idx_fraction, float(fraction))
            changed += 1

        if started_edit:
            if not point_layer.commitChanges():
                point_layer.rollBack()
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    "Could not commit attribute updates.",
                )
                return

        if changed == 0:
            self.iface.messageBar().pushWarning(
                "Delft3D File Manager",
                "No trachytopes points were inside the selected polygon(s)",
            )
            return

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Updated {changed} trachytopes point(s)",
        )

    def export_trachytopes_arl(self):
        """Export active trachytopes point layer to ASCII .arl with space separator."""
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Select a trachytopes point layer first.",
            )
            return
        if layer.geometryType() != QgsWkbTypes.PointGeometry:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "Active layer must be a point layer.",
            )
            return

        for field_name in ("x", "y", "trachytope_number", "fraction"):
            if layer.fields().indexOf(field_name) < 0:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Delft3D File Manager",
                    f"Active layer is missing required field '{field_name}'.",
                )
                return

        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Export trachytopes ARL",
            "",
            "ARL files (*.arl);;All files (*)",
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".arl"):
            output_path = output_path + ".arl"

        idx_x = layer.fields().indexOf("x")
        idx_y = layer.fields().indexOf("y")
        idx_trachytope = layer.fields().indexOf("trachytope_number")
        idx_fraction = layer.fields().indexOf("fraction")

        exported = 0
        with open(output_path, "w", encoding="ascii") as handle:
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if geometry is None or geometry.isEmpty():
                    continue

                x_value = feature.attributes()[idx_x]
                y_value = feature.attributes()[idx_y]
                if x_value is None or y_value is None:
                    point = geometry.asPoint()
                    x_value = point.x()
                    y_value = point.y()

                trachytope_number = feature.attributes()[idx_trachytope]
                fraction = feature.attributes()[idx_fraction]

                try:
                    x_float = float(x_value)
                    y_float = float(y_value)
                    number_int = int(trachytope_number)
                    fraction_float = float(fraction)
                except (TypeError, ValueError):
                    continue

                if not (math.isfinite(x_float) and math.isfinite(y_float) and math.isfinite(fraction_float)):
                    continue
                if number_int == 0:
                    continue

                handle.write(
                    f"{x_float:.6f} {y_float:.6f} 0 {number_int} {fraction_float:.6f}\n"
                )
                exported += 1

        if exported == 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                "No trachytopes points with non-zero trachytope_number were exported.",
            )
            return

        self.iface.messageBar().pushSuccess(
            "Delft3D File Manager",
            f"Exported {exported} trachytopes point(s) to {os.path.basename(output_path)}",
        )

    def open_bed_level_dialog(self):
        """Open the Write Bed Level to Mesh dialog."""
        try:
            from .bed_level_dialog import BedLevelDialog
        except ImportError as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Could not load the bed level dialog:\n{exc}\n\n"
                "Make sure 'netCDF4' is installed in the QGIS Python environment.",
            )
            return
        if self._bed_level_dialog is None:
            self._bed_level_dialog = BedLevelDialog(self.iface, self.iface.mainWindow())

        self._bed_level_dialog.show()
        self._bed_level_dialog.raise_()
        self._bed_level_dialog.activateWindow()

    def install_dependencies(self):
        """Install required Python packages in the QGIS interpreter."""
        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Install Dependencies",
            "This will run pip in the QGIS Python environment to install:\n"
            "- netCDF4\n- pyproj\n- scipy\n- defusedxml\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            missing = []
            for package in self._required_packages:
                module_name = "netCDF4" if package == "netCDF4" else package
                try:
                    importlib.import_module(module_name)
                except Exception:
                    missing.append(package)

            if not missing:
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "Dependencies",
                    "All required dependencies are already installed.",
                )
                return

            result = self._run_pip_install(missing)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                if len(err) > 1200:
                    err = err[-1200:]
                pip_python = self._get_python_executable_for_pip()
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Dependency installation failed",
                    "Could not install Python packages with pip.\n\n"
                    "Command:\n"
                    f"{pip_python} -m pip install {' '.join(missing)}\n\n"
                    "Error:\n"
                    f"{err}",
                )
                return

            self.iface.messageBar().pushSuccess(
                "Delft3D File Manager",
                "Dependencies installed successfully. Please restart QGIS.",
            )
            QMessageBox.information(
                self.iface.mainWindow(),
                "Dependencies installed",
                "Dependencies installed successfully.\n\n"
                "Please restart QGIS before running bed level interpolation.",
            )
        finally:
            QApplication.restoreOverrideCursor()

    def _run_pip_install(self, packages):
        """Run pip install in QGIS Python; bootstrap pip if missing."""
        allowed = set(self._required_packages)
        unexpected = [p for p in packages if p not in allowed]
        if unexpected:
            raise ValueError(f"Refusing to install unlisted package(s): {unexpected!r}")
        python_exe = self._get_python_executable_for_pip()
        cmd = [python_exe, "-m", "pip", "install"] + list(packages)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result

        # Try to bootstrap pip when not available, then retry once.
        ensurepip_result = subprocess.run(
            [python_exe, "-m", "ensurepip", "--upgrade"],
            capture_output=True,
            text=True,
        )
        if ensurepip_result.returncode == 0:
            return subprocess.run(cmd, capture_output=True, text=True)
        return result

    def _get_python_executable_for_pip(self):
        """Return a Python executable path suitable for running pip.

        In Windows QGIS, sys.executable can point to qgis-bin.exe, which cannot
        execute "-m pip" and may open a new QGIS instance instead.
        """
        candidates = []

        # Preferred candidate only when it is already a Python executable.
        exe_name = os.path.basename(sys.executable).lower()
        if exe_name.startswith("python"):
            candidates.append(sys.executable)

        # Typical Python root used by embedded QGIS Python.
        if getattr(sys, "exec_prefix", None):
            candidates.append(os.path.join(sys.exec_prefix, "python.exe"))
            candidates.append(os.path.join(sys.exec_prefix, "bin", "python.exe"))

        # Nearby executable in same folder as current executable.
        candidates.append(os.path.join(os.path.dirname(sys.executable), "python.exe"))

        # PATH fallback.
        path_python = shutil.which("python")
        if path_python:
            candidates.append(path_python)

        seen = set()
        for candidate in candidates:
            if not candidate:
                continue
            norm = os.path.normcase(os.path.normpath(candidate))
            if norm in seen:
                continue
            seen.add(norm)
            if os.path.isfile(candidate):
                return candidate

        # Last resort: keep previous behavior.
        return sys.executable
