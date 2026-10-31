"""Controller of the Large MAP Viewer: connects reader, layers and dialog."""

import math
import os
import time
import logging

try:
    from . import large_map_reader as reader
    from .large_map_layers import LargeMapLayerSet, LargeMapPointLayerSet
except ImportError:  # pragma: no cover - direct module usage
    import large_map_reader as reader
    from large_map_layers import LargeMapLayerSet, LargeMapPointLayerSet

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication

DEFAULT_EPSG = 28992
_PREFERRED_DEFAULTS = ("s1", "waterdepth", "ucmag")
LOGGER = logging.getLogger(__name__)


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
    """State and actions of one Large MAP / restart viewer window."""

    def __init__(self, iface, plugin=None):
        self.iface = iface
        self.plugin = plugin
        self.dialog = None
        self.layer_set = None
        self.paths = []
        self.grids = []
        self.entries = {}
        self.time_values = []
        self.time_labels = []
        self._stream_graph = None
        self._last_plotted_key = None
        self._point_map_tool = None
        self._point_previous_map_tool = None
        self._point_series_dialog = None

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
                on_point_series_requested=self.start_point_series_capture,
            )
        return self.dialog

    def open(self):
        dialog = self._ensure_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def close(self):
        self._cancel_point_series_capture()
        if self.layer_set is not None:
            self.layer_set.dispose(remove_layers=False)
            self.layer_set = None
        if self._point_series_dialog is not None:
            try:
                self._point_series_dialog.close()
                self._point_series_dialog.deleteLater()
            except RuntimeError:
                pass
            self._point_series_dialog = None
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
        except (RuntimeError, TypeError, ValueError) as error:
            LOGGER.warning("Could not zoom to the loaded large-map layers: %s", error)

    # ---------------------------------------------------------------- loading
    def load_file(self, path):
        """Read the grid of all partitions and display it; populate the selectors."""
        self._cancel_point_series_capture()
        dialog = self._ensure_dialog()
        progress = self._progress("Loading MAP/restart grid")
        self._set_busy(True)
        layer_set = None
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
            sediment_records = getattr(self.plugin, "_sediment_records", None)
            entries = reader.list_variables(paths[0], sediment_records)
            time_values, time_labels = reader.read_times(paths[0])
            crs = crs_from_info(*reader.read_crs_info(paths[0]))

            self._update_progress(progress, 75, "Building mesh layers...")
            base = reader.model_base_name(path)
            point_mode = any(getattr(grid, "point_mode", False) for grid in grids)
            layer_class = LargeMapPointLayerSet if point_mode else LargeMapLayerSet
            layer_set = layer_class(
                grids,
                self._group_name(base, point_mode),
                crs=crs,
                layer_name=base,
            )
            layer_set.create_layers()

            if self.layer_set is not None:
                self.layer_set.dispose(remove_layers=True)
            self.paths = paths
            self.grids = grids
            self.entries = {entry.key: entry for entry in entries}
            self.time_values = [float(value) for value in time_values]
            self.time_labels = list(time_labels)
            self.layer_set = layer_set
            self._stream_graph = None
            self._last_plotted_key = None
            self._zoom_to_layers()
        except Exception as error:  # noqa: BLE001 - reported in the window
            if layer_set is not None:
                layer_set.dispose(remove_layers=True)
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

    def _group_name(self, base, point_mode=False):
        unique = getattr(self.plugin, "_unique_group_name", None)
        name = f"{base} (Large MAP / Restart)" if point_mode else f"{base} (Large MAP)"
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
            dialog.set_point_series_enabled(False)
            return
        previous = dialog.selected_extra_indices()
        dimensions = [(dimension.name, dimension.labels) for dimension in entry.extra_dims]
        dialog.set_extra_dimensions(dimensions, previous)
        dialog.set_controls_enabled(True)
        dialog.set_time_enabled(entry.has_time and len(self.time_labels) > 0)
        dialog.set_point_series_enabled(True)

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
        sediment_records = getattr(self.plugin, "_sediment_records", None)
        return [
            reader.read_slice(grid, entry, time_index, extra_indices, sediment_records)
            for grid in self.grids
        ]

    def _cancel_point_series_capture(self):
        """Restore the prior map tool when point capture is cancelled."""
        tool = self._point_map_tool
        if tool is None:
            return
        try:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is tool:
                canvas.setMapTool(self._point_previous_map_tool)
        except (AttributeError, RuntimeError, TypeError):
            pass
        self._point_map_tool = None
        self._point_previous_map_tool = None

    def start_point_series_capture(self):
        """Arm a one-click map tool for the selected variable's time series."""
        dialog = self.dialog
        if dialog is None:
            return False
        entry = self.entries.get(dialog.selected_variable())
        if entry is None or not entry.has_time or not self.time_values:
            dialog.set_message("Select a time-dependent variable before choosing a point.")
            return False

        self._cancel_point_series_capture()
        from qgis.gui import QgsMapTool

        canvas = self.iface.mapCanvas()
        previous_tool = canvas.mapTool() if hasattr(canvas, "mapTool") else None
        extra_indices = dialog.selected_extra_indices()
        viewer = self
        left_button = getattr(Qt, "LeftButton", None)
        if left_button is None:
            left_button = getattr(getattr(Qt, "MouseButton", None), "LeftButton", None)

        class _LargeMapPointMapTool(QgsMapTool):
            def __init__(self):
                super().__init__(canvas)

            def canvasPressEvent(self, event):
                if event.button() != left_button:
                    return
                transform = canvas.getCoordinateTransform()
                point = transform.toMapCoordinates(event.pos().x(), event.pos().y())
                viewer._cancel_point_series_capture()
                viewer.plot_point_series(point, entry.key, extra_indices)

        self._point_previous_map_tool = previous_tool
        self._point_map_tool = _LargeMapPointMapTool()
        canvas.setMapTool(self._point_map_tool)
        dialog.set_message(
            f"Click the map to plot {entry.label} through all available times."
        )
        try:
            self.iface.messageBar().pushInfo(
                "Large MAP Viewer",
                "Click the map once to select the time-series location.",
            )
        except (AttributeError, RuntimeError):
            pass
        return True

    def _point_in_mesh_crs(self, point):
        """Transform a canvas point into the loaded MAP grid CRS."""
        from qgis.core import QgsPointXY

        point = QgsPointXY(float(point.x()), float(point.y()))
        if self.layer_set is None or not self.layer_set.layers:
            raise reader.LargeMapError("No MAP grid is loaded")
        try:
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            mesh_crs = self.layer_set.layers[0].crs()
        except (AttributeError, RuntimeError) as exc:
            raise reader.LargeMapError(f"Could not determine the map CRS: {exc}") from exc
        if (
            not callable(getattr(canvas_crs, "isValid", None))
            or not canvas_crs.isValid()
            or not callable(getattr(mesh_crs, "isValid", None))
            or not mesh_crs.isValid()
            or canvas_crs == mesh_crs
        ):
            return point
        try:
            return QgsCoordinateTransform(
                canvas_crs,
                mesh_crs,
                QgsProject.instance(),
            ).transform(point)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise reader.LargeMapError(
                f"Could not transform the point to the MAP grid CRS: {exc}"
            ) from exc

    def _ensure_point_series_dialog(self):
        if self._point_series_dialog is None:
            from .cross_section_profile_dialog import CrossSectionProfileDialog

            parent = self.iface.mainWindow() if self.iface is not None else None
            self._point_series_dialog = CrossSectionProfileDialog(parent, mesh_mode=False)
            self._point_series_dialog.setWindowTitle("Large MAP Time Series")
        return self._point_series_dialog

    def plot_point_series(self, point, variable_key=None, extra_indices=None):
        """Read and display one nearest mesh sample for every available time."""
        dialog = self.dialog
        if dialog is None or self.layer_set is None:
            return False
        variable_key = variable_key or dialog.selected_variable()
        entry = self.entries.get(variable_key)
        if entry is None:
            dialog.set_message("Select a variable to plot.")
            return False
        if not entry.has_time or not self.time_values:
            dialog.set_message("The selected variable has no temporal samples.")
            return False
        extra_indices = list(
            dialog.selected_extra_indices() if extra_indices is None else extra_indices
        )

        from .mesh_profile_sampler import nearest_mesh_sample_candidates

        try:
            mesh_point = self._point_in_mesh_crs(point)
            candidates = nearest_mesh_sample_candidates(
                self.grids,
                (mesh_point.x(), mesh_point.y()),
                entry.location,
            )
        except (reader.LargeMapError, RuntimeError, TypeError, ValueError) as error:
            dialog.set_message(f"Point time series failed: {error}")
            return False
        if not candidates:
            dialog.set_message(f"No {entry.location} samples are available in the MAP grid.")
            return False

        candidate_series = []
        self._set_busy(True)
        try:
            sediment_records = getattr(self.plugin, "_sediment_records", None)
            if entry.key == reader.STREAM_FUNCTION_KEY:
                candidate_series = [[] for _ in candidates]
                for time_index in range(len(self.time_values)):
                    partition_values = self._stream_values(time_index)
                    for candidate_index, (grid_index, local_index, _sample_point) in enumerate(candidates):
                        values = partition_values[grid_index]
                        candidate_series[candidate_index].append(values[local_index])
                    self.dialog.set_message(
                        f"Reading streamfunction time series: {time_index + 1}/{len(self.time_values)}"
                    )
                    QApplication.processEvents()
            else:
                for grid_index, local_index, _sample_point in candidates:
                    grid = self.grids[grid_index]
                    source_index = (
                        int(grid.node_index[local_index])
                        if entry.location == reader.NODE
                        else int(grid.face_index[local_index])
                    )
                    candidate_series.append(
                        reader.read_point_series(
                            grid,
                            entry,
                            source_index,
                            extra_indices,
                            sediment_records,
                        )
                    )

            values = [None] * len(self.time_values)
            for series in candidate_series:
                if len(series) != len(values):
                    raise reader.LargeMapError(
                        "The point data length does not match the MAP time coordinate"
                    )
                for time_index, value in enumerate(series):
                    if values[time_index] is not None:
                        continue
                    try:
                        numeric_value = float(value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(numeric_value):
                        values[time_index] = numeric_value
        except (
            reader.LargeMapError,
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            dialog.set_message(f"Point time series failed: {error}")
            return False
        finally:
            self._set_busy(False)

        sample_point = candidates[0][2]
        extra_labels = [
            dimension.labels[index]
            for dimension, index in zip(entry.extra_dims, extra_indices)
            if 0 <= index < len(dimension.labels)
        ]
        title = f"{entry.label} at ({sample_point[0]:g}, {sample_point[1]:g})"
        if extra_labels:
            title += " - " + ", ".join(extra_labels)
        chart = self._ensure_point_series_dialog()
        chart.set_profile(
            list(zip(self.time_values, values)),
            title,
            {"x_axis_label": "time", "y_axis_label": entry.label},
            message=(
                "No finite values were found at the nearest mesh sample."
                if not any(value is not None for value in values)
                else ""
            ),
        )
        chart.setWindowTitle("Large MAP Time Series")
        chart.show()
        chart.raise_()
        chart.activateWindow()
        dialog.set_message(
            f"Plotted {entry.label} at ({sample_point[0]:g}, {sample_point[1]:g}) "
            f"for {len(values)} time steps."
        )
        return True

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
