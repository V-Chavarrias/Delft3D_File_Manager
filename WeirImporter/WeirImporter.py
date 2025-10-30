# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction, QFileDialog
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject
)
from PyQt5.QtCore import QVariant
import os

class WeirImporter:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        """Create toolbar button and menu item"""
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(QIcon(icon_path), "Load Weir File", self.iface.mainWindow())
        self.action.setStatusTip("Load custom weir text file as line + point layers")
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Weir Importer", self.action)

    def unload(self):
        """Remove the plugin menu item and icon"""
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&Weir Importer", self.action)

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
            "Weir Importer",
            f"Loaded {poly_layer.featureCount()} weirs and {point_layer.featureCount()} points"
        )
