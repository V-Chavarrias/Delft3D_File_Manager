# -*- coding: utf-8 -*-
"""
Dialog for writing bed level (elevation) data into a UGRID mesh file.

Supports three source types:
    1. NetCDF file  – any variable on a regular lat/lon grid.
    2. QGIS Raster layer  – any band of an already-loaded raster layer.
    3. QGIS Vector layer  – any numeric attribute of a point/multipoint layer.

The dialog spawns a QThread for the heavy computation so the QGIS UI stays
responsive.  A progress bar is updated via Qt signals.
"""

from __future__ import annotations

import importlib
import os
import shutil
import traceback
from typing import Optional

import numpy as np
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .bed_level_interpolator import (
    INTERP_METHODS,
    auto_detect_mesh_info,
    list_source_variables,
    load_source_netcdf,
    run_interpolation,
)


def _is_numeric_dtype(dtype) -> bool:
    """Return True if a numpy/netCDF dtype stores numeric values."""
    try:
        return np.issubdtype(np.dtype(dtype), np.number)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class _InterpolationWorker(QThread):
    """QThread that runs the interpolation and emits progress / result signals."""

    progress = pyqtSignal(int, int)   # (current_node, total_nodes)
    finished = pyqtSignal(int)        # updated_count
    error = pyqtSignal(str)           # error message

    def __init__(
        self,
        method: str,
        mesh_path: str,
        z_var_name: str,
        source_x: np.ndarray,
        source_y: np.ndarray,
        source_z: np.ndarray,
        mesh_epsg: Optional[int],
        source_epsg: int,
        parent=None,
    ):
        super().__init__(parent)
        self._method = method
        self._mesh_path = mesh_path
        self._z_var_name = z_var_name
        self._source_x = source_x
        self._source_y = source_y
        self._source_z = source_z
        self._mesh_epsg = mesh_epsg
        self._source_epsg = source_epsg

    def run(self):
        try:
            count = run_interpolation(
                method=self._method,
                mesh_path=self._mesh_path,
                z_var_name=self._z_var_name,
                source_x=self._source_x,
                source_y=self._source_y,
                source_z=self._source_z,
                mesh_epsg=self._mesh_epsg,
                source_epsg=self._source_epsg,
                progress_callback=lambda cur, tot: self.progress.emit(cur, tot),
            )
            self.finished.emit(count)
        except Exception:  # noqa: BLE001
            self.error.emit(traceback.format_exc())


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class BedLevelDialog(QDialog):
    """Dialog for the 'Write Bed Level to Mesh' action."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self._worker: Optional[_InterpolationWorker] = None
        self._required_dependencies = ["netCDF4", "pyproj", "scipy"]
        self._target_mesh_path = ""

        self.setWindowTitle("Write Bed Level to Mesh")
        self.setMinimumWidth(520)
        self._build_ui()
        self._connect_signals()
        self._populate_qgis_layers()
        self.refresh_dependency_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # ── Mesh group ────────────────────────────────────────────────
        mesh_group = QGroupBox("Target Mesh (UGRID NetCDF)")
        mesh_form = QFormLayout(mesh_group)

        self.mesh_path_edit = QLineEdit()
        self.mesh_path_edit.setPlaceholderText("Select UGRID NetCDF file…")
        self.mesh_browse_btn = QPushButton("...")
        self.mesh_browse_btn.setFixedWidth(38)
        self.mesh_browse_btn.clicked.connect(self._browse_mesh_file)
        mesh_path_row = QHBoxLayout()
        mesh_path_row.addWidget(self.mesh_path_edit)
        mesh_path_row.addWidget(self.mesh_browse_btn)
        mesh_form.addRow("Mesh file:", mesh_path_row)

        self.combo_z_var = QComboBox()
        mesh_form.addRow("Elevation variable:", self.combo_z_var)

        self.mesh_epsg_edit = QLineEdit()
        self.mesh_epsg_edit.setPlaceholderText("e.g. 32618  (leave blank if same as source)")
        mesh_form.addRow("Mesh CRS (EPSG):", self.mesh_epsg_edit)

        self.output_mesh_edit = QLineEdit()
        self.output_mesh_edit.setPlaceholderText(
            "Optional: output mesh file (leave empty to overwrite input)"
        )
        self.output_browse_btn = QPushButton("...")
        self.output_browse_btn.setFixedWidth(38)
        self.output_browse_btn.clicked.connect(self._browse_output_mesh_file)
        output_path_row = QHBoxLayout()
        output_path_row.addWidget(self.output_mesh_edit)
        output_path_row.addWidget(self.output_browse_btn)
        mesh_form.addRow("Output mesh:", output_path_row)

        main_layout.addWidget(mesh_group)

        # ── Source group ──────────────────────────────────────────────
        src_group = QGroupBox("Elevation Source")
        src_layout = QVBoxLayout(src_group)

        # Source type radio buttons
        src_type_row = QHBoxLayout()
        self.radio_netcdf = QRadioButton("NetCDF file")
        self.radio_raster = QRadioButton("QGIS Raster layer")
        self.radio_vector = QRadioButton("QGIS Vector layer")
        self.radio_netcdf.setChecked(True)
        src_type_row.addWidget(self.radio_netcdf)
        src_type_row.addWidget(self.radio_raster)
        src_type_row.addWidget(self.radio_vector)
        src_type_row.addStretch()
        src_layout.addLayout(src_type_row)

        # ── Source: NetCDF file panel ──────────────────────────────────
        self.panel_netcdf = QWidget()
        netcdf_form = QFormLayout(self.panel_netcdf)
        netcdf_form.setContentsMargins(0, 0, 0, 0)

        self.src_path_edit = QLineEdit()
        self.src_path_edit.setPlaceholderText("Select source NetCDF file…")
        self.src_browse_btn = QPushButton("...")
        self.src_browse_btn.setFixedWidth(38)
        self.src_browse_btn.clicked.connect(self._browse_source_file)
        src_path_row = QHBoxLayout()
        src_path_row.addWidget(self.src_path_edit)
        src_path_row.addWidget(self.src_browse_btn)
        netcdf_form.addRow("Source file:", src_path_row)

        self.combo_src_var = QComboBox()
        netcdf_form.addRow("Variable:", self.combo_src_var)

        self.src_epsg_edit = QLineEdit("4326")
        self.src_epsg_edit.setPlaceholderText("e.g. 4326")
        netcdf_form.addRow("Source CRS (EPSG):", self.src_epsg_edit)

        src_layout.addWidget(self.panel_netcdf)

        # ── Source: QGIS Raster layer panel ───────────────────────────
        self.panel_raster = QWidget()
        raster_form = QFormLayout(self.panel_raster)
        raster_form.setContentsMargins(0, 0, 0, 0)

        self.combo_raster_layer = QComboBox()
        raster_form.addRow("Raster layer:", self.combo_raster_layer)

        self.combo_raster_band = QComboBox()
        raster_form.addRow("Band:", self.combo_raster_band)

        src_layout.addWidget(self.panel_raster)
        self.panel_raster.hide()

        # ── Source: QGIS Vector layer panel ───────────────────────────
        self.panel_vector = QWidget()
        vector_form = QFormLayout(self.panel_vector)
        vector_form.setContentsMargins(0, 0, 0, 0)

        self.combo_vector_layer = QComboBox()
        vector_form.addRow("Vector layer:", self.combo_vector_layer)

        self.combo_vector_attr = QComboBox()
        vector_form.addRow("Elevation attribute:", self.combo_vector_attr)

        src_layout.addWidget(self.panel_vector)
        self.panel_vector.hide()

        main_layout.addWidget(src_group)

        # ── Method ────────────────────────────────────────────────────
        method_group = QGroupBox("Interpolation Method")
        method_form = QFormLayout(method_group)
        self.combo_method = QComboBox()
        for key, label in INTERP_METHODS.items():
            self.combo_method.addItem(label, key)
        method_form.addRow("Method:", self.combo_method)
        main_layout.addWidget(method_group)

        # ── Dependency status ────────────────────────────────────────
        deps_group = QGroupBox("Dependency Status")
        deps_layout = QVBoxLayout(deps_group)
        deps_layout.setContentsMargins(9, 9, 9, 9)
        deps_header = QHBoxLayout()
        self.deps_status_label = QLabel("")
        self.deps_refresh_btn = QPushButton("Refresh")
        self.deps_refresh_btn.setFixedWidth(90)
        deps_header.addWidget(self.deps_status_label, 1)
        deps_header.addWidget(self.deps_refresh_btn)
        deps_layout.addLayout(deps_header)
        self.deps_detail_label = QLabel("")
        self.deps_detail_label.setWordWrap(True)
        deps_layout.addWidget(self.deps_detail_label)
        main_layout.addWidget(deps_group)

        # ── Progress ──────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)

        # ── Buttons ───────────────────────────────────────────────────
        btn_box = QDialogButtonBox()
        self.run_btn = btn_box.addButton("Run", QDialogButtonBox.AcceptRole)
        btn_box.addButton(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        self.run_btn.clicked.connect(self._on_run)
        main_layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.mesh_path_edit.editingFinished.connect(self._on_mesh_path_changed)
        self.src_path_edit.editingFinished.connect(self._on_source_path_changed)
        self.radio_netcdf.toggled.connect(self._on_source_type_toggled)
        self.radio_raster.toggled.connect(self._on_source_type_toggled)
        self.radio_vector.toggled.connect(self._on_source_type_toggled)
        self.combo_raster_layer.currentIndexChanged.connect(self._on_raster_layer_changed)
        self.combo_vector_layer.currentIndexChanged.connect(self._on_vector_layer_changed)
        self.deps_refresh_btn.clicked.connect(self.refresh_dependency_status)

    def _dependency_status(self):
        """Return tuple: (installed_list, missing_list)."""
        installed = []
        missing = []
        for module_name in self._required_dependencies:
            try:
                importlib.import_module(module_name)
                installed.append(module_name)
            except Exception:
                missing.append(module_name)
        return installed, missing

    def refresh_dependency_status(self):
        """Update dependency status labels in the dialog."""
        installed, missing = self._dependency_status()
        if not missing:
            self.deps_status_label.setText("Status: Installed")
            self.deps_status_label.setStyleSheet("color: #1E7F34; font-weight: 600;")
            self.deps_detail_label.setText(
                "All required packages are available: " + ", ".join(installed)
            )
            self.deps_detail_label.setStyleSheet("")
            return

        self.deps_status_label.setText("Status: Missing")
        self.deps_status_label.setStyleSheet("color: #B14F00; font-weight: 600;")
        self.deps_detail_label.setText(
            "Missing packages: " + ", ".join(missing)
            + "\nUse menu: Delft3D File Manager -> Install Python Dependencies, then restart QGIS."
        )
        self.deps_detail_label.setStyleSheet("color: #B14F00;")

    # ------------------------------------------------------------------
    # Slot: source-type radio button changed
    # ------------------------------------------------------------------

    def _on_source_type_toggled(self):
        self.panel_netcdf.setVisible(self.radio_netcdf.isChecked())
        self.panel_raster.setVisible(self.radio_raster.isChecked())
        self.panel_vector.setVisible(self.radio_vector.isChecked())

    # ------------------------------------------------------------------
    # Slot: mesh file changed
    # ------------------------------------------------------------------

    def _on_mesh_path_changed(self):
        path = self.mesh_path_edit.text().strip()
        if not os.path.isfile(path):
            return
        previous = self.combo_z_var.currentText()
        self.combo_z_var.clear()
        try:
            try:
                import netCDF4 as nc
            except ModuleNotFoundError:
                self._show_missing_netcdf4_message("read mesh variables")
                return

            ds = nc.Dataset(path, "r")
            info = auto_detect_mesh_info(ds)
            node_dim = ds[info["node_x_var"]].dimensions[0]

            # Candidate 1: explicit node_z/location=node variables from UGRID metadata.
            candidates = list(info["node_z_vars"])

            # Candidate 2 (fallback): any numeric variable whose first dimension is node_dim.
            for vname, var in ds.variables.items():
                if vname in (info["node_x_var"], info["node_y_var"], info["face_conn_var"]):
                    continue
                if not var.dimensions:
                    continue
                if var.dimensions[0] != node_dim:
                    continue
                if not _is_numeric_dtype(var.dtype):
                    continue
                if vname not in candidates:
                    candidates.append(vname)

            for vname in candidates:
                self.combo_z_var.addItem(vname)

            # Restore previous selection if still available.
            if previous:
                idx = self.combo_z_var.findText(previous)
                if idx >= 0:
                    self.combo_z_var.setCurrentIndex(idx)

            epsg = _read_epsg_from_nc(ds)
            if epsg and epsg > 0:
                self.mesh_epsg_edit.setText(str(epsg))
            ds.close()

            if self.combo_z_var.count() == 0:
                self.status_label.setText(
                    "No numeric node variable found. Check if the file is a UGRID mesh."
                )
            else:
                self.status_label.setText("")
        except Exception as exc:
            self.status_label.setText(f"Could not read mesh file: {exc}")

    # ------------------------------------------------------------------
    # Slot: source file changed
    # ------------------------------------------------------------------

    def _on_source_path_changed(self):
        path = self.src_path_edit.text().strip()
        if not os.path.isfile(path):
            return
        previous = self.combo_src_var.currentText()
        self.combo_src_var.clear()
        try:
            try:
                import netCDF4  # noqa: F401
            except ModuleNotFoundError:
                self._show_missing_netcdf4_message("read source NetCDF variables")
                return

            data_vars, coord_info = list_source_variables(path)

            # Fallback for files without full CF metadata: include any numeric
            # variable with at least 2 dimensions, excluding detected coords.
            if not data_vars:
                import netCDF4 as nc

                ds = nc.Dataset(path, "r")
                try:
                    lat_var = coord_info.get("lat_var")
                    lon_var = coord_info.get("lon_var")
                    for vname, var in ds.variables.items():
                        if vname in (lat_var, lon_var):
                            continue
                        if len(var.dimensions) < 2:
                            continue
                        if not _is_numeric_dtype(var.dtype):
                            continue
                        data_vars.append(vname)
                finally:
                    ds.close()

            for v in data_vars:
                self.combo_src_var.addItem(v)

            if previous:
                idx = self.combo_src_var.findText(previous)
                if idx >= 0:
                    self.combo_src_var.setCurrentIndex(idx)

            if coord_info["is_geographic"]:
                self.src_epsg_edit.setText("4326")

            if self.combo_src_var.count() == 0:
                self.status_label.setText(
                    "No numeric source variables found in the selected NetCDF file."
                )
            else:
                self.status_label.setText("")
        except Exception as exc:
            self.status_label.setText(f"Could not read source file: {exc}")

    # ------------------------------------------------------------------
    # Slot: raster layer selection changed
    # ------------------------------------------------------------------

    def _on_raster_layer_changed(self):
        self.combo_raster_band.clear()
        layer = self._selected_raster_layer()
        if layer is None:
            return
        n_bands = layer.bandCount()
        for b in range(1, n_bands + 1):
            name = layer.bandName(b)
            self.combo_raster_band.addItem(f"{b}: {name}", b)

    # ------------------------------------------------------------------
    # Slot: vector layer selection changed
    # ------------------------------------------------------------------

    def _on_vector_layer_changed(self):
        self.combo_vector_attr.clear()
        layer = self._selected_vector_layer()
        if layer is None:
            return
        for field in layer.fields():
            if field.isNumeric():
                self.combo_vector_attr.addItem(field.name())

    # ------------------------------------------------------------------
    # Layer list population
    # ------------------------------------------------------------------

    def _populate_qgis_layers(self):
        raster_layers = []
        vector_layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                raster_layers.append(layer)
            elif isinstance(layer, QgsVectorLayer):
                if layer.geometryType() in (
                    QgsWkbTypes.PointGeometry,
                    QgsWkbTypes.UnknownGeometry,
                ):
                    vector_layers.append(layer)

        self.combo_raster_layer.clear()
        for layer in raster_layers:
            self.combo_raster_layer.addItem(layer.name(), layer.id())

        self.combo_vector_layer.clear()
        for layer in vector_layers:
            self.combo_vector_layer.addItem(layer.name(), layer.id())

        if raster_layers:
            self._on_raster_layer_changed()
        if vector_layers:
            self._on_vector_layer_changed()

    # ------------------------------------------------------------------
    # File browser helpers
    # ------------------------------------------------------------------

    def _browse_mesh_file(self):
        dlg = QFileDialog(self, "Select UGRID mesh file")
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter("NetCDF files (*.nc *.nc4);;All files (*)")
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        path = ""
        if dlg.exec_():
            selected = dlg.selectedFiles()
            if selected:
                path = selected[0]
        if path:
            self.mesh_path_edit.setText(path)
            self._on_mesh_path_changed()

    def _browse_source_file(self):
        dlg = QFileDialog(self, "Select source elevation file")
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter("NetCDF files (*.nc *.nc4);;All files (*)")
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        path = ""
        if dlg.exec_():
            selected = dlg.selectedFiles()
            if selected:
                path = selected[0]
        if path:
            self.src_path_edit.setText(path)
            self._on_source_path_changed()

    def _browse_output_mesh_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select output mesh file",
            self.mesh_path_edit.text().strip() or "",
            "NetCDF files (*.nc *.nc4);;All files (*)",
        )
        if path:
            self.output_mesh_edit.setText(path)

    # ------------------------------------------------------------------
    # Layer retrieval helpers
    # ------------------------------------------------------------------

    def _selected_raster_layer(self) -> Optional[QgsRasterLayer]:
        layer_id = self.combo_raster_layer.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _selected_vector_layer(self) -> Optional[QgsVectorLayer]:
        layer_id = self.combo_vector_layer.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate(self) -> bool:
        input_mesh_path = self.mesh_path_edit.text().strip()
        if not os.path.isfile(input_mesh_path):
            QMessageBox.warning(self, "Missing input", "Please select a valid mesh file.")
            return False

        output_mesh_path = self.output_mesh_edit.text().strip()
        if output_mesh_path:
            out_dir = os.path.dirname(output_mesh_path)
            if out_dir and not os.path.isdir(out_dir):
                QMessageBox.warning(
                    self,
                    "Invalid output",
                    "The output folder does not exist.",
                )
                return False

            if os.path.normcase(os.path.abspath(output_mesh_path)) == os.path.normcase(
                os.path.abspath(input_mesh_path)
            ):
                # Same path effectively means overwrite; clear output to avoid copy step.
                self.output_mesh_edit.setText("")

        if not self.combo_z_var.currentText():
            QMessageBox.warning(self, "Missing input", "No elevation variable selected in mesh.")
            return False
        if self.radio_netcdf.isChecked():
            if not os.path.isfile(self.src_path_edit.text().strip()):
                QMessageBox.warning(self, "Missing input", "Please select a valid source file.")
                return False
            if not self.combo_src_var.currentText():
                QMessageBox.warning(self, "Missing input", "No variable selected in source file.")
                return False
        elif self.radio_raster.isChecked():
            if self._selected_raster_layer() is None:
                QMessageBox.warning(self, "Missing input", "No raster layer available.")
                return False
        elif self.radio_vector.isChecked():
            if self._selected_vector_layer() is None:
                QMessageBox.warning(self, "Missing input", "No vector layer available.")
                return False
            if not self.combo_vector_attr.currentText():
                QMessageBox.warning(self, "Missing input", "No elevation attribute selected.")
                return False
        return True

    # ------------------------------------------------------------------
    # EPSG helper
    # ------------------------------------------------------------------

    def _mesh_epsg(self) -> Optional[int]:
        txt = self.mesh_epsg_edit.text().strip()
        if txt:
            try:
                return int(txt)
            except ValueError:
                pass
        return None

    def _source_epsg(self) -> int:
        txt = self.src_epsg_edit.text().strip()
        try:
            return int(txt)
        except ValueError:
            return 4326

    # ------------------------------------------------------------------
    # Source data loading
    # ------------------------------------------------------------------

    def _load_source_data(self):
        """Return (source_x, source_y, source_z, source_epsg)."""
        if self.radio_netcdf.isChecked():
            return self._load_source_netcdf()
        elif self.radio_raster.isChecked():
            return self._load_source_raster()
        else:
            return self._load_source_vector()

    def _load_source_netcdf(self):
        path = self.src_path_edit.text().strip()
        var_name = self.combo_src_var.currentText()
        source_epsg = self._source_epsg()

        try:
            import netCDF4  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The 'netCDF4' Python package is required to read NetCDF files.\n\n"
                "Install it in the QGIS Python environment and restart QGIS."
            ) from exc

        # Compute mesh bbox in source CRS for efficient subsetting
        try:
            import netCDF4 as nc
            from pyproj import Transformer

            ds_mesh = nc.Dataset(self.mesh_path_edit.text().strip(), "r")
            info = auto_detect_mesh_info(ds_mesh)
            nx = np.asarray(ds_mesh[info["node_x_var"]][:], dtype=float)
            ny = np.asarray(ds_mesh[info["node_y_var"]][:], dtype=float)
            ds_mesh.close()

            mesh_epsg = self._mesh_epsg()
            if mesh_epsg and source_epsg and mesh_epsg != source_epsg:
                tr = Transformer.from_crs(
                    f"EPSG:{mesh_epsg}", f"EPSG:{source_epsg}", always_xy=True
                )
                corners_src = tr.transform(
                    [nx.min(), nx.max(), nx.min(), nx.max()],
                    [ny.min(), ny.min(), ny.max(), ny.max()],
                )
                bbox = (
                    min(corners_src[0]),
                    min(corners_src[1]),
                    max(corners_src[0]),
                    max(corners_src[1]),
                )
            else:
                bbox = (nx.min(), ny.min(), nx.max(), ny.max())
        except Exception:
            bbox = None  # will read full source

        sx, sy, sz = load_source_netcdf(path, var_name, bbox)
        return sx, sy, sz, source_epsg

    def _load_source_raster(self):
        from osgeo import gdal

        layer = self._selected_raster_layer()
        band_num = self.combo_raster_band.currentData() or 1
        source_epsg = _epsg_from_crs(layer.crs())

        gdal_ds = gdal.Open(layer.source())
        if gdal_ds is None:
            raise RuntimeError(f"GDAL could not open raster layer: {layer.source()}")

        band = gdal_ds.GetRasterBand(band_num)
        nodata = band.GetNoDataValue()
        data = band.ReadAsArray().astype(float)
        if nodata is not None:
            data[data == nodata] = np.nan

        gt = gdal_ds.GetGeoTransform()
        nrows, ncols = data.shape
        cols_idx = np.arange(ncols)
        rows_idx = np.arange(nrows)
        col_grid, row_grid = np.meshgrid(cols_idx, rows_idx)
        # Pixel centre coordinates
        x_grid = gt[0] + (col_grid + 0.5) * gt[1] + (row_grid + 0.5) * gt[2]
        y_grid = gt[3] + (col_grid + 0.5) * gt[4] + (row_grid + 0.5) * gt[5]
        gdal_ds = None  # close

        sx = x_grid.ravel()
        sy = y_grid.ravel()
        sz = data.ravel()
        valid = np.isfinite(sz)
        return sx[valid], sy[valid], sz[valid], source_epsg

    def _load_source_vector(self):
        layer = self._selected_vector_layer()
        attr = self.combo_vector_attr.currentText()
        source_epsg = _epsg_from_crs(layer.crs())

        xs, ys, zs = [], [], []
        for feat in layer.getFeatures():
            val = feat[attr]
            if val is None:
                continue
            try:
                z = float(val)
            except (TypeError, ValueError):
                continue
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            pt = geom.centroid().asPoint()
            xs.append(pt.x())
            ys.append(pt.y())
            zs.append(z)

        return np.array(xs), np.array(ys), np.array(zs), source_epsg

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            return  # already running

        if not self._validate():
            return

        self.status_label.setText("Loading source data…")
        self.run_btn.setEnabled(False)
        try:
            sx, sy, sz, source_epsg = self._load_source_data()
        except Exception as exc:
            QMessageBox.critical(self, "Error loading source data", str(exc))
            self.run_btn.setEnabled(True)
            self.status_label.setText("")
            return

        if len(sz) == 0:
            QMessageBox.warning(
                self, "No valid source data",
                "The source dataset contains no finite elevation values."
            )
            self.run_btn.setEnabled(True)
            self.status_label.setText("")
            return

        method_key = self.combo_method.currentData()
        input_mesh_path = self.mesh_path_edit.text().strip()
        output_mesh_path = self.output_mesh_edit.text().strip()
        mesh_path = input_mesh_path

        if output_mesh_path:
            try:
                shutil.copy2(input_mesh_path, output_mesh_path)
                mesh_path = output_mesh_path
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Error creating output mesh",
                    f"Could not create output mesh file:\n{exc}",
                )
                self.run_btn.setEnabled(True)
                self.status_label.setText("")
                return

        z_var_name = self.combo_z_var.currentText()
        mesh_epsg = self._mesh_epsg()
        self._target_mesh_path = mesh_path

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(
            f"Interpolating {len(sz):,} source points into mesh…"
        )

        self._worker = _InterpolationWorker(
            method=method_key,
            mesh_path=mesh_path,
            z_var_name=z_var_name,
            source_x=sx,
            source_y=sy,
            source_z=sz,
            mesh_epsg=mesh_epsg,
            source_epsg=source_epsg,
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int):
        pct = int(100 * current / total) if total > 0 else 0
        self.progress_bar.setValue(pct)

    def _on_finished(self, updated_count: int):
        self.progress_bar.setValue(100)
        self.run_btn.setEnabled(True)
        self.status_label.setText(
            f"Done. {updated_count:,} mesh node(s) updated."
        )
        self.iface.messageBar().pushSuccess(
            "Bed Level",
            f"Wrote bed level to mesh: {updated_count:,} node(s) updated in "
            f"{os.path.basename(self._target_mesh_path or self.mesh_path_edit.text().strip())}",
        )

    def _on_error(self, msg: str):
        self.progress_bar.setValue(0)
        self.run_btn.setEnabled(True)
        self.status_label.setText("Failed – see error dialog.")
        QMessageBox.critical(self, "Interpolation error", msg)

    def _show_missing_netcdf4_message(self, operation: str):
        self.refresh_dependency_status()
        self.status_label.setText("Missing dependency: netCDF4")
        QMessageBox.warning(
            self,
            "Missing dependency",
            "The 'netCDF4' Python package is not available in the QGIS Python "
            f"environment, so the plugin cannot {operation}.\n\n"
            "Use menu: Delft3D File Manager -> Install Python Dependencies, "
            "then restart QGIS.",
        )

    # ------------------------------------------------------------------
    # Close guard: don't close while worker is running
    # ------------------------------------------------------------------

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Running", "Please wait for the interpolation to finish."
            )
            return
        super().reject()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _read_epsg_from_nc(nc_dataset) -> Optional[int]:
    """Try to read an EPSG integer from a NetCDF dataset."""
    for vname in nc_dataset.variables:
        v = nc_dataset[vname]
        for attr in ("EPSG_code", "epsg", "EPSG"):
            val = getattr(v, attr, None)
            if val is not None:
                s = str(val).upper().replace("EPSG:", "").strip()
                try:
                    code = int(s)
                    if code > 0:
                        return code
                except ValueError:
                    pass
    return None


def _epsg_from_crs(crs) -> int:
    """Extract EPSG integer from a QgsCoordinateReferenceSystem."""
    auth = crs.authid()  # e.g. "EPSG:4326"
    if auth.upper().startswith("EPSG:"):
        try:
            return int(auth.split(":")[1])
        except (IndexError, ValueError):
            pass
    return 4326
