import math
import pathlib

import numpy as np
import pytest

from Delft3DFileManager.mesh_profile_sampler import (
    cumulative_chainage,
    dataset_index_for_displayed_scalar,
    densify_polyline,
    mesh_edge_crossings,
    nearest_mesh_sample_candidates,
    sample_partitioned_mesh,
    sample_partitioned_mesh_timeseries,
)


DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
DELTA_PARTITIONS = [DATA_DIR / f"delta_{index:04d}_map.nc" for index in range(4)]


def _partition_topology(path):
    nc = pytest.importorskip("netCDF4")
    with nc.Dataset(str(path), "r") as dataset:
        variables = {name.lower(): name for name in dataset.variables}
        node_x = np.asarray(dataset.variables[variables["mesh2d_node_x"]][:], dtype=float)
        node_y = np.asarray(dataset.variables[variables["mesh2d_node_y"]][:], dtype=float)
        face_variable = dataset.variables[variables["mesh2d_face_nodes"]]
        face_nodes = face_variable[:]
        if isinstance(face_nodes, np.ma.MaskedArray):
            face_nodes = face_nodes.filled(-1)
        start_index = int(getattr(face_variable, "start_index", 0))
        return node_x, node_y, np.asarray(face_nodes, dtype=int) - start_index


class _DatasetValue:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Layer:
    def __init__(self, values, group=2, dataset=4):
        self.values = values
        self.group = group
        self.dataset = dataset

    def activeScalarDatasetGroup(self):
        return self.group

    def activeScalarDatasetIndex(self):
        return self.dataset

    def datasetValue(self, dataset_index, point):
        assert dataset_index == (self.group, self.dataset)
        return _DatasetValue(self.values.get(tuple(point), math.nan))


class _TemporalLayer:
    def __init__(self, values):
        self.values = values

    def datasetValue(self, dataset_index, point):
        return _DatasetValue(
            self.values.get((tuple(dataset_index), tuple(point)), math.nan)
        )


class _Grid:
    def __init__(self, node_x, node_y, faces):
        self.node_x = np.asarray(node_x, dtype=float)
        self.node_y = np.asarray(node_y, dtype=float)
        self.faces = np.asarray(faces, dtype=int)


def test_cumulative_chainage_and_densification():
    points = densify_polyline([(0, 0), (10, 0)], maximum_spacing=3)

    assert len(points) == 5
    assert cumulative_chainage(points) == [0.0, 2.5, 5.0, 7.5, 10.0]


def test_sample_partitioned_mesh_uses_first_finite_partition_value():
    first = _Layer({(0.0, 0.0): 1.0, (1.0, 0.0): math.nan})
    second = _Layer({(1.0, 0.0): 2.0, (2.0, 0.0): 3.0})

    profile = sample_partitioned_mesh(
        [first, second],
        [(0, 0), (1, 0), (2, 0)],
        (2, 4),
    )

    assert profile == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]


def test_sample_partitioned_mesh_preserves_missing_data_gaps():
    profile = sample_partitioned_mesh(
        [_Layer({(0.0, 0.0): math.nan})],
        [(0, 0), (1, 0)],
        (2, 4),
    )

    assert profile == [(0.0, None), (1.0, None)]


def test_sample_partitioned_mesh_timeseries_uses_finite_partition_values():
    point = (0.0, 0.0)
    first = _TemporalLayer({
        ((2, 0), point): 1.0,
        ((2, 1), point): math.nan,
    })
    second = _TemporalLayer({((2, 1), point): 2.0})

    values = sample_partitioned_mesh_timeseries(
        [first, second],
        point,
        [(2, 0), (2, 1), (2, 2)],
    )

    assert values == [1.0, 2.0, None]


def test_nearest_mesh_sample_candidates_respects_node_and_face_location():
    grid = _Grid(
        [0, 1, 1, 0],
        [0, 0, 1, 1],
        [[0, 1, 2, 3]],
    )

    assert nearest_mesh_sample_candidates([grid], (0.8, 0.2), "node") == [
        (0, 1, (1.0, 0.0))
    ]
    assert nearest_mesh_sample_candidates([grid], (0.6, 0.4), "face") == [
        (0, 0, (0.5, 0.5))
    ]


def test_nearest_mesh_sample_candidates_supports_restart_points():
    grid = _Grid([0, 1, 2], [10, 10, 10], [])

    assert nearest_mesh_sample_candidates([grid], (1.7, 10.1), "point") == [
        (0, 2, (2.0, 10.0))
    ]


def test_nearest_mesh_sample_candidates_keeps_duplicate_partition_nodes():
    grid = _Grid([0, 1, 1, 0], [0, 0, 1, 1], [[0, 1, 2, 3]])

    candidates = nearest_mesh_sample_candidates(
        [grid, grid],
        (0.0, 0.0),
        "node",
    )

    assert candidates == [(0, 0, (0.0, 0.0)), (1, 0, (0.0, 0.0))]


def test_sample_partitioned_mesh_finds_values_between_outside_endpoints():
    layer = _Layer({(0.0, 0.0): 7.0})

    profile = sample_partitioned_mesh(
        [layer],
        [(-1, 0), (1, 0)],
        (2, 4),
        maximum_spacing=1.0,
    )

    assert any(value == 7.0 for _, value in profile)


def test_mesh_edge_crossings_returns_exact_intersections_in_chainage_order():
    crossings = mesh_edge_crossings(
        [0, 10, 10, 0],
        [0, 0, 10, 10],
        [[0, 1, 2, 3]],
        [(-5, 5), (15, 5)],
    )

    assert crossings == [(5.0, (0.0, 5.0)), (15.0, (10.0, 5.0))]


def test_mesh_edge_crossings_keeps_points_inside_one_face():
    crossings = mesh_edge_crossings(
        [0, 10, 10, 0],
        [0, 0, 10, 10],
        [[0, 1, 2, 3]],
        [(2, 5), (8, 5)],
    )

    assert crossings == [(0.0, (2.0, 5.0)), (6.0, (8.0, 5.0))]


def test_mesh_edge_crossings_deduplicates_shared_face_edges():
    crossings = mesh_edge_crossings(
        [0, 10, 10, 0, 20, 20],
        [0, 0, 10, 10, 0, 10],
        [[0, 1, 2, 3], [1, 4, 5, 2]],
        [(-5, 5), (25, 5)],
    )

    assert crossings == [(5.0, (0.0, 5.0)), (15.0, (10.0, 5.0)), (25.0, (20.0, 5.0))]


def test_delta_line_through_each_partition_individually_finds_edges():
    topologies = [_partition_topology(path) for path in DELTA_PARTITIONS]
    line = [(-0.1, 0.5), (1.1, 0.5)]

    counts = [
        len(mesh_edge_crossings(node_x, node_y, face_nodes, line))
        for node_x, node_y, face_nodes in topologies
    ]

    assert counts == [2, 2, 2, 2]


def test_delta_line_through_all_partitions_finds_edges_in_all_partitions():
    topologies = [_partition_topology(path) for path in DELTA_PARTITIONS]
    line = [(-0.1, 0.5), (1.1, 0.5)]

    partition_crossings = [
        mesh_edge_crossings(node_x, node_y, face_nodes, line)
        for node_x, node_y, face_nodes in topologies
    ]

    assert all(len(crossings) == 2 for crossings in partition_crossings)
    assert sum(len(crossings) for crossings in partition_crossings) == 8


def test_dataset_index_for_displayed_scalar_uses_layer_state():
    assert dataset_index_for_displayed_scalar(_Layer({})) == (2, 4)


def test_dataset_index_for_displayed_scalar_rejects_no_active_group():
    assert dataset_index_for_displayed_scalar(_Layer({}, group=-1)) is None


def test_dataset_index_for_displayed_scalar_accepts_renderer_group():
    class _Renderer:
        def activeScalarDatasetGroup(self):
            return 3

    class _RendererLayer(_Layer):
        def activeScalarDatasetGroup(self):
            raise AttributeError

        def rendererSettings(self):
            return _Renderer()

    layer = _RendererLayer({}, group=-1, dataset=1)
    assert dataset_index_for_displayed_scalar(layer) == (3, 1)


def test_mesh_profile_uses_temporal_dataset_before_static_dataset():
    from Delft3DFileManager.Delft3DFileManager import Delft3DFileManager

    class _Index:
        def __init__(self, value):
            self.value = value

        def isValid(self):
            return True

    class _Renderer:
        def activeScalarDatasetGroup(self):
            return 2

    class _Temporal:
        def referenceTemporalRange(self):
            return "reference range"

    class _Canvas:
        def temporalRange(self):
            return "displayed range"

    class _Iface:
        def mapCanvas(self):
            return _Canvas()

    class _Layer:
        def rendererSettings(self):
            return _Renderer()

        def temporalProperties(self):
            return _Temporal()

        def activeScalarDatasetAtTime(self, time_range, group_index):
            assert time_range == "displayed range"
            assert group_index == 2
            return _Index(8)

        def staticScalarDatasetIndex(self, group_index):
            raise AssertionError("static dataset must not replace the temporal dataset")

    plugin = Delft3DFileManager.__new__(Delft3DFileManager)
    plugin.iface = _Iface()
    result = plugin._mesh_profile_dataset_index(_Layer())

    assert result.value == 8