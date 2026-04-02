# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsMapLayerType, QgsWkbTypes, QgsSpatialIndex
)
from PyQt5.QtCore import QVariant, Qt
import importlib
import math
import os
import shutil
import subprocess
import sys

class Delft3DFileManager:
    def __init__(self, iface):
        self.iface = iface
        self.import_action = None
        self.export_action = None
        self.export_pointcloud_action = None
        self.bed_level_action = None
        self.create_trachytopes_action = None
        self.update_trachytopes_action = None
        self.export_trachytopes_action = None
        self.install_deps_action = None
        self._bed_level_dialog = None
        self._required_packages = ["netCDF4", "pyproj", "scipy"]

    def initGui(self):
        """Create toolbar button and menu item"""
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.import_action = QAction(QIcon(icon_path), "Import", self.iface.mainWindow())
        self.import_action.setStatusTip("Import Delft3D file (.fxw fixed-weir, .pli/.ldb/.pol polyline, .pliz auto-detected fixed-weir/polyline, .xyn points, .nc UGRID mesh)")
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
        if self.update_trachytopes_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.update_trachytopes_action)
        if self.export_trachytopes_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.export_trachytopes_action)
        if self.export_pointcloud_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.export_pointcloud_action)
        if self.install_deps_action:
            self.iface.removePluginMenu("&Delft3D File Manager", self.install_deps_action)

    def run(self):
        """Main entry point: open file dialog and dispatch by extension"""
        filepath, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select Delft3D file",
            "",
            "Delft3D Files (*.fxw *.pli *.ldb *.pol *.pliz *.xyn *.nc);;All Files (*)"
        )
        if filepath:
            self.load_file_by_extension(filepath)

    def load_file_by_extension(self, filepath):
        """Route file to appropriate parser based on extension."""
        _, ext = os.path.splitext(filepath)
        ext_lower = ext.lower()
        
        if ext_lower == ".fxw":
            self.load_fixed_weir_file(filepath)
        elif ext_lower == ".pliz":
            if self._pliz_has_extra_columns(filepath):
                self.load_fixed_weir_file(filepath)
            else:
                self.load_polyline_file(filepath)
        elif ext_lower in [".pli", ".ldb", ".pol"]:
            self.load_polyline_file(filepath)
        elif ext_lower == ".xyn":
            self.load_xyn_file(filepath)
        elif ext_lower == ".nc":
            self.load_ugrid_mesh_file(filepath)
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
                "  .nc - UGRID mesh file"
            )

    def _pliz_has_extra_columns(self, filepath):
        """Return True when a .pliz file header indicates more than two data columns."""
        try:
            try:
                with open(filepath, "r", encoding="utf-8") as handle:
                    lines = [line.strip() for line in handle if line.strip()]
            except UnicodeDecodeError:
                with open(filepath, "r") as handle:
                    lines = [line.strip() for line in handle if line.strip()]

            if len(lines) < 2:
                return False

            header_parts = lines[1].split()
            if len(header_parts) < 2:
                return False

            return int(header_parts[1]) > 2
        except (OSError, ValueError, IndexError):
            return False

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

        # --- Read file ---
        with open(filepath, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]

        i = 0
        while i < len(lines):
            if ":" in lines[i]:  # new weir block
                weir_name = lines[i]
                i += 1
                nrows, _ = map(int, lines[i].split())
                i += 1

                pts = []

                for _ in range(nrows):
                    parts = lines[i].split()
                    x, y = map(float, parts[:2])
                    vals = list(map(float, parts[2:]))  # 7 attributes
                    pts.append(QgsPointXY(x, y))

                    # Add point feature
                    point_feat = QgsFeature()
                    point_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                    point_feat.setAttributes([weir_name] + vals)
                    point_pr.addFeature(point_feat)

                    i += 1

                # Add polyline feature
                poly_feat = QgsFeature()
                poly_feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
                poly_feat.setAttributes([weir_name])
                poly_pr.addFeature(poly_feat)
            else:
                i += 1

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
        base_name = os.path.splitext(os.path.basename(filepath))[0]

        point_layer = QgsVectorLayer(f"Point?crs=EPSG:28992", base_name, "memory")
        point_pr = point_layer.dataProvider()
        point_pr.addAttributes(
            [
                QgsField("x", QVariant.Double),
                QgsField("y", QVariant.Double),
                QgsField("name", QVariant.String),
            ]
        )
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

                point_feat = QgsFeature(point_layer.fields())
                point_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x_value, y_value)))
                point_feat.setAttributes([x_value, y_value, point_name])
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
            "Text files (*.txt)"
        )
        if not output_path:
            return

        name_field = self._get_name_field(layer)
        exported_count = 0

        with open(output_path, "w", encoding="utf-8") as handle:
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if not geometry or geometry.isEmpty():
                    continue

                polylines = self._extract_polylines(geometry)
                if not polylines:
                    continue

                base_name = self._feature_name(feature, name_field)

                for idx, polyline in enumerate(polylines):
                    if len(polyline) < 2:
                        continue

                    exported_count += 1
                    block_name = base_name if len(polylines) == 1 else f"{base_name}_{idx + 1}"
                    handle.write(f"{block_name}\n")
                    handle.write(f"{len(polyline)} 2\n")
                    for point in polyline:
                        handle.write(f"{point.x():.6f} {point.y():.6f}\n")

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
            else:
                self.iface.messageBar().pushWarning(
                    "Delft3D File Manager",
                    "Point layers without the fixed-weir fields should be exported with 'Export Point Cloud (.xyn)'",
                )
            return

        self.iface.messageBar().pushWarning(
            "Delft3D File Manager",
            "Export supports only line layers and fixed-weir point layers",
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
        field_lookup = {field.name().lower(): field.name() for field in layer.fields()}
        resolved = {}
        for field_name in self._fixed_weir_field_names():
            actual_name = field_lookup.get(field_name.lower())
            if actual_name is None:
                return None
            resolved[field_name] = actual_name
        return resolved

    def _normalize_fxw_name(self, name):
        """Ensure exported fixed-weir block names remain compatible with the importer."""
        name = str(name).strip()
        return name if name.endswith(":") else f"{name}:"

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

        try:
            with nc.Dataset(filepath, 'r') as ds:
                # Read CRS
                epsg = self._read_epsg_from_nc(ds)
                if epsg is None:
                    epsg = 28992  # Default fallback

                # Detect components
                has_mesh2d = self._detect_mesh2d_exists(ds)
                mesh1d_data = self._read_mesh1d_data(ds) if self._detect_mesh1d_exists(ds) else None
                geom_data = self._read_geometry_data(ds) if self._detect_geometry_exists(ds) else None

                if not has_mesh2d and mesh1d_data is None and geom_data is None:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "Delft3D File Manager",
                        f"No mesh2d, mesh1d, or geometry components found in {os.path.basename(filepath)}"
                    )
                    return

                # Prompt for layer names
                layer_names = self._prompt_for_layer_names(base_name, has_mesh2d, mesh1d_data, geom_data)
                if layer_names is None:
                    return

                loaded_layers = []

                # Load mesh2d
                if has_mesh2d:
                    try:
                        self._load_mesh2d_layer(filepath, base_name, epsg, layer_names["mesh2d"])
                        loaded_layers.append("mesh2d")
                    except Exception as exc:
                        self.iface.messageBar().pushWarning(
                            "Delft3D File Manager",
                            f"Could not load mesh2d: {exc}"
                        )

                # Load mesh1d branches
                if mesh1d_data:
                    try:
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

        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Delft3D File Manager",
                f"Error loading mesh file: {exc}"
            )
            return

        if loaded_layers:
            self.iface.messageBar().pushSuccess(
                "Delft3D File Manager",
                f"Loaded {', '.join(loaded_layers)} from {os.path.basename(filepath)}"
            )

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

    def _detect_mesh2d_exists(self, nc_dataset):
        """Check if mesh2d topology exists in dataset."""
        return "Mesh2d_node_x" in nc_dataset.variables and "Mesh2d_node_y" in nc_dataset.variables

    def _detect_mesh1d_exists(self, nc_dataset):
        """Check if mesh1d topology exists in dataset."""
        return "mesh1d_node_x" in nc_dataset.variables and "mesh1d_node_y" in nc_dataset.variables

    def _detect_geometry_exists(self, nc_dataset):
        """Check if network geometry exists in dataset."""
        return "network_geom_x" in nc_dataset.variables and "network_geom_y" in nc_dataset.variables

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

    def _load_mesh2d_layer(self, filepath, base_name, epsg, layer_name):
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

        def _apply_crs_if_missing(layer):
            if layer is not None and layer.isValid() and not layer.crs().isValid():
                crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
                layer.setCrs(crs)

        def _is_usable_2d_mesh(layer):
            if layer is None or not layer.isValid():
                return False
            try:
                if layer.meshFaceCount() > 0:
                    return True
            except Exception:
                pass
            try:
                ext = layer.extent()
                return ext is not None and not ext.isEmpty()
            except Exception:
                return False

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

        # In multi-topology UGRID files, explicitly target the 2D mesh only.
        # MDAL URI format (from MDAL sources):
        # - "meshfile":meshname
        # - mdal:"meshfile":meshname
        quoted_file = f'"{filepath}"'
        mdal_mesh_uri = f'{quoted_file}:Mesh2d'
        mdal_mesh_uri_lower = f'{quoted_file}:mesh2d'
        mdal_driver_uri = f'mdal:{quoted_file}:Mesh2d'
        mdal_driver_uri_lower = f'mdal:{quoted_file}:mesh2d'

        uri_candidates = [
            mdal_mesh_uri,
            mdal_mesh_uri_lower,
            mdal_driver_uri,
            mdal_driver_uri_lower,
            f"{filepath}|layername=Mesh2d",
            f"{filepath}|layerName=Mesh2d",
        ]

        for uri in uri_candidates:
            for provider in ("mdal", ""):
                mesh_layer = QgsMeshLayer(uri, layer_name, provider)
                if not mesh_layer.isValid():
                    continue
                if _is_usable_2d_mesh(mesh_layer):
                    _apply_crs_if_missing(mesh_layer)
                    QgsProject.instance().addMapLayer(mesh_layer)
                    return

        # Avoid false-negative warning if a valid mesh from this same source is already loaded.
        for existing_layer in QgsProject.instance().mapLayers().values():
            if isinstance(existing_layer, QgsMeshLayer) and existing_layer.isValid():
                if _source_matches(existing_layer.source(), filepath) and _is_usable_2d_mesh(existing_layer):
                    _apply_crs_if_missing(existing_layer)
                    return

        raise RuntimeError(
            f"Failed to load mesh from {filepath}. "
            "Ensure the file is a valid UGRID mesh in netCDF format with faces. "
            "Supported by QGIS MDAL provider (netCDF/HDF5 with UGRID topology). "
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
        for vname in nc_dataset.variables:
            variable = nc_dataset[vname]
            for attr_name in ("EPSG_code", "epsg", "EPSG"):
                value = getattr(variable, attr_name, None)
                if value is None:
                    continue
                text = str(value).upper().replace("EPSG:", "").strip()
                try:
                    code = int(text)
                except ValueError:
                    continue
                if code > 0:
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
            "- netCDF4\n- pyproj\n- scipy\n\n"
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
