import copy
from types import SimpleNamespace

import numpy as np
import pytest

from Delft3DFileManager import large_map_layers as layers_module
from Delft3DFileManager.large_map_dialog import step_index
from Delft3DFileManager.large_map_reader import FACE, NODE, POINT, PartitionGrid, VariableEntry
from Delft3DFileManager.large_map_viewer import dataset_name, default_variable_key


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class FakeScalar:
    def __init__(self, ramp="default"):
        self.ramp = ramp
        self.minimum = None
        self.maximum = None

    def setClassificationMinimumMaximum(self, minimum, maximum):
        self.minimum, self.maximum = minimum, maximum


class FakeNative:
    def __init__(self):
        self.enabled = False

    def setEnabled(self, enabled):
        self.enabled = enabled

    def isEnabled(self):
        return self.enabled


class FakeSettings:
    def __init__(self):
        self.scalars = {}
        self.active = None
        self.native = FakeNative()

    def scalarSettings(self, index):
        return copy.deepcopy(self.scalars.get(index, FakeScalar()))

    def setScalarSettings(self, index, scalar):
        self.scalars[index] = copy.deepcopy(scalar)

    def setActiveScalarDatasetGroup(self, index):
        self.active = index

    def activeScalarDatasetGroup(self):
        return self.active

    def nativeMeshSettings(self):
        return copy.deepcopy(self.native)

    def setNativeMeshSettings(self, native):
        self.native = copy.deepcopy(native)


class FakeMetadata:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeLayer:
    counter = 0
    support_removal = True

    def __init__(self, uri, name, provider):
        FakeLayer.counter += 1
        self._id = f"layer{FakeLayer.counter}"
        self.uri, self.name, self.provider = uri, name, provider
        self.groups = []
        self.datasets = []
        self.settings = FakeSettings()
        self.custom_properties = {}
        self.rendererChanged = FakeSignal()
        self.static_index = None
        if FakeLayer.support_removal:
            self.removeDatasets = self._remove

    def id(self):
        return self._id

    def isValid(self):
        return True

    def setCrs(self, crs):
        self.crs = crs

    def setCustomProperty(self, key, value):
        self.custom_properties[key] = value

    def customProperty(self, key, default=None):
        return self.custom_properties.get(key, default)

    def temporalProperties(self):
        return None

    def rendererSettings(self):
        return copy.deepcopy(self.settings)

    def setRendererSettings(self, settings):
        self.settings = copy.deepcopy(settings)
        self.rendererChanged.emit()

    def addDatasets(self, definition):
        header = definition.split("\n", 1)[0].split()
        assert len(header) == 3
        self.groups.append(header[2])
        self.datasets.append(definition)
        return True

    def _remove(self, name):
        self.groups.remove(name)

    def datasetGroupsIndexes(self):
        return list(range(len(self.groups)))

    def datasetGroupMetadata(self, index):
        return FakeMetadata(self.groups[index[0]])

    def setStaticScalarDatasetIndex(self, index):
        self.static_index = index

    def triggerRepaint(self):
        pass


class FakeGroup:
    def __init__(self, name):
        self._name = name
        self.children_list = []

    def name(self):
        return self._name

    def addLayer(self, layer):
        self.children_list.append(layer)

    def insertLayer(self, position, layer):
        self.children_list.insert(position, layer)


class FakeRoot:
    def __init__(self):
        self.groups = []

    def insertGroup(self, index, name):
        group = FakeGroup(name)
        self.groups.insert(index, group)
        return group

    def findGroups(self, recursive):
        return list(self.groups)

    def findLayer(self, layer_id):
        return None


class FakeProject:
    def __init__(self):
        self.layersWillBeRemoved = FakeSignal()
        self.root = FakeRoot()
        self.map_layers = {}

    def layerTreeRoot(self):
        return self.root

    def mapLayers(self):
        return dict(self.map_layers)

    def addMapLayer(self, layer, add_to_legend):
        self.map_layers[layer.id()] = layer

    def removeMapLayer(self, layer_id):
        self.removeMapLayers([layer_id])

    def removeMapLayers(self, layer_ids):
        self.layersWillBeRemoved.emit(list(layer_ids))
        for layer_id in layer_ids:
            self.map_layers.pop(layer_id, None)


class FakeVectorFields:
    def indexOf(self, name):
        return 0 if name == "delft3d_value" else -1


class FakeVectorFeature:
    counter = 0

    def __init__(self, _fields=None):
        FakeVectorFeature.counter += 1
        self._id = FakeVectorFeature.counter
        self.attributes = {}
        self.geometry = None

    def id(self):
        return self._id

    def setGeometry(self, geometry):
        self.geometry = geometry

    def setAttribute(self, index, value):
        self.attributes[index] = value


class FakeVectorProvider:
    def __init__(self, layer):
        self.layer = layer

    def addAttributes(self, _fields):
        return True

    def addFeatures(self, features):
        self.layer.features.extend(features)
        return True, features

    def changeAttributeValues(self, updates):
        by_id = {feature.id(): feature for feature in self.layer.features}
        for feature_id, attributes in updates.items():
            for index, value in attributes.items():
                by_id[feature_id].attributes[index] = value
        return True


class FakeVectorLayer:
    counter = 0

    def __init__(self, _uri, name, _provider):
        FakeVectorLayer.counter += 1
        self._id = f"point{FakeVectorLayer.counter}"
        self.name = name
        self.features = []
        self.properties = {}
        self.rendererChanged = FakeSignal()
        self._renderer = None
        self._provider = FakeVectorProvider(self)

    def id(self):
        return self._id

    def isValid(self):
        return True

    def setCrs(self, crs):
        self.crs = crs

    def dataProvider(self):
        return self._provider

    def updateFields(self):
        pass

    def fields(self):
        return FakeVectorFields()

    def getFeatures(self):
        return list(self.features)

    def updateExtents(self):
        pass

    def extent(self):
        return SimpleNamespace(combineExtentWith=lambda _other: None)

    def setCustomProperty(self, key, value):
        self.properties[key] = value

    def customProperty(self, key, default=None):
        return self.properties.get(key, default)

    def setRenderer(self, renderer):
        self._renderer = renderer
        self.rendererChanged.emit()

    def renderer(self):
        return self._renderer

    def triggerRepaint(self):
        pass


class FakePoint:
    def __init__(self, x, y):
        self.x, self.y = x, y


class FakeGeometry:
    @staticmethod
    def fromPointXY(point):
        return point


class FakeSymbol:
    @staticmethod
    def defaultSymbol(_geometry_type):
        return FakeSymbol()

    def setColor(self, color):
        self.color = color


class FakeRendererRange:
    def __init__(self, lower, upper, symbol, label):
        self.lower, self.upper, self.symbol, self.label = lower, upper, symbol, label


class FakeGraduatedRenderer:
    def __init__(self, field, ranges):
        self.field, self.ranges = field, ranges

    def clone(self):
        return copy.deepcopy(self)


def _grid(part, offset=0.0):
    return PartitionGrid(
        path=f"p{part}.nc",
        partition_id=part,
        node_x=np.array([0.0, 1.0, 1.0, 0.0]) + offset,
        node_y=np.array([0.0, 0.0, 1.0, 1.0]),
        faces=np.array([[0, 1, 2, -1], [0, 2, 3, -1]]),
        face_index=np.array([0, 1]),
        node_index=np.arange(4),
        ghost_filtered=True,
    )


def _point_grid(part, offset=0.0):
    return PartitionGrid(
        path=f"r{part}.nc",
        partition_id=part,
        node_x=np.array([0.0, 1.0]) + offset,
        node_y=np.array([0.0, 1.0]),
        faces=np.empty((0, 0), dtype=np.int64),
        face_index=np.array([0, 1]),
        node_index=np.array([0, 1]),
        ghost_filtered=True,
        point_mode=True,
    )


@pytest.fixture
def layer_set(monkeypatch):
    monkeypatch.setattr(layers_module, "QgsMeshLayer", FakeLayer)
    monkeypatch.setattr(layers_module, "QgsMeshDatasetIndex", lambda *args: args)
    FakeLayer.support_removal = True
    project = FakeProject()
    result = layers_module.LargeMapLayerSet([_grid(0), _grid(1, 1.0)], "model (Large MAP)", project=project, layer_name="model")
    result.create_layers()
    return result, project


@pytest.fixture
def point_layer_set(monkeypatch):
    monkeypatch.setattr(layers_module, "QgsVectorLayer", FakeVectorLayer)
    monkeypatch.setattr(layers_module, "QgsFeature", FakeVectorFeature)
    monkeypatch.setattr(layers_module, "QgsField", lambda *_args: object())
    monkeypatch.setattr(layers_module, "QgsGeometry", FakeGeometry)
    monkeypatch.setattr(layers_module, "QgsPointXY", FakePoint)
    monkeypatch.setattr(layers_module, "QgsSymbol", FakeSymbol)
    monkeypatch.setattr(layers_module, "QgsRendererRange", FakeRendererRange)
    monkeypatch.setattr(layers_module, "QgsGraduatedSymbolRenderer", FakeGraduatedRenderer)
    monkeypatch.setattr(layers_module, "QgsWkbTypes", SimpleNamespace(PointGeometry=1))
    monkeypatch.setattr(layers_module, "QVariant", SimpleNamespace(Double="double"))
    monkeypatch.setattr(layers_module, "QColor", lambda value: value)
    project = FakeProject()
    result = layers_module.LargeMapPointLayerSet(
        [_point_grid(0), _point_grid(1, 10.0)],
        "restart (Large MAP / Restart)",
        project=project,
        layer_name="restart",
    )
    result.create_layers()
    return result, project


def _active_scalar(layer):
    return layer.settings.scalars[layer.settings.active]


def test_mesh_memory_uri_handles_mixed_polygons():
    uri = layers_module.mesh_memory_uri([0, 1, 1, 0, 0.5], [0, 0, 1, 1, 2], [[0, 1, 2, 3], [3, 2, 4, -1]])
    vertices, faces = uri.split("\n---\n")
    assert vertices.splitlines() == ["0, 0", "1, 0", "1, 1", "0, 1", "0.5, 2"]
    assert faces.splitlines() == ["0, 1, 2, 3", "3, 2, 4"]
    uri = layers_module.mesh_memory_uri([0, 1, 1], [0, 0, 1], [[-1, 0, 1, 2]])
    assert uri.split("\n---\n")[1] == "0, 1, 2"
    with pytest.raises(ValueError):
        layers_module.mesh_memory_uri([0, 1], [0, 0], [[0, 1, -1]])


def test_dataset_definition_and_shared_range():
    text = layers_module.dataset_definition([1.5, np.nan], "water level t 1", FACE, "Water level [m]")
    assert text.splitlines() == [
        "face scalar water_level_t_1",
        "---",
        "description: Water level [m]",
        "---",
        "0",
        "1.5",
        "nan",
    ]
    assert layers_module.dataset_definition([1], "z", NODE).startswith("vertex scalar z\n")
    assert layers_module.shared_range([np.array([1.0, np.nan]), np.array([-2.0, 5.0])]) == (-2.0, 5.0)
    assert layers_module.shared_range([np.array([np.nan])]) is None
    low, high = layers_module.shared_range([np.array([3.0])])
    assert low < 3.0 < high


def test_layers_are_created_with_frame_and_partition_names(layer_set):
    result, project = layer_set
    assert [layer.name for layer in result.layers] == ["model [0]", "model [1]"]
    assert all(layer.provider == "mesh_memory" for layer in result.layers)
    assert all(layer.settings.native.enabled for layer in result.layers)
    assert project.root.groups[0].name() == "model (Large MAP)"
    assert len(project.root.groups[0].children_list) == 2


def test_large_map_layers_keep_original_mesh_sources(layer_set):
    result, _project = layer_set

    assert [layer.customProperty("delft3d_mesh_source") for layer in result.layers] == [
        result._slots[0].grid.path,
        result._slots[1].grid.path,
    ]


def test_plot_uses_shared_range_and_keeps_style_for_same_variable(layer_set):
    result, _project = layer_set
    rng = result.plot([np.array([1.0, 2.0]), np.array([3.0, 10.0])], "s1 t0", FACE, variable_changed=True)
    assert rng == (1.0, 10.0)
    for layer in result.layers:
        assert layer.groups == ["s1_t0"]
        assert not layer.settings.native.enabled
        assert (_active_scalar(layer).minimum, _active_scalar(layer).maximum) == (1.0, 10.0)

    # A Symbology edit on one partition is mirrored to the other.
    first, second = result.layers
    settings = first.rendererSettings()
    scalar = settings.scalarSettings(settings.active)
    scalar.ramp = "viridis"
    scalar.setClassificationMinimumMaximum(2.0, 4.0)
    settings.setScalarSettings(settings.active, scalar)
    first.setRendererSettings(settings)
    assert _active_scalar(second).ramp == "viridis"
    assert (_active_scalar(second).minimum, _active_scalar(second).maximum) == (2.0, 4.0)

    # Same variable (time/index step): the user's style and range are kept.
    result.plot([np.array([0.0, 50.0]), np.array([3.0, 4.0])], "s1 t1", FACE, variable_changed=False)
    for layer in result.layers:
        assert layer.groups == ["s1_t1"]
        assert _active_scalar(layer).ramp == "viridis"
        assert (_active_scalar(layer).minimum, _active_scalar(layer).maximum) == (2.0, 4.0)

    # New variable: colour ramp kept, range reset to the shared data range.
    result.plot([np.array([-1.0, 0.0]), np.array([0.5, 0.7])], "bl", FACE, variable_changed=True)
    for layer in result.layers:
        assert layer.groups == ["bl"]
        assert _active_scalar(layer).ramp == "viridis"
        assert (_active_scalar(layer).minimum, _active_scalar(layer).maximum) == (-1.0, 0.7)


def test_persistent_symbology_links_restore_after_project_reload(layer_set):
    result, project = layer_set
    result.plot([np.array([1.0, 2.0]), np.array([3.0, 4.0])], "s1 t0", FACE, variable_changed=True)
    first, second = result.layers
    sync_id = first.customProperty("delft3d_large_map_sync_id")
    assert sync_id
    assert second.customProperty("delft3d_large_map_sync_id") == sync_id

    unrelated_set = layers_module.LargeMapLayerSet(
        [_grid(2), _grid(3, 1.0)],
        "unrelated (Large MAP)",
        project=project,
        layer_name="unrelated",
    )
    unrelated_set.plot(
        [np.array([1.0, 2.0]), np.array([3.0, 4.0])],
        "s1 t0",
        FACE,
        variable_changed=True,
    )
    unrelated_first, unrelated_second = unrelated_set.layers

    result.dispose()
    unrelated_set.dispose()
    layers_module.restore_persistent_symbology_links(project)
    layers_module.restore_persistent_symbology_links(project)

    settings = first.rendererSettings()
    scalar = settings.scalarSettings(settings.active)
    scalar.ramp = "viridis"
    settings.setScalarSettings(settings.active, scalar)
    first.setRendererSettings(settings)

    assert _active_scalar(second).ramp == "viridis"
    assert _active_scalar(unrelated_first).ramp == "default"
    assert _active_scalar(unrelated_second).ramp == "default"
    assert len(first.rendererChanged.callbacks) == 1

    project.removeMapLayers([layer.id() for layer in project.map_layers.values()])


def test_plot_recreates_layers_without_dataset_removal_support(monkeypatch, layer_set):
    result, project = layer_set
    result.plot([np.array([1.0, 2.0]), np.array([3.0, 4.0])], "a", FACE, variable_changed=True)
    old_ids = [layer.id() for layer in result.layers]
    result._can_remove = False
    result.plot([np.array([1.0, 2.0]), np.array([3.0, 4.0])], "b", FACE, variable_changed=False)
    new_ids = [layer.id() for layer in result.layers]
    assert set(old_ids).isdisjoint(new_ids)
    assert set(project.map_layers) == set(new_ids)
    assert all(layer.groups == ["b"] for layer in result.layers)


def test_removed_layers_are_recreated_on_next_plot(layer_set):
    result, project = layer_set
    result.plot([np.array([1.0, 2.0]), np.array([3.0, 4.0])], "a", FACE, variable_changed=True)
    project.removeMapLayer(result.layers[0].id())
    assert not result.has_layers()
    result.plot([np.array([1.0, 2.0]), np.array([3.0, 4.0])], "a", FACE, variable_changed=False)
    assert result.has_layers()
    assert len(project.map_layers) == 2
    result.dispose(remove_layers=True)
    assert project.map_layers == {}
    assert project.layersWillBeRemoved.callbacks == []


def test_plot_requires_one_array_per_partition(layer_set):
    result, _project = layer_set
    with pytest.raises(ValueError):
        result.plot([np.array([1.0, 2.0])], "a", FACE, variable_changed=True)


def test_restart_point_layers_store_values_and_share_renderer(point_layer_set):
    result, project = point_layer_set

    assert [layer.name for layer in result.layers] == ["restart [0]", "restart [1]"]
    assert all(len(layer.features) == 2 for layer in result.layers)
    value_range = result.plot(
        [np.array([1.0, 2.0]), np.array([3.0, np.nan])],
        "s1_t0",
        POINT,
        variable_changed=True,
    )

    assert value_range == (1.0, 3.0)
    assert [feature.attributes[0] for feature in result.layers[0].features] == [1.0, 2.0]
    assert [feature.attributes[0] for feature in result.layers[1].features] == [3.0, None]
    assert result.layers[0].renderer().field == "delft3d_value"
    assert result.layers[1].renderer().ranges[-1].upper == 3.0
    assert project.root.groups[0].name() == "restart (Large MAP / Restart)"


def test_restart_point_layers_reject_value_count_mismatch(point_layer_set):
    result, _project = point_layer_set

    with pytest.raises(ValueError, match="Expected 2 restart values"):
        result.plot([np.array([1.0]), np.array([2.0, 3.0])], "s1", POINT, True)


def test_step_index_clamps_at_the_ends():
    assert step_index(0, 3, 1) == 1
    assert step_index(2, 3, 1) is None
    assert step_index(0, 3, -1) is None
    assert step_index(1, 3, -1) == 0
    assert step_index(-1, 3, 1) is None
    assert step_index(0, 0, 1) is None


def test_viewer_default_variable_and_dataset_names():
    entries = [
        VariableEntry("derived:froude_number", "Froude", FACE, True, derived=True),
        VariableEntry("mesh2d_czs", "Chezy", FACE, True),
        VariableEntry("mesh2d_s1", "Water level", FACE, True),
    ]
    assert default_variable_key(entries) == "mesh2d_s1"
    assert default_variable_key(entries[:2]) == "derived:froude_number"
    assert default_variable_key([]) is None
    assert dataset_name(entries[0], "2020-01-01 01:00:00") == "froude_number_2020-01-01_01:00:00"
    static = VariableEntry("mesh2d_sbxcum", "Transport", FACE, False)
    assert dataset_name(static, "2020-01-01", ["2"]) == "mesh2d_sbxcum_2"
