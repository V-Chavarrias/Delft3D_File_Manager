"""Orthogonality metrics for unstructured 2D mesh faces."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _face_circumcenter(points: np.ndarray) -> np.ndarray:
    """Return the least-squares circumcenter of a polygon."""
    if len(points) < 3:
        raise ValueError("A face must contain at least three nodes")
    reference = points[0]
    matrix = 2.0 * (points[1:] - reference)
    right_hand_side = np.sum(points[1:] ** 2, axis=1) - np.sum(reference ** 2)
    center, _, rank, _ = np.linalg.lstsq(matrix, right_hand_side, rcond=None)
    if rank < 2:
        raise ValueError("Cannot compute a circumcenter for a degenerate face")
    return center


def _shared_edges(face_nodes: Sequence[Sequence[int]]) -> list[tuple[int, int, int, int]]:
    edges: dict[tuple[int, int], tuple[int, int]] = {}
    shared = []
    for face_index, face in enumerate(face_nodes):
        if len(face) < 3:
            raise ValueError("A face must contain at least three nodes")
        for edge_index, first in enumerate(face):
            second = face[(edge_index + 1) % len(face)]
            if first == second:
                raise ValueError("A face cannot contain a zero-length edge")
            key = tuple(sorted((int(first), int(second))))
            if key in edges:
                previous_face, _ = edges[key]
                shared.append((key[0], key[1], previous_face, face_index))
            else:
                edges[key] = (face_index, edge_index)
    return shared


def edge_orthogonality(
    node_x: np.ndarray,
    node_y: np.ndarray,
    face_nodes: Sequence[Sequence[int]],
) -> list[tuple[int, int, int, int, float]]:
    """Return ``(node_a, node_b, face_a, face_b, cosine)`` for each internal edge."""
    node_coordinates = np.column_stack((node_x, node_y)).astype(float, copy=False)
    if node_coordinates.ndim != 2 or node_coordinates.shape[1] != 2:
        raise ValueError("Node coordinates must be one-dimensional x and y arrays")

    faces = [tuple(int(node) for node in face) for face in face_nodes]
    node_count = len(node_coordinates)
    for face in faces:
        if any(node < 0 or node >= node_count for node in face):
            raise ValueError("Face references a node outside the coordinate arrays")

    centers = np.asarray([_face_circumcenter(node_coordinates[list(face)]) for face in faces])
    results = []
    for first_node, second_node, first_face, second_face in _shared_edges(faces):
        edge = node_coordinates[second_node] - node_coordinates[first_node]
        center_link = centers[second_face] - centers[first_face]
        denominator = np.linalg.norm(edge) * np.linalg.norm(center_link)
        if denominator <= np.finfo(float).eps:
            cosine = 1.0
        else:
            cosine = abs(float(np.dot(edge, center_link) / denominator))
        results.append((first_node, second_node, first_face, second_face, cosine))

    if not results:
        raise ValueError("At least two faces sharing an edge are required")
    return results


def orthogonality_cosines(
    node_x: np.ndarray,
    node_y: np.ndarray,
    face_nodes: Sequence[Sequence[int]],
) -> np.ndarray:
    """Return absolute edge/circumcenter-link cosines for internal edges."""
    return np.asarray([result[-1] for result in edge_orthogonality(node_x, node_y, face_nodes)])


def face_orthogonality(
    face_nodes: Sequence[Sequence[int]],
    edge_results: Sequence[tuple[int, int, int, int, float]],
) -> np.ndarray:
    """Return the worst adjacent-edge cosine for each face."""
    values = np.full(len(face_nodes), np.nan, dtype=float)
    for _, _, first_face, second_face, cosine in edge_results:
        values[first_face] = np.nanmax([values[first_face], cosine])
        values[second_face] = np.nanmax([values[second_face], cosine])
    return values


def maximum_orthogonality(
    node_x: np.ndarray,
    node_y: np.ndarray,
    face_nodes: Sequence[Sequence[int]],
) -> float:
    """Return the worst internal-edge orthogonality cosine."""
    return float(np.max(orthogonality_cosines(node_x, node_y, face_nodes)))
