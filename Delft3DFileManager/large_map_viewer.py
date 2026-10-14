"""Controller of the Large MAP Viewer: connects reader, in-memory layers and dialog."""

import os
import time

try:
    from . import large_map_reader as reader
    from .large_map_layers import LargeMapLayerSet
except ImportError:  # pragma: no cover - direct module usage
    import large_map_reader as reader
    from large_map_layers import LargeMapLayerSet

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication

DEFAULT_EPSG = 28992
_PREFERRED_DEFAULTS = ("s1", "waterdepth", "ucmag")


def default_variable_key(entries):
    """Pick a sensible initial variable (water level when available)."""
    for suffix in _PREFERRED_DEFAULTS:
        for entry in entries:
            if not entry.derived and entry.key.lower().endswith(suffix):
                return entry.key
    return entries[0].key if entries else None


def dataset_name(entry, time_label=None, extra_labels=None):
    """Short dataset-group name shown below the mesh layer in the layer tree."""
    base = entry.key.split(":", 1)[1] if entry.derived else entry.key
    parts = [base]
    if entry.has_time and time_label:
        parts.append(str(time_label))
    parts.extend(str(label) for label in extra_labels or [])
    return "_".join("_".join(str(part).split()) for part in parts if str(part).strip())


def crs_from_info(epsg, wkt):
    """Build a CRS from an EPSG code, else WKT, else the plugin default (EPSG:28992)."""
    if epsg:
        crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
        if crs.isValid():
            return crs
    if wkt:
        crs = QgsCoordinateReferenceSystem.fromWkt(wkt)
        if crs.isValid():
            return crs
    return QgsCoordinateReferenceSystem(f"EPSG:{DEFAULT_EPSG}")


def _wait_cursor():
    cursor = getattr(Qt, "WaitCursor", None)
    if cursor is None:
        cursor = getattr(getattr(Qt, "CursorShape", None), "WaitCursor", None)
    return cursor


class LargeMapViewer:
    """State and actions of one Large MAP Viewer window."""

    def __init__(self, iface, plugin=None):
        self.iface = iface
        self.plugin = plugin
        self.dialog = None
        self.layer_set = None
        self.paths = []
        self.grids = []
        self.entries = {}
        self.time_labels = []
        self._stream_graph = None
        self._last_plotted_key = None

    # ----------------------------------------------------------------- dialog
    def _ensure_dialog(self):
        if self.dialog is None:
            from .large_map_dialog import LargeMapDialog

            parent = self.iface.mainWindow() if self.iface is not None else None
            self.dialog = LargeMapDialog(parent)
            self.dialog.set_handlers(
                on_file_selected=self.load_file,
                on_variable_changed=self.on_variable_changed,
                on_plot_requested=self.plot,
            )
        return self.dialog

    def open(self):
        dialog = self._ensure_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def close(self):
        if self.layer_set is not None:
            self.layer_set.dispose(remove_layers=False)
            self.layer_set = None
        if self.dialog is not None:
            try:
                self.dialog.close()
                self.dialog.deleteLater()
            except RuntimeError:
                pass
            self.dialog = None

    # --------------------------------------------------------------- helpers
    def _progress(self, title):
        create = getattr(self.plugin, "_create_progress_dialog", None)
        return create(title) if callable(create) else None

    def _update_progress(self, progress, value, text):
        update = getattr(self.plugin, "_update_progress_dialog", None)
        if callable(update):
            update(progress, value, text)

    def _close_progress(self, progress):
        close = getattr(self.plugin, "_close_progress_dialog", None)
        if callable(close):
            close(progress)

    def _set_busy(self, busy):
        entry = self.entries.get(self.dialog.selected_variable()) if self.dialog else None
        if self.dialog is not None:
            self.dialog.set_busy(busy, has_time=entry.has_time if entry else True)
        try:
            if busy:
                QApplication.setOverrideCursor(_wait_cursor())
            else:
                QApplication.restoreOverrideCursor()
            QApplication.processEvents()
        except (RuntimeError, TypeError):
            pass

    def _zoom_to_layers(self):
        try:
            canvas = self.iface.mapCanvas()
            layers = self.layer_set.layers
            extent = self.layer_set.extent()
            if extent is None or not layers:
                return
            destination = canvas.mapSettings().destinationCrs()
            if destination.isValid() and destination != layers[0].crs():
                transform = QgsCoordinateTransform(layers[0].crs(), destination, QgsProject.instance())
                extent = transform.transformBoundingBox(extent)
            canvas.setExtent(extent)
            canvas.refresh()
        except Exception:  # noqa: BLE001 - zooming is a convenience only
            pass

    # ---------------------------------------------------------------- loading
    def load_file(self, path):
        """Read the grid of all partitions and display it; populate the selectors."""
        dialog = self._ensure_dialog()
        progress = self._progress("Loading MAP grid")
        self._set_busy(True)
        try:
            paths = reader.discover_partitions(path)
            grids = []
            for number, partition_path in enumerate(paths):
                self._update_progress(
                    progress,
                    5 + 60 * number / max(len(paths), 1),
                    f"Reading grid {number + 1}/{len(paths)}: {os.path.basename(partition_path)}",
                )
                grids.append(reader.read_partition_grid(partition_path))
            self._update_progress(progress, 65, "Reading variables and times...")
            entries = reader.list_variables(paths[0])
            _values, time_labels = reader.read_times(paths[0])
            crs = crs_from_info(*reader.read_crs_info(paths[0]))

            self._update_progress(progress, 75, "Building mesh layers...")
            if self.layer_set is not None:
                self.layer_set.dispose(remove_layers=False)
                self.layer_set = None
            base = reader.model_base_name(path)
            layer_set = LargeMapLayerSet(grids, self._group_name(base), crs=crs, layer_name=base)
            layer_set.create_layers()

            self.paths = paths
            self.grids = grids
            self.entries = {entry.key: entry for entry in entries}
            self.time_labels = list(time_labels)
            self.layer_set = layer_set
            self._stream_graph = None
            self._last_plotted_key = None
            self._zoom_to_layers()
        except Exception as error:  # noqa: BLE001 - reported in the window
            dialog.set_message(f"Could not load {os.path.basename(str(path))}: {error}")
            return False
        finally:
            self._close_progress(progress)
            self._set_busy(False)

        faces = sum(grid.face_count for grid in grids)
        nodes = sum(len(grid.node_x) for grid in grids)
        partitions = f"{len(paths)} partitions, " if len(paths) > 1 else ""
        dialog.set_path(path)
        dialog.set_info(
            f"{partitions}{faces:,} faces, {nodes:,} nodes, {len(self.time_labels)} time steps, "
            f"CRS {crs.authid() or 'custom'}"
        )
        dialog.set_variable_options([(entry.key, entry.label) for entry in entries], default_variable_key(entries))
        dialog.set_time_labels(self.time_labels, 0)
        self.on_variable_changed(dialog.selected_variable())
        dialog.set_message("Grid loaded. Select a variable, time and index, then click Plot.")
        return True

    def _group_name(self, base):
        unique = getattr(self.plugin, "_unique_group_name", None)
        name = f"{base} (Large MAP)"
        if callable(unique):
            try:
                return unique(name)
            except Exception:  # noqa: BLE001
                return name
        return name

    def on_variable_changed(self, key):
        dialog = self.dialog
        entry = self.entries.get(key)
        if dialog is None:
            return
        if entry is None:
            dialog.set_extra_dimensions([])
            dialog.set_controls_enabled(False)
            return
        previous = dialog.selected_extra_indices()
        dimensions = [(dimension.name, dimension.labels) for dimension in entry.extra_dims]
        dialog.set_extra_dimensions(dimensions, previous)
        dialog.set_controls_enabled(True)
        dialog.set_time_enabled(entry.has_time and len(self.time_labels) > 0)

    # --------------------------------------------------------------- plotting
    def _stream_values(self, time_index):
        if self._stream_graph is None:
            self.dialog.set_message("Building the streamfunction graph (first use)...")
            QApplication.processEvents()
            self._stream_graph = reader.StreamFunctionGraph(self.grids)
        return self._stream_graph.values_for_time(time_index)

    def read_values(self, entry, time_index, extra_indices):
        if entry.key == reader.STREAM_FUNCTION_KEY:
            return self._stream_values(time_index)
        return [reader.read_slice(grid, entry, time_index, extra_indices) for grid in self.grids]

    def plot(self):
        dialog = self.dialog
        if dialog is None or self.layer_set is None:
            return False
        entry = self.entries.get(dialog.selected_variable())
        if entry is None:
            dialog.set_message("Select a variable to plot.")
            return False
        time_index = dialog.selected_time_index() if entry.has_time else 0
        extra_indices = dialog.selected_extra_indices()
        time_label = self.time_labels[time_index] if entry.has_time and self.time_labels else None
        extra_labels = [
            dimension.labels[index] for dimension, index in zip(entry.extra_dims, extra_indices)
        ]

        self._set_busy(True)
        started = time.perf_counter()
        try:
            values = self.read_values(entry, time_index, extra_indices)
            value_range = self.layer_set.plot(
                values,
                dataset_name(entry, time_label, [label.split(":")[0] for label in extra_labels]),
                entry.location,
                variable_changed=entry.key != self._last_plotted_key,
                description=entry.label,
            )
            self._last_plotted_key = entry.key
        except Exception as error:  # noqa: BLE001 - reported in the window
            dialog.set_message(f"Plot failed: {error}")
            return False
        finally:
            self._set_busy(False)

        details = [entry.label]
        if time_label:
            details.append(time_label)
        details.extend(extra_labels)
        range_text = (
            f"data range {value_range[0]:.4g} to {value_range[1]:.4g}" if value_range else "no valid values"
        )
        dialog.set_message(
            f"Plotted {' | '.join(details)} ({range_text}, {time.perf_counter() - started:.1f} s). "
            "Adjust colours in the layer Symbology; changes apply to all partitions."
        )
        try:
            self.iface.mapCanvas().refresh()
        except (AttributeError, RuntimeError):
            pass
        return True
