import importlib
import math
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from Delft3DFileManager.mesh_edge_paths import (
    MeshPolylineDraft,
    UnreachableCornerError,
    build_edge_graph,
    normalize_face_connectivity,
)


def _euclidean(first, second):
    return math.hypot(second[0] - first[0], second[1] - first[1])


def test_faces_create_only_boundary_edges_and_close_rings():
    graph = build_edge_graph(
        [(0, 0), (2, 0), (2, 2), (0, 2)],
        [(0, 1, 2, 3)],
        _euclidean,
    )

    assert graph.shortest_path(0, 2) in ([0, 1, 2], [0, 3, 2])
    assert graph.shortest_path(3, 0) == [3, 0]
    assert (0, 2) not in graph.neighbors


def test_shared_edges_are_deduplicated():
    calls = []

    def measure(first, second):
        calls.append((first, second))
        return _euclidean(first, second)

    graph = build_edge_graph(
        [(0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (2, 1)],
        [(0, 1, 2, 3), (1, 4, 5, 2)],
        measure,
    )

    assert len(calls) == 7
    assert graph.neighbors[1].count((2, 1.0)) == 1


def test_connectivity_normalizes_start_index_fill_values_and_masks():
    masked = np.ma.array(
        [[1, 2, 3, 999], [3, 4, 5, 999]],
        mask=[[False, False, False, True], [False, False, False, False]],
    )

    assert normalize_face_connectivity(
        masked, start_index=1, fill_value=999
    ) == [(0, 1, 2), (2, 3, 4)]
    assert normalize_face_connectivity(
        [[0, 1, 2, -1]], fill_value=-1
    ) == [(0, 1, 2)]


@pytest.mark.parametrize(
    "faces, message",
    [
        ([(-1, 1, 2)], "outside"),
        ([(0, 1, 2, 2)], "distinct"),
    ],
)
def test_invalid_face_references_and_repeated_nodes_are_rejected(faces, message):
    with pytest.raises(ValueError, match=message):
        build_edge_graph([(0, 0), (1, 0), (0, 1)], faces, _euclidean)


def test_invalid_connectivity_and_nonfinite_coordinates_are_rejected():
    with pytest.raises(ValueError, match="fewer than three"):
        normalize_face_connectivity([[1, 2, 999]], start_index=1, fill_value=999)

    with pytest.raises(ValueError, match="finite"):
        build_edge_graph([(0, 0), (1, 0), (math.nan, 1)], [(0, 1, 2)], _euclidean)


def test_weighted_shortest_path_keeps_every_intermediate_corner():
    graph = build_edge_graph(
        [(0, 0), (1, 0), (2, 0), (0, 1), (2, 1)],
        [(0, 1, 2, 4, 3)],
        lambda first, second: {
            frozenset(((0, 0), (1, 0))): 1,
            frozenset(((1, 0), (2, 0))): 1,
            frozenset(((2, 0), (2, 1))): 1,
            frozenset(((2, 1), (0, 1))): 8,
            frozenset(((0, 1), (0, 0))): 1,
        }[frozenset((first, second))],
    )

    assert graph.shortest_path(0, 2) == [0, 1, 2]


def test_equal_cost_route_is_deterministic():
    graph = build_edge_graph(
        [(0, 0), (1, 1), (1, -1), (2, 0)],
        [(0, 1, 3, 2)],
        lambda first, second: 1.0,
    )

    assert graph.shortest_path(0, 3) == [0, 1, 3]
    assert graph.shortest_path(0, 3) == [0, 1, 3]


def test_disconnected_components_and_coincident_node_identity():
    graph = build_edge_graph(
        [(0, 0), (1, 0), (0, 0), (1, 1), (-1, 1), (2, 2)],
        [(0, 1, 4), (2, 3, 5)],
        _euclidean,
    )

    assert graph.shortest_path(0, 1) == [0, 1]
    with pytest.raises(UnreachableCornerError):
        graph.shortest_path(0, 2)


def test_draft_keeps_loops_and_undoes_whole_clicked_segments():
    graph = build_edge_graph(
        [(0, 0), (1, 0), (1, 1), (0, 1)],
        [(0, 1, 2, 3)],
        _euclidean,
    )
    draft = MeshPolylineDraft(graph)

    assert draft.append_corner(0)
    assert not draft.append_corner(0)
    assert draft.append_corner(2)
    assert draft.nodes == [0, 1, 2]
    assert draft.append_corner(0)
    assert draft.nodes == [0, 1, 2, 1, 0]
    assert draft.can_finish()
    draft.undo()
    assert draft.nodes == [0, 1, 2]
    draft.undo()
    assert draft.nodes == [0]
    draft.undo()
    assert draft.nodes == []
    assert not draft.can_finish()


def test_plugin_requires_an_active_mesh_before_capture(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_is_mesh_layer", lambda layer: False)

    assert plugin.create_polyline_from_mesh() is None
    plugin.iface.messageBar().pushWarning.assert_called_once()


def test_plugin_rejects_invalid_mesh_crs_before_capture(plugin, monkeypatch):
    layer = MagicMock()
    layer.isValid.return_value = True
    layer.crs.return_value.isValid.return_value = False
    plugin.iface.activeLayer.return_value = layer
    monkeypatch.setattr(plugin, "_is_mesh_layer", lambda active: active is layer)

    assert plugin.create_polyline_from_mesh() is None
    warning = plugin.iface.messageBar().pushWarning.call_args.args[1]
    assert "invalid coordinate reference system" in warning


def test_plugin_starts_capture_without_distance_area_length_units(plugin, monkeypatch):
    plugin_module = importlib.import_module("Delft3DFileManager.Delft3DFileManager")
    layer = MagicMock()
    layer.isValid.return_value = True
    layer.crs.return_value.isValid.return_value = True
    layer.crs.return_value.ellipsoidAcronym.return_value = "WGS84"
    layer.id.return_value = "mesh-layer"
    plugin.iface.activeLayer.return_value = layer
    monkeypatch.setattr(plugin, "_is_mesh_layer", lambda active: active is layer)
    monkeypatch.setattr(plugin, "_native_mesh", lambda active: object())
    monkeypatch.setattr(
        plugin,
        "_mesh_vertices_faces",
        lambda mesh: ([(0, 0), (1, 0), (0, 1)], [(0, 1, 2)]),
    )

    class DistanceArea:
        def setSourceCrs(self, crs, transform_context):
            self.source_crs = crs

        def setEllipsoid(self, ellipsoid):
            self.ellipsoid = ellipsoid

        def willUseEllipsoid(self):
            return True

        def measureLine(self, first, second):
            return 1.0

    distance_area = DistanceArea()
    monkeypatch.setattr(plugin_module, "QgsDistanceArea", lambda: distance_area)

    class CaptureTool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setitem(
        sys.modules,
        "Delft3DFileManager.mesh_polyline_capture",
        SimpleNamespace(MeshPolylineCaptureTool=CaptureTool),
    )
    plugin._mesh_polyline_map_tool = None

    capture = plugin.create_polyline_from_mesh()

    assert isinstance(capture, CaptureTool)
    assert distance_area.ellipsoid == "WGS84"
    plugin.iface.messageBar().pushWarning.assert_not_called()
