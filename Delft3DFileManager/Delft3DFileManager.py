# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsMapLayerType, QgsWkbTypes
)
from PyQt5.QtCore import QVariant
import os

class Delft3DFileManager:
    def __init__(self, iface):
        self.iface = iface
        self.import_action = None
        self.export_action = None

    def initGui(self):
        """Create toolbar button and menu item"""
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.import_action = QAction(QIcon(icon_path), "Load Weir File", self.iface.mainWindow())
        self.import_action.setStatusTip("Load custom weir text file as line + point layers")
        self.import_action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.import_action)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.import_action)

        self.export_action = QAction(QIcon(icon_path), "Export Polyline", self.iface.mainWindow())
        self.export_action.setStatusTip("Export line layer features to custom text format")
        self.export_action.triggered.connect(self.export_lines)
        self.iface.addToolBarIcon(self.export_action)
        self.iface.addPluginToMenu("&Delft3D File Manager", self.export_action)

    def unload(self):
        """Remove the plugin menu item and icon"""
        if self.import_action:
            self.iface.removeToolBarIcon(self.import_action)
            self.iface.removePluginMenu("&Delft3D File Manager", self.import_action)
        if self.export_action:
            self.iface.removeToolBarIcon(self.export_action)
            self.iface.removePluginMenu("&Delft3D File Manager", self.export_action)

    def run(self):
        """Main entry point"""
        filepath, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Select weir text file",
            "",
            "Text files (*.txt)"
        )
        if filepath:
            self.load_weir_file(filepath)

    def load_weir_file(self, filepath):
        """Parse the text file and create both polyline and point layers"""
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
