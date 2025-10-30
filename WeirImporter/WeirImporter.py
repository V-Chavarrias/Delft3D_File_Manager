# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction, QFileDialog
from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject
)
from qgis.PyQt.QtCore import QVariant
import os

class WeirImporter:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        """Create toolbar button and menu item"""
        self.action = QAction("Load Weir File", self.iface.mainWindow())
        self.action.setStatusTip("Load custom weir text file as line layer")
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
        """Parse the text file and create a layer"""
        layer_name = os.path.splitext(os.path.basename(filepath))[0]
        layer = QgsVectorLayer("LineString?crs=EPSG:28992", layer_name, "memory")
        provider = layer.dataProvider()

        fields = [
            QgsField("name", QVariant.String),
            QgsField("crest_lvl", QVariant.Double),
            QgsField("sill_hL", QVariant.Double),
            QgsField("sill_hR", QVariant.Double),
            QgsField("crest_w", QVariant.Double),
            QgsField("slope_L", QVariant.Double),
            QgsField("slope_R", QVariant.Double),
            QgsField("rough_cd", QVariant.Double),
        ]
        provider.addAttributes(fields)
        layer.updateFields()

        with open(filepath, 'r') as f:
            lines = [l.strip() for l in f if l.strip()]

        i = 0
        while i < len(lines):
            name_line = lines[i]
            i += 1
            row_col = lines[i]
            i += 1

            nrows, ncols = map(int, row_col.split())
            coords = []
            last_values = None
            for _ in range(nrows):
                values = list(map(float, lines[i].split()))
                coords.append(QgsPointXY(values[0], values[1]))
                last_values = values[2:]
                i += 1

            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolylineXY(coords))
            feat.setAttributes([name_line] + last_values)
            provider.addFeature(feat)

        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self.iface.messageBar().pushSuccess(
            "Weir Importer",
            f"Loaded {layer.featureCount()} weirs from {os.path.basename(filepath)}"
        )
