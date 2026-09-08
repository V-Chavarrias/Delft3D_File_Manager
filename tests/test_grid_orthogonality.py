import numpy as np
import pytest

from Delft3DFileManager.Delft3DFileManager import Delft3DFileManager
from Delft3DFileManager.grid_orthogonality import (
    edge_orthogonality,
    face_orthogonality,
    maximum_orthogonality,
    orthogonality_cosines,
)


class _NativeMesh:
    pass


class _NativeMeshLayer:
    def nativeMesh(self):
        return _NativeMesh()


def test_qgis_native_mesh_accessor_is_supported():
    mesh = Delft3DFileManager._native_mesh(_NativeMeshLayer())

    assert isinstance(mesh, _NativeMesh)


class _ProviderMesh:
    def __init__(self):
        self.vertices_data = [(0.0, 0.0), (1.0, 0.0)]
        self.faces_data = [(0, 1, 0)]

    def vertexCount(self):
        return len(self.vertices_data)

    def vertex(self, index):
        return self.vertices_data[index]

    def faceCount(self):
        return len(self.faces_data)

    def face(self, index):
        return self.faces_data[index]


def test_indexed_mesh_topology_is_supported():
    vertices, faces = Delft3DFileManager._mesh_vertices_faces(_ProviderMesh())

    assert vertices == [(0.0, 0.0), (1.0, 0.0)]
    assert faces == [(0, 1, 0)]


def _two_cell_mesh():
    return (
        np.array([0.0, 1.0, 1.0, 0.0, 2.0]),
        np.array([0.0, 0.0, 1.0, 1.0, 0.0]),
        [(0, 1, 2, 3), (1, 4, 2)],
    )


def test_orthogonal_shared_edge_has_near_zero_cosine():
    node_x, node_y, faces = _two_cell_mesh()

    results = edge_orthogonality(node_x, node_y, faces)

    assert len(results) == 1
    assert results[0][:4] == (1, 2, 0, 1)
    assert results[0][-1] == pytest.approx(0.0, abs=1e-12)
    assert maximum_orthogonality(node_x, node_y, faces) == pytest.approx(0.0, abs=1e-12)


def test_face_values_use_worst_adjacent_internal_edge():
    node_x, node_y, faces = _two_cell_mesh()
    edge_results = edge_orthogonality(node_x, node_y, faces)

    assert face_orthogonality(faces, edge_results) == pytest.approx([0.0, 0.0], abs=1e-12)


def test_single_face_has_no_orthogonality_metric():
    with pytest.raises(ValueError, match="two faces"):
        orthogonality_cosines(
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
            [(0, 1, 2)],
        )


def test_degenerate_face_is_rejected():
    with pytest.raises(ValueError, match="degenerate"):
        orthogonality_cosines(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([0.0, 0.0, 0.0, 1.0]),
            [(0, 1, 2), (1, 3, 2)],
        )


def test_invalid_node_reference_is_rejected():
    with pytest.raises(ValueError, match="outside"):
        edge_orthogonality(
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
            [(0, 1, 2), (1, 3, 2)],
        )


def test_repeated_node_in_face_is_rejected():
    with pytest.raises(ValueError, match="zero-length"):
        edge_orthogonality(
            np.array([0.0, 1.0, 0.0, 1.0]),
            np.array([0.0, 0.0, 1.0, 1.0]),
            [(0, 1, 2), (1, 2, 2, 3)],
        )


def test_zero_length_face_center_link_uses_worst_case_sentinel():
    node_x = np.array([0.0, 1.0, 1.0, 0.0])
    node_y = np.array([0.0, 0.0, 1.0, 1.0])

    values = orthogonality_cosines(node_x, node_y, [(0, 1, 2), (0, 1, 2)])

    assert values.tolist() == [1.0, 1.0, 1.0]
