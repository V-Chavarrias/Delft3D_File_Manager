"""In-memory QGIS mesh layers for the Large MAP Viewer.

Each partition is shown as a ``mesh_memory`` layer built from its owned faces.
Plotting replaces the single dataset group of every layer; styling is shared
across partitions (one colour range) and Symbology edits are mirrored.
"""

import uuid

import numpy as np

try:
    from .large_map_reader import FACE
except ImportError:  # pragma: no cover - direct module usage
    from large_map_reader import FACE

try:
    from qgis.core import (
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsMeshDatasetIndex,
        QgsMeshLayer,
        QgsGraduatedSymbolRenderer,
        QgsPointXY,
        QgsProject,
        QgsRendererRange,
        QgsSymbol,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QVariant
    from qgis.PyQt.QtGui import QColor
except ImportError:  # pragma: no cover - only outside QGIS
    QgsFeature = QgsField = QgsGeometry = None
    QgsMeshDatasetIndex = QgsMeshLayer = QgsProject = None
    QgsGraduatedSymbolRenderer = QgsPointXY = None
    QgsRendererRange = QgsSymbol = QgsVectorLayer = QgsWkbTypes = None
    QVariant = QColor = None


_LARGE_MAP_SYNC_PROPERTY = "delft3d_large_map_sync_id"
_LARGE_MAP_DATASET_PROPERTY = "delft3d_large_map_dataset_group"
_PERSISTENT_SYNC_LINKS = {}
_PERSISTENT_SYNCING = set()


def _join_columns(columns):
    text = columns[0]
    for column in columns[1:]:
        text = np.char.add(np.char.add(text, ", "), column)
    return text


def mesh_memory_uri(node_x, node_y, faces):
    """Build a ``mesh_memory`` provider URI.

    ``faces`` is an (n_faces, n_max) integer array of 0-based node indices
    padded with negative values.
    """
    node_x = np.asarray(node_x, dtype=float)
    node_y = np.asarray(node_y, dtype=float)
    faces = np.asarray(faces, dtype=np.int64)
    if faces.ndim != 2 or len(faces) == 0:
        raise ValueError("The mesh has no faces")
    vertices = _join_columns([np.char.mod("%.17g", node_x), np.char.mod("%.17g", node_y)])

    valid = faces >= 0
    counts = valid.sum(axis=1)
    leading = valid == (np.arange(faces.shape[1])[np.newaxis, :] < counts[:, np.newaxis])
    lines = np.empty(len(faces), dtype=object)
    if bool(np.all(leading)):
        strings = faces.astype(str)
        for count in np.unique(counts):
            rows = np.nonzero(counts == count)[0]
            if count == 0:
                lines[rows] = ""
                continue
            lines[rows] = _join_columns([strings[rows, column] for column in range(int(count))])
    else:
        for row, face in enumerate(faces):
            lines[row] = ", ".join(str(int(node)) for node in face[face >= 0])
    if np.any(counts < 3):
        raise ValueError("The mesh contains faces with fewer than three nodes")
    return "\n".join(vertices.tolist()) + "\n---\n" + "\n".join(lines.tolist())


def dataset_group_name(name):
    """Memory mesh dataset names must not contain whitespace."""
    return "_".join(str(name).split()) or "value"


def dataset_definition(values, name, location, description=""):
    """Build the text definition accepted by ``QgsMeshLayer.addDatasets`` for memory meshes."""
    kind = "face" if location == FACE else "vertex"
    name = dataset_group_name(name)
    description = " ".join(str(description).split()) or name
    values = np.asarray(values, dtype=float).reshape(-1)
    body = "\n".join(np.char.mod("%.9g", values).tolist())
    return f"{kind} scalar {name}\n---\ndescription: {description}\n---\n0\n{body}"


def shared_range(values_list):
    """Return the finite (min, max) over all arrays, or ``None`` when no finite value exists."""
    minimum = None
    maximum = None
    for values in values_list:
        values = np.asarray(values, dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            continue
        low = float(finite.min())
        high = float(finite.max())
        minimum = low if minimum is None else min(minimum, low)
        maximum = high if maximum is None else max(maximum, high)
    if minimum is None:
        return None
    if minimum == maximum:
        pad = abs(minimum) * 1e-6 or 1e-6
        minimum -= pad
        maximum += pad
    return minimum, maximum


def _group_index_by_name(layer, name):
    for index in layer.datasetGroupsIndexes():
        if layer.datasetGroupMetadata(QgsMeshDatasetIndex(index)).name() == name:
            return index
    indexes = list(layer.datasetGroupsIndexes())
    return indexes[-1] if indexes else None


def _disconnect_persistent_sync(project, sync_id):
    registration = _PERSISTENT_SYNC_LINKS.pop((id(project), sync_id), None)
    if registration is None:
        return
    for layer, callback in registration["layers"].values():
        try:
            layer.rendererChanged.disconnect(callback)
        except (TypeError, RuntimeError):
            pass
    try:
        project.layersWillBeRemoved.disconnect(registration["remove_callback"])
    except (AttributeError, TypeError, RuntimeError):
        pass


def _layer_tree_group_path(project, layer):
    root = project.layerTreeRoot()
    node = root.findLayer(layer.id())
    if node is None:
        return ""
    names = []
    parent = node.parent()
    while parent is not None and parent != root:
        name = getattr(parent, "name", None)
        if callable(name) and name():
            names.append(str(name()))
        parent = parent.parent()
    return "/".join(reversed(names))


def _active_dataset_group_name(layer):
    settings = layer.rendererSettings()
    active = settings.activeScalarDatasetGroup()
    if active is None and hasattr(layer, "activeScalarDatasetGroup"):
        active = layer.activeScalarDatasetGroup()
    indexes = list(layer.datasetGroupsIndexes())
    for index in indexes:
        if active is not None and int(index) != int(active):
            continue
        name = layer.datasetGroupMetadata(QgsMeshDatasetIndex(index)).name()
        if name:
            return name
    return ""


def _mirror_persistent_renderer(source, project, sync_id):
    if sync_id in _PERSISTENT_SYNCING:
        return
    dataset_name = source.customProperty(_LARGE_MAP_DATASET_PROPERTY, "")
    if not dataset_name:
        return
    source_index = _group_index_by_name(source, dataset_name)
    if source_index is None:
        return

    source_settings = source.rendererSettings()
    scalar = source_settings.scalarSettings(source_index)
    native = source_settings.nativeMeshSettings()
    _PERSISTENT_SYNCING.add(sync_id)
    try:
        for target in project.mapLayers().values():
            if target is source or target.customProperty(_LARGE_MAP_SYNC_PROPERTY, "") != sync_id:
                continue
            target_name = target.customProperty(_LARGE_MAP_DATASET_PROPERTY, "")
            target_index = _group_index_by_name(target, target_name)
            if target_index is None:
                continue
            settings = target.rendererSettings()
            settings.setScalarSettings(target_index, scalar)
            settings.setNativeMeshSettings(native)
            target.setRendererSettings(settings)
            target.triggerRepaint()
    finally:
        _PERSISTENT_SYNCING.remove(sync_id)


def restore_persistent_symbology_links(project):
    """Reconnect saved Large MAP partition layers after a project is loaded."""
    for project_id, sync_id in tuple(_PERSISTENT_SYNC_LINKS):
        if project_id == id(project):
            _disconnect_persistent_sync(project, sync_id)

    grouped = {}
    legacy_groups = {}
    for layer in project.mapLayers().values():
        sync_id = str(layer.customProperty(_LARGE_MAP_SYNC_PROPERTY, "") or "")
        if sync_id:
            grouped.setdefault(sync_id, []).append(layer)
            continue
        group_path = _layer_tree_group_path(project, layer)
        if "(large map)" in group_path.lower():
            legacy_groups.setdefault(group_path, []).append(layer)

    for layers in legacy_groups.values():
        if len(layers) < 2:
            continue
        sync_id = uuid.uuid4().hex
        for layer in layers:
            layer.setCustomProperty(_LARGE_MAP_SYNC_PROPERTY, sync_id)
            dataset_name = _active_dataset_group_name(layer)
            if dataset_name:
                layer.setCustomProperty(_LARGE_MAP_DATASET_PROPERTY, dataset_name)
        grouped[sync_id] = layers

    for sync_id, layers in grouped.items():
        if len(layers) < 2:
            continue
        callbacks = {}
        for layer in layers:
            callback = lambda *_args, layer=layer, sync_id=sync_id: _mirror_persistent_renderer(
                layer, project, sync_id
            )
            layer.rendererChanged.connect(callback)
            callbacks[str(layer.id())] = (layer, callback)

        def on_layers_will_be_removed(layer_ids, sync_id=sync_id):
            registration = _PERSISTENT_SYNC_LINKS.get((id(project), sync_id))
            if registration is None:
                return
            removed_ids = {
                str(layer.id()) if callable(getattr(layer, "id", None)) else str(layer)
                for layer in layer_ids
            }
            for layer_id in removed_ids:
                registered = registration["layers"].pop(layer_id, None)
                if registered is not None:
                    layer, callback = registered
                    try:
                        layer.rendererChanged.disconnect(callback)
                    except (TypeError, RuntimeError):
                        pass
            if len(registration["layers"]) < 2:
                _disconnect_persistent_sync(project, sync_id)

        project.layersWillBeRemoved.connect(on_layers_will_be_removed)
        _PERSISTENT_SYNC_LINKS[(id(project), sync_id)] = {
            "layers": callbacks,
            "remove_callback": on_layers_will_be_removed,
        }


def clear_persistent_symbology_links(project):
    """Disconnect restored renderer links when the plugin is unloaded."""
    for project_id, sync_id in tuple(_PERSISTENT_SYNC_LINKS):
        if project_id == id(project):
            _disconnect_persistent_sync(project, sync_id)


class _LayerSlot:
    def __init__(self, grid, uri, name):
        self.grid = grid
        self.uri = uri
        self.name = name
        self.layer = None
        self.layer_id = None
        self.dataset_name = None
        self.group_index = None
        self.callback = None


class LargeMapLayerSet:
    """Owns one in-memory mesh layer per partition inside a layer-tree group."""

    def __init__(self, grids, group_name, crs=None, project=None, layer_name=None):
        self._project = project or QgsProject.instance()
        self._group_name = group_name
        self._group = None
        self._crs = crs
        self._sync_id = uuid.uuid4().hex
        self._syncing = False
        self._busy = False
        self._plotted = False
        self._can_remove = None
        multi = len(grids) > 1
        layer_name = layer_name or group_name
        self._slots = []
        for grid in grids:
            name = f"{layer_name} [{grid.partition_id}]" if multi and grid.partition_id is not None else layer_name
            self._slots.append(_LayerSlot(grid, mesh_memory_uri(grid.node_x, grid.node_y, grid.faces), name))
        self._project.layersWillBeRemoved.connect(self._on_layers_will_be_removed)

    # ------------------------------------------------------------------ layers
    @property
    def layers(self):
        return [slot.layer for slot in self._slots if slot.layer is not None]

    def has_layers(self):
        return bool(self._slots) and all(slot.layer is not None for slot in self._slots)

    def _ensure_group(self):
        root = self._project.layerTreeRoot()
        if self._group is not None:
            try:
                if self._group in root.findGroups(True):
                    return self._group
            except RuntimeError:
                pass
        self._group = root.insertGroup(0, self._group_name)
        return self._group

    def _new_layer(self, slot):
        layer = QgsMeshLayer(slot.uri, slot.name, "mesh_memory")
        if not layer.isValid():
            raise RuntimeError(f"Could not create the mesh layer for {slot.name}")
        layer.setCustomProperty("delft3d_mesh_source", slot.grid.path)
        layer.setCustomProperty(_LARGE_MAP_SYNC_PROPERTY, self._sync_id)
        if self._crs is not None and self._crs.isValid():
            layer.setCrs(self._crs)
        temporal = layer.temporalProperties()
        if temporal is not None and hasattr(temporal, "setIsActive"):
            temporal.setIsActive(False)
        return layer

    def _attach(self, slot, layer, position=None):
        self._project.addMapLayer(layer, False)
        group = self._ensure_group()
        if position is None:
            group.addLayer(layer)
        else:
            group.insertLayer(position, layer)
        slot.layer = layer
        slot.layer_id = layer.id()
        slot.callback = lambda layer=layer: self._on_renderer_changed(layer)
        layer.rendererChanged.connect(slot.callback)

    def create_layers(self):
        """Create (or recreate) missing layers; new layers show the mesh frame only."""
        for slot in self._slots:
            if slot.layer is not None:
                continue
            layer = self._new_layer(slot)
            settings = layer.rendererSettings()
            native = settings.nativeMeshSettings()
            native.setEnabled(True)
            settings.setNativeMeshSettings(native)
            layer.setRendererSettings(settings)
            slot.dataset_name = None
            slot.group_index = None
            self._attach(slot, layer)
        if not all(slot.dataset_name for slot in self._slots):
            self._plotted = False
        return self.layers

    def extent(self):
        extent = None
        for layer in self.layers:
            if extent is None:
                extent = layer.extent()
            else:
                extent.combineExtentWith(layer.extent())
        return extent

    def _on_layers_will_be_removed(self, layer_ids):
        if self._busy:
            return
        removed = set(layer_ids)
        for slot in self._slots:
            if slot.layer_id in removed:
                self._disconnect(slot)
                slot.layer = None
                slot.layer_id = None
                slot.dataset_name = None
                slot.group_index = None

    def _disconnect(self, slot):
        if slot.layer is not None and slot.callback is not None:
            try:
                slot.layer.rendererChanged.disconnect(slot.callback)
            except (TypeError, RuntimeError):
                pass
        slot.callback = None

    def dispose(self, remove_layers=False):
        try:
            self._project.layersWillBeRemoved.disconnect(self._on_layers_will_be_removed)
        except (TypeError, RuntimeError):
            pass
        ids = []
        for slot in self._slots:
            self._disconnect(slot)
            if slot.layer_id:
                ids.append(slot.layer_id)
            slot.layer = None
        if remove_layers and ids:
            self._project.removeMapLayers(ids)

    # ---------------------------------------------------------------- plotting
    def _supports_removal(self, layer):
        if self._can_remove is None:
            self._can_remove = hasattr(layer, "removeDatasets")
        return self._can_remove

    def _template_scalar_settings(self):
        for slot in self._slots:
            if slot.layer is not None and slot.group_index is not None:
                return slot.layer.rendererSettings().scalarSettings(slot.group_index)
        return None

    def _replace_layer(self, slot):
        """Fallback for QGIS < 3.42 (no removeDatasets): rebuild the layer in place."""
        old = slot.layer
        settings = old.rendererSettings()
        node = self._project.layerTreeRoot().findLayer(old.id())
        parent = node.parent() if node is not None else None
        position = parent.children().index(node) if parent is not None else None
        layer = self._new_layer(slot)
        layer.setRendererSettings(settings)
        self._disconnect(slot)
        old_id = slot.layer_id
        self._busy = True
        try:
            if parent is not None and parent is not self._group:
                self._group = parent
            self._attach(slot, layer, position)
            self._project.removeMapLayer(old_id)
        finally:
            self._busy = False
        slot.dataset_name = None
        slot.group_index = None
        return layer

    def plot(self, values_per_layer, dataset_name, location, variable_changed, description=""):
        """Replace the plotted dataset on all layers; returns the shared (min, max) or ``None``."""
        if len(values_per_layer) != len(self._slots):
            raise ValueError("One array of values per partition is required")
        self.create_layers()
        template = None if variable_changed else self._template_scalar_settings()
        keep_style = template is not None
        if template is None and variable_changed:
            template = self._template_scalar_settings()
        value_range = shared_range(values_per_layer)
        first_plot = not self._plotted

        self._syncing = True
        try:
            for slot, values in zip(self._slots, values_per_layer):
                layer = slot.layer
                if slot.dataset_name is not None:
                    if self._supports_removal(layer):
                        layer.removeDatasets(slot.dataset_name)
                    else:
                        layer = self._replace_layer(slot)
                if not layer.addDatasets(dataset_definition(values, dataset_name, location, description)):
                    raise RuntimeError(f"Could not add the plotted values to {slot.name}")
                slot.dataset_name = dataset_group_name(dataset_name)
                slot.group_index = _group_index_by_name(layer, slot.dataset_name)
                layer.setCustomProperty(_LARGE_MAP_DATASET_PROPERTY, slot.dataset_name)

            for slot in self._slots:
                layer = slot.layer
                settings = layer.rendererSettings()
                scalar = template if template is not None else settings.scalarSettings(slot.group_index)
                if not keep_style and value_range is not None:
                    scalar.setClassificationMinimumMaximum(value_range[0], value_range[1])
                settings.setScalarSettings(slot.group_index, scalar)
                settings.setActiveScalarDatasetGroup(slot.group_index)
                if first_plot:
                    native = settings.nativeMeshSettings()
                    native.setEnabled(False)
                    settings.setNativeMeshSettings(native)
                layer.setRendererSettings(settings)
                if hasattr(layer, "setStaticScalarDatasetIndex"):
                    layer.setStaticScalarDatasetIndex(QgsMeshDatasetIndex(slot.group_index, 0))
                layer.triggerRepaint()
        finally:
            self._syncing = False
        self._plotted = True
        return value_range

    def _on_renderer_changed(self, source):
        """Mirror Symbology edits of one partition layer to the other partitions."""
        if self._syncing or self._busy:
            return
        source_slot = next((slot for slot in self._slots if slot.layer is source), None)
        if source_slot is None or source_slot.group_index is None:
            return
        source_settings = source.rendererSettings()
        scalar = source_settings.scalarSettings(source_slot.group_index)
        native = source_settings.nativeMeshSettings()
        self._syncing = True
        try:
            for slot in self._slots:
                if slot is source_slot or slot.layer is None or slot.group_index is None:
                    continue
                settings = slot.layer.rendererSettings()
                settings.setScalarSettings(slot.group_index, scalar)
                settings.setNativeMeshSettings(native)
                slot.layer.setRendererSettings(settings)
                slot.layer.triggerRepaint()
        finally:
            self._syncing = False


_POINT_VALUE_FIELD = "delft3d_value"
_POINT_COLORS = ("#313695", "#74add1", "#fee090", "#f46d43", "#a50026")


class LargeMapPointLayerSet:
    """Owns one in-memory point layer per restart partition."""

    def __init__(self, grids, group_name, crs=None, project=None, layer_name=None):
        self._project = project or QgsProject.instance()
        self._group_name = group_name
        self._group = None
        self._crs = crs
        self._sync_id = uuid.uuid4().hex
        self._syncing = False
        self._busy = False
        self._plotted = False
        self._slots = []
        multi = len(grids) > 1
        layer_name = layer_name or group_name
        for grid in grids:
            name = f"{layer_name} [{grid.partition_id}]" if multi and grid.partition_id is not None else layer_name
            slot = _LayerSlot(grid, None, name)
            slot.feature_ids = []
            self._slots.append(slot)
        self._project.layersWillBeRemoved.connect(self._on_layers_will_be_removed)

    @property
    def layers(self):
        return [slot.layer for slot in self._slots if slot.layer is not None]

    def has_layers(self):
        return bool(self._slots) and all(slot.layer is not None for slot in self._slots)

    def _ensure_group(self):
        root = self._project.layerTreeRoot()
        if self._group is not None:
            try:
                if self._group in root.findGroups(True):
                    return self._group
            except RuntimeError:
                pass
        self._group = root.insertGroup(0, self._group_name)
        return self._group

    def _new_layer(self, slot):
        layer = QgsVectorLayer("Point", slot.name, "memory")
        if not layer.isValid():
            raise RuntimeError(f"Could not create the point layer for {slot.name}")
        if self._crs is not None and self._crs.isValid():
            layer.setCrs(self._crs)
        provider = layer.dataProvider()
        if not provider.addAttributes([QgsField(_POINT_VALUE_FIELD, QVariant.Double)]):
            raise RuntimeError(f"Could not create the value field for {slot.name}")
        layer.updateFields()
        field_index = layer.fields().indexOf(_POINT_VALUE_FIELD)
        features = []
        for x, y in zip(slot.grid.node_x, slot.grid.node_y):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))
            feature.setAttribute(field_index, None)
            features.append(feature)
        result = provider.addFeatures(features)
        if isinstance(result, tuple):
            if not result[0]:
                raise RuntimeError(f"Could not add restart points for {slot.name}")
        elif result is False:
            raise RuntimeError(f"Could not add restart points for {slot.name}")
        layer.updateExtents()
        slot.feature_ids = [feature.id() for feature in layer.getFeatures()]
        layer.setCustomProperty("delft3d_mesh_source", slot.grid.path)
        layer.setCustomProperty(_LARGE_MAP_SYNC_PROPERTY, self._sync_id)
        return layer

    def _attach(self, slot, layer, position=None):
        self._project.addMapLayer(layer, False)
        group = self._ensure_group()
        if position is None:
            group.addLayer(layer)
        else:
            group.insertLayer(position, layer)
        slot.layer = layer
        slot.layer_id = layer.id()
        slot.callback = lambda layer=layer: self._on_renderer_changed(layer)
        layer.rendererChanged.connect(slot.callback)

    def create_layers(self):
        """Create (or recreate) missing point layers."""
        for slot in self._slots:
            if slot.layer is not None:
                continue
            self._attach(slot, self._new_layer(slot))
        if not all(slot.dataset_name for slot in self._slots):
            self._plotted = False
        return self.layers

    def extent(self):
        extent = None
        for layer in self.layers:
            if extent is None:
                extent = layer.extent()
            else:
                extent.combineExtentWith(layer.extent())
        return extent

    def _on_layers_will_be_removed(self, layer_ids):
        if self._busy:
            return
        removed = set(layer_ids)
        for slot in self._slots:
            if slot.layer_id in removed:
                self._disconnect(slot)
                slot.layer = None
                slot.layer_id = None
                slot.dataset_name = None
                slot.group_index = None
                slot.feature_ids = []

    def _disconnect(self, slot):
        if slot.layer is not None and slot.callback is not None:
            try:
                slot.layer.rendererChanged.disconnect(slot.callback)
            except (TypeError, RuntimeError):
                pass
        slot.callback = None

    def dispose(self, remove_layers=False):
        try:
            self._project.layersWillBeRemoved.disconnect(self._on_layers_will_be_removed)
        except (TypeError, RuntimeError):
            pass
        ids = []
        for slot in self._slots:
            self._disconnect(slot)
            if slot.layer_id:
                ids.append(slot.layer_id)
            slot.layer = None
        if remove_layers and ids:
            self._project.removeMapLayers(ids)

    @staticmethod
    def _clone_renderer(renderer):
        clone = getattr(renderer, "clone", None)
        return clone() if callable(clone) else renderer

    @staticmethod
    def _renderer(value_range, template=None):
        if value_range is None:
            return None
        minimum, maximum = value_range
        width = (maximum - minimum) / len(_POINT_COLORS)
        template_symbols = []
        ranges_method = getattr(template, "ranges", None)
        template_ranges = ranges_method() if callable(ranges_method) else ranges_method or []
        for source_range in template_ranges:
            symbol_method = getattr(source_range, "symbol", None)
            source_symbol = symbol_method() if callable(symbol_method) else None
            if source_symbol is not None:
                template_symbols.append(source_symbol)
        ranges = []
        for index, color in enumerate(_POINT_COLORS):
            lower = minimum + index * width
            upper = maximum if index == len(_POINT_COLORS) - 1 else minimum + (index + 1) * width
            if template_symbols:
                symbol = LargeMapPointLayerSet._clone_renderer(template_symbols[index % len(template_symbols)])
            else:
                symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PointGeometry)
            if symbol is None:
                raise RuntimeError("Could not create the restart point symbol")
            if not template_symbols:
                symbol.setColor(QColor(color))
            ranges.append(
                QgsRendererRange(
                    lower,
                    upper,
                    symbol,
                    f"{lower:.4g} - {upper:.4g}",
                )
            )
        return QgsGraduatedSymbolRenderer(_POINT_VALUE_FIELD, ranges)

    def plot(self, values_per_layer, dataset_name, location, variable_changed, description=""):
        """Replace point values on all layers and return the shared data range."""
        del location, description
        if len(values_per_layer) != len(self._slots):
            raise ValueError("One array of values per partition is required")
        self.create_layers()
        value_range = shared_range(values_per_layer)
        first_plot = not self._plotted
        template = None
        if variable_changed and self._plotted and self._slots:
            template = self._slots[0].layer.renderer()
        self._syncing = True
        try:
            for slot, values in zip(self._slots, values_per_layer):
                values = np.asarray(values, dtype=float).reshape(-1)
                if len(values) != len(slot.feature_ids):
                    raise ValueError(
                        f"Expected {len(slot.feature_ids)} restart values for {slot.name}, got {len(values)}"
                    )
                field_index = slot.layer.fields().indexOf(_POINT_VALUE_FIELD)
                updates = {
                    int(feature_id): {
                        field_index: float(value) if np.isfinite(value) else None
                    }
                    for feature_id, value in zip(slot.feature_ids, values)
                }
                result = slot.layer.dataProvider().changeAttributeValues(updates)
                if result is False:
                    raise RuntimeError(f"Could not update restart values for {slot.name}")
                slot.layer.updateExtents()
                slot.dataset_name = dataset_name

            if variable_changed or first_plot:
                renderer = self._renderer(value_range, template)
                if renderer is not None:
                    for slot in self._slots:
                        slot.layer.setRenderer(self._clone_renderer(renderer))
            for slot in self._slots:
                slot.layer.triggerRepaint()
        finally:
            self._syncing = False
        self._plotted = True
        return value_range

    def _on_renderer_changed(self, source):
        """Mirror Symbology edits of one restart partition to the others."""
        if self._syncing or self._busy:
            return
        source_renderer = source.renderer()
        self._syncing = True
        try:
            for slot in self._slots:
                if slot.layer is source or slot.layer is None:
                    continue
                slot.layer.setRenderer(self._clone_renderer(source_renderer))
                slot.layer.triggerRepaint()
        finally:
            self._syncing = False
