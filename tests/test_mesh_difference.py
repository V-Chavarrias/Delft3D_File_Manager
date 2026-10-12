from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

import numpy as np
import pytest
from netCDF4 import Dataset

import Delft3DFileManager.Delft3DFileManager as plugin_module
from Delft3DFileManager import mesh_difference as difference


class Point:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


VERTICES = [Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 1)]
FACES = [(0, 1, 2), (0, 2, 3)]


class Reference:
    def __init__(self, milliseconds=None):
        self.milliseconds = milliseconds

    def isValid(self):
        return self.milliseconds is not None

    def toMSecsSinceEpoch(self):
        return self.milliseconds


class Metadata:
    def __init__(self, name="Water level", location=1, scalar=True, units="m",
                 temporal=False, reference=None):
        self._name, self._location, self._scalar = name, location, scalar
        self._units, self._temporal, self._reference = units, temporal, Reference(reference)

    def name(self):
        return self._name

    def dataType(self):
        return self._location

    def isScalar(self):
        return self._scalar

    def extraOptions(self):
        return {"units": self._units}

    def isTemporal(self):
        return self._temporal

    def referenceTime(self):
        return self._reference


class Block:
    def __init__(self, values=(), count=0, valid=True, flags=()):
        self._values, self._count, self._valid, self._flags = values, count, valid, flags

    def isValid(self):
        return self._valid

    def count(self):
        return self._count

    def values(self):
        return np.asarray(self._values).ravel().tolist()

    def active(self):
        return list(self._flags)


class MeshLayer:
    def __init__(self, values, metadata=None, times=None, name="Mesh", flags=()):
        self.groups = {0: (metadata or Metadata(), values, times or [0])}
        self._name, self.flags = name, flags
        self._crs = SimpleNamespace(
            isValid=lambda: True, isGeographic=lambda: False,
            toWkt=lambda: "test CRS", authid=lambda: "EPSG:28992",
        )

    def name(self):
        return self._name

    def source(self):
        return self._name + ".nc"

    def isValid(self):
        return True

    def crs(self):
        return self._crs

    def datasetGroupsIndexes(self):
        return list(self.groups)

    def datasetGroupMetadata(self, index):
        return self.groups[index.group][0]

    def datasetCount(self, index):
        return len(self.groups[index.group][1])

    def datasetMetadata(self, index):
        return SimpleNamespace(isValid=lambda: True, time=lambda: self.groups[index.group][2][index.dataset])

    def datasetValues(self, index, start, count):
        assert start == 0
        return Block(self.groups[index.group][1][index.dataset], count)

    def areFacesActive(self, index, start, count):
        return Block(count=count, flags=self.flags)


@pytest.fixture(autouse=True)
def mesh_api(monkeypatch):
    monkeypatch.setattr(
        difference, "_index",
        lambda group, dataset=0: SimpleNamespace(group=group, dataset=dataset),
    )
    monkeypatch.setattr(
        sys.modules["qgis.core"], "QgsMeshDatasetGroupMetadata",
        SimpleNamespace(DataOnVertices=0, DataOnFaces=1, DataOnVolumes=2, DataOnEdges=3),
    )


def prepare_and_write(path, left, right):
    groups, skipped = difference.prepare_groups(left, right)
    difference.write_difference(path, left, right, VERTICES, FACES, groups)
    return groups, skipped


def test_static_difference_persists_topology_crs_and_missing_data(tmp_path):
    left = MeshLayer([[5, np.nan]], name="A")
    right = MeshLayer([[2, 9]], name="B")
    path = tmp_path / "diff.nc"
    groups, skipped = prepare_and_write(path, left, right)
    assert len(groups) == 1 and not skipped
    with Dataset(path) as output:
        assert "time" not in output.dimensions
        assert output.description == "Mesh difference: A - B"
        assert output.variables["projected_coordinate_system"].epsg == 28992
        assert output.variables["mesh2d"].face_dimension == "mesh2d_nFaces"
        np.testing.assert_array_equal(output.variables["mesh2d_face_nodes"][:], FACES)
        variable = output.variables["difference_0"]
        assert variable.dimensions == ("mesh2d_nFaces",)
        assert variable.location == "face" and variable.units == "m"
        assert variable[0] == 3 and np.ma.is_masked(variable[1])


def test_absolute_matching_times_with_different_origins_and_order(tmp_path):
    left = MeshLayer(
        [[10, 20], [30, 40], [50, 60]],
        Metadata(temporal=True, reference=0), [0, 1, 2],
    )
    right = MeshLayer(
        [[3, 4], [1, 2], [100, 200]],
        Metadata(temporal=True, reference=3_600_000), [1, 0, 2],
    )
    path = tmp_path / "temporal.nc"
    groups, _ = prepare_and_write(path, left, right)
    assert groups[0].pairs == [(3_600_000, 1, 1), (7_200_000, 2, 0)]
    with Dataset(path) as output:
        np.testing.assert_array_equal(output.variables["time"][:], [0, 3600])
        assert output.variables["time"].units.startswith("seconds since 1970-01-01 01:00:00")
        np.testing.assert_array_equal(output.variables["difference_0"][:], [[29, 38], [47, 56]])


@pytest.mark.parametrize("static_left", [True, False])
def test_static_temporal_broadcast_and_subtraction_order(tmp_path, static_left):
    static = MeshLayer([[2, 4]])
    temporal = MeshLayer(
        [[10, 20], [30, 40]], Metadata(temporal=True), [0, 2],
    )
    left, right = (static, temporal) if static_left else (temporal, static)
    path = tmp_path / "broadcast.nc"
    prepare_and_write(path, left, right)
    with Dataset(path) as output:
        expected = np.array([[8, 16], [28, 36]]) * (-1 if static_left else 1)
        np.testing.assert_array_equal(output.variables["difference_0"][:], expected)
        np.testing.assert_array_equal(output.variables["time"][:], [0, 7200])
        assert output.variables["time"].units == "seconds"


def test_vector_node_difference_is_component_wise(tmp_path):
    metadata = Metadata(name="Velocity", location=0, scalar=False, units="m/s")
    left = MeshLayer([[[5, 2], [4, 8], [9, 1], [3, 6]]], metadata)
    right = MeshLayer([[[1, 5], [2, 3], [1, 1], [7, 4]]], metadata)
    path = tmp_path / "vectors.nc"
    prepare_and_write(path, left, right)
    with Dataset(path) as output:
        x, y = output.variables["difference_0_x"], output.variables["difference_0_y"]
        assert x.location == "node"
        assert x.long_name == "x component of Velocity difference (A - B)"
        assert y.long_name == "y component of Velocity difference (A - B)"
        assert x.dimensions == ("time", "mesh2d_nNodes")
        assert x.source_is_temporal == 0
        np.testing.assert_array_equal(output.variables["time"][:], [0])
        np.testing.assert_array_equal(x[:], [[4, 2, 8, -4]])
        np.testing.assert_array_equal(y[:], [[-3, 5, 0, 2]])


def test_static_vector_repeats_on_shared_temporal_axis(tmp_path):
    metadata = Metadata(name="Velocity", scalar=False)
    left = MeshLayer([[[5, 8], [10, 12]]], metadata)
    right = MeshLayer([[[2, 3], [4, 5]]], metadata)
    temporal = Metadata(name="Level", temporal=True)
    left.groups[7] = (temporal, [[10, 20], [30, 40]], [0, 1])
    right.groups[8] = (temporal, [[2, 3], [4, 5]], [0, 1])
    path = tmp_path / "constant_vectors.nc"
    prepare_and_write(path, left, right)
    with Dataset(path) as output:
        np.testing.assert_array_equal(output.variables["difference_1_x"][:], [[3, 6], [3, 6]])
        np.testing.assert_array_equal(output.variables["difference_1_y"][:], [[5, 7], [5, 7]])


def test_group_specific_common_times_use_union_with_missing_rows(tmp_path):
    metadata = Metadata(temporal=True)
    left = MeshLayer([[10, 20], [30, 40]], metadata, [0, 1])
    right = MeshLayer([[1, 2]], metadata, [1])
    extra = Metadata(name="Depth", temporal=True)
    left.groups[5] = (extra, [[7, 8]], [0])
    right.groups[9] = (extra, [[2, 3]], [0])
    path = tmp_path / "union.nc"
    prepare_and_write(path, left, right)
    with Dataset(path) as output:
        np.testing.assert_array_equal(output.variables["time"][:], [0, 3600])
        depth = output.variables["difference_0"][:]
        level = output.variables["difference_1"][:]
        np.testing.assert_array_equal(depth[0], [5, 5])
        assert np.ma.getmaskarray(depth[1]).all()
        assert np.ma.getmaskarray(level[0]).all()
        np.testing.assert_array_equal(level[1], [29, 38])


@pytest.mark.parametrize("metadata,reason", [
    (Metadata(location=0), "different data locations"),
    (Metadata(scalar=False), "scalar/vector mismatch"),
    (Metadata(units="cm"), "different declared units"),
    (Metadata(location=2), "unsupported"),
    (Metadata(name="Depth"), "not present"),
])
def test_incompatible_groups_are_rejected(metadata, reason):
    with pytest.raises(ValueError, match=reason):
        difference.prepare_groups(MeshLayer([[1, 2]]), MeshLayer([[3, 4]], metadata))


def test_partial_success_reports_every_skipped_group():
    left, right = MeshLayer([[5, 6]]), MeshLayer([[1, 2]])
    left.groups[2] = (Metadata(name="Extra"), [[1, 2]], [0])
    right.groups[5] = (Metadata(name="Extra", units="cm"), [[1, 2]], [0])
    groups, skipped = difference.prepare_groups(left, right)
    assert [group.name for group in groups] == ["Water level"]
    assert skipped == ["Extra: different declared units"]


def test_duplicate_names_are_not_arbitrarily_paired():
    left, right = MeshLayer([[5, 6]]), MeshLayer([[1, 2]])
    left.groups[8] = left.groups[0]
    with pytest.raises(ValueError, match="ambiguous duplicate"):
        difference.prepare_groups(left, right)


@pytest.mark.parametrize("left_times,right_times,reason", [
    ([0, 1], [2, 3], "no common timestamps"),
    ([0, 0], [0, 1], "duplicate timestamps"),
    ([0, np.nan], [0, 1], "not finite"),
])
def test_invalid_or_disjoint_times_are_explicit(left_times, right_times, reason):
    metadata = Metadata(temporal=True)
    with pytest.raises(ValueError, match=reason):
        difference.prepare_groups(
            MeshLayer([[1, 2], [3, 4]], metadata, left_times),
            MeshLayer([[1, 2], [3, 4]], metadata, right_times),
        )


def test_absolute_relative_mismatch_is_rejected():
    with pytest.raises(ValueError, match="absolute reference time"):
        difference.prepare_groups(
            MeshLayer([[1, 2]], Metadata(temporal=True, reference=0)),
            MeshLayer([[1, 2]], Metadata(temporal=True)),
        )


def test_layer_reference_time_fallback_matches_absolute_times():
    left = MeshLayer([[10, 20]], Metadata(temporal=True), [1])
    left.temporalProperties = lambda: SimpleNamespace(referenceTime=lambda: Reference(0))
    right = MeshLayer(
        [[1, 2]], Metadata(temporal=True, reference=3_600_000), [0],
    )
    groups, skipped = difference.prepare_groups(left, right)
    assert not skipped and groups[0].absolute_time
    assert groups[0].pairs == [(3_600_000, 0, 0)]


def test_absolute_and_relative_group_axes_cannot_share_output():
    left = MeshLayer([[10, 20]], Metadata(temporal=True, reference=0))
    right = MeshLayer([[1, 2]], Metadata(temporal=True, reference=0))
    relative = Metadata(name="Relative", temporal=True)
    left.groups[2] = (relative, [[1, 2]], [0])
    right.groups[3] = (relative, [[1, 2]], [0])
    with pytest.raises(ValueError, match="Cannot combine absolute and relative"):
        difference.prepare_groups(left, right)


def test_single_timestep_temporal_group_stays_temporal(tmp_path):
    path = tmp_path / "one_time.nc"
    metadata = Metadata(temporal=True)
    prepare_and_write(path, MeshLayer([[8, 9]], metadata), MeshLayer([[1, 2]], metadata))
    with Dataset(path) as output:
        assert len(output.dimensions["time"]) == 1
        assert output.variables["difference_0"].dimensions == ("time", "mesh2d_nFaces")


def test_face_inactivity_and_infinite_values_propagate(tmp_path):
    path = tmp_path / "inactive.nc"
    prepare_and_write(
        path, MeshLayer([[10, np.inf]], flags=(False, True)), MeshLayer([[2, 3]])
    )
    with Dataset(path) as output:
        assert np.ma.getmaskarray(output.variables["difference_0"][:]).all()


def test_node_values_without_any_active_adjacent_face_are_masked(tmp_path):
    metadata = Metadata(location=0)
    path = tmp_path / "inactive_nodes.nc"
    prepare_and_write(
        path,
        MeshLayer([[10, 20, 30, 40]], metadata, flags=(True, False)),
        MeshLayer([[1, 2, 3, 4]], metadata),
    )
    with Dataset(path) as output:
        values = output.variables["difference_0"][:]
        np.testing.assert_array_equal(values[:3], [9, 18, 27])
        assert np.ma.is_masked(values[3])


@pytest.mark.parametrize("vertices,faces,reason", [
    (VERTICES[:-1], FACES, "node coordinates"),
    ([Point(0, 0), Point(2, 0), Point(1, 1), Point(0, 1)], FACES, "node coordinates"),
    (VERTICES, list(reversed(FACES)), "face connectivity"),
    ([Point(np.nan, 0)] + VERTICES[1:], FACES, "finite"),
])
def test_topology_must_match_exactly(vertices, faces, reason):
    with pytest.raises(ValueError, match=reason):
        difference.validate_topology(VERTICES, FACES, vertices, faces)


def test_topology_accepts_identical_grid_and_rejects_invalid_faces():
    difference.validate_topology(VERTICES, FACES, VERTICES, FACES)
    with pytest.raises(ValueError, match="invalid face"):
        difference.validate_topology(VERTICES, [(0, 1, 4)], VERTICES, [(0, 1, 4)])
    with pytest.raises(ValueError, match="2D mesh"):
        difference.validate_topology(VERTICES, [], VERTICES, [])


def test_existing_output_is_unchanged(tmp_path):
    path = tmp_path / "existing.nc"
    path.write_bytes(b"do not overwrite")
    with pytest.raises(ValueError, match="already exists"):
        prepare_and_write(path, MeshLayer([[1, 2]]), MeshLayer([[3, 4]]))
    assert path.read_bytes() == b"do not overwrite"


def test_read_failure_cleans_up_partial_output(tmp_path, monkeypatch):
    left, right = MeshLayer([[1, 2]]), MeshLayer([[3, 4]])
    monkeypatch.setattr(left, "datasetValues", lambda *args: Block(valid=False))
    path = tmp_path / "failed.nc"
    with pytest.raises(ValueError, match="Could not read dataset"):
        prepare_and_write(path, left, right)
    assert list(tmp_path.iterdir()) == []


def test_legacy_provider_indexes_are_used(monkeypatch):
    left, right = MeshLayer([[5, 6]]), MeshLayer([[1, 2]])
    for layer in (left, right):
        metadata, count = layer.datasetGroupMetadata, layer.datasetCount
        provider = SimpleNamespace(
            datasetGroupCount=lambda: 1,
            datasetGroupMetadata=lambda group, method=metadata: method(difference._index(group)),
            datasetCount=lambda group, method=count: method(difference._index(group)),
            datasetMetadata=layer.datasetMetadata,
            datasetValues=layer.datasetValues,
        )
        monkeypatch.setattr(layer, "datasetGroupsIndexes", None)
        monkeypatch.setattr(layer, "dataProvider", lambda provider=provider: provider, raising=False)
    groups, skipped = difference.prepare_groups(left, right)
    assert len(groups) == 1 and not skipped


def configure_action(plugin, monkeypatch, tmp_path):
    left, right = MeshLayer([[5, 6]], name="A"), MeshLayer([[1, 2]], name="B")
    right._crs = left._crs
    plugin.iface.layerTreeView().selectedLayers.return_value = [left, right]
    monkeypatch.setattr(plugin, "_is_mesh_layer", lambda layer: isinstance(layer, MeshLayer))
    monkeypatch.setattr(plugin, "_native_mesh", lambda layer: layer)
    monkeypatch.setattr(plugin, "_mesh_vertices_faces", lambda mesh: (VERTICES, FACES))
    monkeypatch.setattr(
        plugin_module.QInputDialog, "getItem", lambda *args: ("1: A", True)
    )
    monkeypatch.setattr(
        plugin_module.QFileDialog, "getSaveFileName",
        lambda *args: (str(tmp_path / "result"), ""),
    )
    derived = MagicMock()
    derived.isValid.return_value = True
    derived.dataProvider().datasetGroupCount.return_value = 1
    constructor = MagicMock(return_value=derived)
    monkeypatch.setattr(plugin_module, "QgsMeshLayer", constructor)
    return left, right, derived, constructor


def test_action_saves_adds_layer_and_supports_reversed_order(plugin, monkeypatch, tmp_path):
    left, right, derived, constructor = configure_action(plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin_module.QInputDialog, "getItem", lambda *args: ("2: B", True))
    assert plugin.compute_mesh_difference() is derived
    assert constructor.call_args.args[1] == "B - A"
    derived.setCrs.assert_called_once_with(right.crs())
    plugin_module.QgsProject.instance().addMapLayer.assert_called_with(derived)
    with Dataset(tmp_path / "result.nc") as output:
        np.testing.assert_array_equal(output.variables["difference_0"][:], [-4, -4])


@pytest.mark.parametrize("count", [0, 1, 3])
def test_action_requires_exactly_two_selected_meshes(plugin, monkeypatch, count):
    plugin.iface.layerTreeView().selectedLayers.return_value = [object()] * count
    assert plugin.compute_mesh_difference() is None
    assert "exactly two" in plugin.iface.messageBar().pushWarning.call_args.args[1]


def test_action_rejects_nonmesh_selection(plugin, monkeypatch):
    plugin.iface.layerTreeView().selectedLayers.return_value = [object(), object()]
    monkeypatch.setattr(plugin, "_is_mesh_layer", lambda layer: False)
    assert plugin.compute_mesh_difference() is None
    plugin.iface.messageBar().pushWarning.assert_called_once()


@pytest.mark.parametrize("cancel_stage", ["order", "save"])
def test_action_cancellation_creates_nothing(plugin, monkeypatch, tmp_path, cancel_stage):
    configure_action(plugin, monkeypatch, tmp_path)
    if cancel_stage == "order":
        monkeypatch.setattr(plugin_module.QInputDialog, "getItem", lambda *args: ("", False))
    else:
        monkeypatch.setattr(plugin_module.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    assert plugin.compute_mesh_difference() is None
    assert not list(tmp_path.iterdir())
    plugin.iface.messageBar().pushWarning.assert_not_called()


def test_action_rejects_different_crs(plugin, monkeypatch, tmp_path):
    left, right, _, _ = configure_action(plugin, monkeypatch, tmp_path)
    right._crs = SimpleNamespace(isValid=lambda: True)
    assert plugin.compute_mesh_difference() is None
    assert "same valid CRS" in plugin.iface.messageBar().pushWarning.call_args.args[1]
    assert not list(tmp_path.iterdir())


def test_action_reports_saved_but_unloadable_output(plugin, monkeypatch, tmp_path):
    _, _, derived, _ = configure_action(plugin, monkeypatch, tmp_path)
    derived.isValid.return_value = False
    assert plugin.compute_mesh_difference() is None
    assert (tmp_path / "result.nc").exists()
    assert "saved" in plugin.iface.messageBar().pushWarning.call_args.args[1]
    plugin.iface.messageBar().pushSuccess.assert_not_called()


def test_action_reports_skips_after_success(plugin, monkeypatch, tmp_path):
    left, _, derived, _ = configure_action(plugin, monkeypatch, tmp_path)
    left.groups[7] = (Metadata(name="Extra"), [[1, 2]], [0])
    warning = MagicMock()
    monkeypatch.setattr(plugin_module.QMessageBox, "warning", warning)
    assert plugin.compute_mesh_difference() is derived
    assert "Extra: not present in both layers" in warning.call_args.args[2]


def test_action_rejects_topology_mismatch_before_saving(plugin, monkeypatch, tmp_path):
    left, _, _, _ = configure_action(plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(
        plugin, "_mesh_vertices_faces",
        lambda mesh: (VERTICES, FACES if mesh is left else list(reversed(FACES))),
    )
    assert plugin.compute_mesh_difference() is None
    assert "face connectivity" in plugin.iface.messageBar().pushWarning.call_args.args[1]
    assert not list(tmp_path.iterdir())
