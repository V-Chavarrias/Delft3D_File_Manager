import copy
from types import SimpleNamespace

import Delft3DFileManager.Delft3DFileManager as plugin_module


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class RendererSettings:
    def __init__(self, style="default"):
        self.style = style
        self.active_group = 0

    def activeScalarDatasetGroup(self):
        return self.active_group


class MeshLayer:
    def __init__(self, layer_id, source):
        self._id = layer_id
        self._source = source
        self.properties = {"delft3d_mesh_source": source}
        self.settings = RendererSettings()
        self.rendererChanged = Signal()
        self.activeScalarDatasetGroupChanged = Signal()
        self.activeVectorDatasetGroupChanged = Signal()

    def id(self):
        return self._id

    def customProperty(self, key, default=None):
        return self.properties.get(key, default)

    def setCustomProperty(self, key, value):
        self.properties[key] = value

    def source(self):
        return self._source

    def activeScalarDatasetGroup(self):
        return self.settings.active_group

    def activeVectorDatasetGroup(self):
        return None

    def setActiveScalarDatasetGroup(self, index):
        self.settings.active_group = index
        self.activeScalarDatasetGroupChanged.emit()

    def setActiveVectorDatasetGroup(self, _index):
        self.activeVectorDatasetGroupChanged.emit()

    def rendererSettings(self):
        return copy.deepcopy(self.settings)

    def setRendererSettings(self, settings):
        self.settings = copy.deepcopy(settings)
        self.rendererChanged.emit()

    def triggerRepaint(self):
        pass


class Root:
    def findLayer(self, _layer_id):
        return None


class Project:
    def __init__(self):
        self._layers = {}
        self.root = Root()

    def mapLayers(self):
        return dict(self._layers)

    def layerTreeRoot(self):
        return self.root


def test_project_read_restores_partition_renderer_sync(monkeypatch):
    project = Project()
    layers = [
        MeshLayer("partition-0", r"C:\runs\run_0000_map.nc"),
        MeshLayer("partition-1", r"C:\runs\run_0001_map.nc"),
    ]
    project._layers = {layer.id(): layer for layer in layers}

    class ProjectProvider:
        @staticmethod
        def instance():
            return project

    monkeypatch.setattr(plugin_module, "QgsProject", ProjectProvider)
    iface = SimpleNamespace(projectRead=Signal())
    manager = plugin_module.Delft3DFileManager(iface)
    manager._connect_partition_mesh_sync_restore()

    sync_id = layers[0].customProperty("delft3d_partition_mesh_sync_id")
    assert sync_id
    assert layers[1].customProperty("delft3d_partition_mesh_sync_id") == sync_id

    iface.projectRead.emit()
    edited = layers[0].rendererSettings()
    edited.style = "custom-ramp"
    layers[0].setRendererSettings(edited)

    assert layers[1].rendererSettings().style == "custom-ramp"
    assert len(layers[0].rendererChanged.callbacks) == 1

    manager._disconnect_partition_mesh_sync_restore()
    manager._disconnect_partition_mesh_sync_sessions()
