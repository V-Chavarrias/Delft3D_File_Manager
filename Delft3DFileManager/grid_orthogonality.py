"""Orthogonality metrics for unstructured 2D mesh faces."""

from __future__ import annotations

from collections.abc import Sequence
from collections import defaultdict, deque
import time
from typing import Callable

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


def mesh_properties(
    node_x: np.ndarray,
    node_y: np.ndarray,
    face_nodes: Sequence[Sequence[int]],
    face_centers: np.ndarray | None = None,
    compute_connectivity: bool = True,
    compute_face_quality: bool = True,
    compute_dual_links: bool = True,
    progress_callback: Callable[[int, str], None] | None = None,
    timing_callback: Callable[[str, float], None] | None = None,
) -> dict[str, object]:
    """Return connectivity, centers, dual links, and orthogonality properties."""
    timings = {}

    def timed(stage, started):
        elapsed = time.perf_counter() - started
        timings[stage] = elapsed
        if timing_callback is not None:
            timing_callback(stage, elapsed)

    def report(percent: int, stage: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, stage)

    report(0, "Preparing mesh topology")
    stage_started = time.perf_counter()
    node_coordinates = np.column_stack((node_x, node_y)).astype(float, copy=False)
    faces = [tuple(int(node) for node in face) for face in face_nodes]
    node_count = len(node_coordinates)
    for face in faces:
        if len(face) < 3:
            raise ValueError("A face must contain at least three nodes")
        if any(node < 0 or node >= node_count for node in face):
            raise ValueError("Face references a node outside the coordinate arrays")

    if face_centers is not None:
        if isinstance(face_centers, np.ma.MaskedArray):
            raise ValueError("Supplied face centers cannot be masked")
        centers = np.asarray(face_centers, dtype=float)
        if centers.shape != (len(faces), 2):
            raise ValueError("Supplied face centers must have shape (face_count, 2)")
        if not np.all(np.isfinite(centers)):
            raise ValueError("Supplied face centers must contain finite values")
        report(30, "Using supplied face centers")
    else:
        centers = np.empty((len(faces), 2), dtype=float)
        for face_index, face in enumerate(faces):
            centers[face_index] = _face_circumcenter(node_coordinates[list(face)])
            if face_index % 4096 == 0:
                report(1 + int(28 * face_index / max(len(faces), 1)), "Computing face centers")
        report(30, "Computed face centers")
    timed("face_centers", stage_started)
    report(30, "Calculated face centers")
    stage_started = time.perf_counter()
    edge_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
    for face_id, face in enumerate(faces):
        for index, first_node in enumerate(face):
            second_node = face[(index + 1) % len(face)]
            if first_node == second_node:
                raise ValueError("A face cannot contain a zero-length edge")
            edge_faces[tuple(sorted((first_node, second_node)))].append(face_id)
        if face_id % 4096 == 0:
            report(31 + int(18 * face_id / max(len(faces), 1)), "Building edge connectivity")
    timed("edge_connectivity", stage_started)
    report(50, "Built edge connectivity")

    adjacency: list[set[int]] = [set() for _ in faces] if compute_connectivity else []
    boundary_flags = np.zeros(len(faces), dtype=bool)
    nonmanifold_flags = np.zeros(len(faces), dtype=bool)
    face_quality = np.full(len(faces), np.nan, dtype=float)
    edge_properties = []
    dual_links = []
    orthogonality_by_edge = {}
    stage_started = time.perf_counter()
    for (first_node, second_node), incident_faces in edge_faces.items():
        incident_count = len(incident_faces)
        if incident_count == 1:
            boundary_flags[incident_faces[0]] = True
        elif incident_count > 2:
            nonmanifold_flags[incident_faces] = True
        if incident_count > 1:
            first_face, second_face = incident_faces[:2]
            edge = node_coordinates[second_node] - node_coordinates[first_node]
            center_link = centers[second_face] - centers[first_face]
            denominator = np.linalg.norm(edge) * np.linalg.norm(center_link)
            if denominator <= np.finfo(float).eps:
                cosine = 1.0
            else:
                cosine = abs(
                    float(np.dot(edge, center_link) / denominator)
                )
            orthogonality_by_edge[(first_node, second_node)] = cosine
            if compute_face_quality:
                for face_id in incident_faces:
                    if np.isnan(face_quality[face_id]) or cosine > face_quality[face_id]:
                        face_quality[face_id] = cosine
            if compute_connectivity or compute_dual_links:
                for first_face in incident_faces:
                    for second_face in incident_faces:
                        if first_face < second_face:
                            if compute_connectivity:
                                adjacency[first_face].add(second_face)
                                adjacency[second_face].add(first_face)
                            if compute_dual_links:
                                dual_links.append((first_face, second_face, first_node, second_node))
        edge_properties.append({
            "node_a": first_node,
            "node_b": second_node,
            "face_ids": tuple(incident_faces),
            "incident_count": incident_count,
            "boundary": incident_count == 1,
            "nonmanifold": incident_count > 2,
            "orthogonality": orthogonality_by_edge.get((first_node, second_node)),
        })
    timed("edge_properties", stage_started)
    report(70, "Calculated edge properties")

    component_ids = [-1] * len(faces)
    if compute_connectivity:
        component_id = 0
        stage_started = time.perf_counter()
        for start_face in range(len(faces)):
            if component_ids[start_face] >= 0:
                continue
            queue = deque([start_face])
            component_ids[start_face] = component_id
            while queue:
                face_id = queue.popleft()
                for neighbor_id in adjacency[face_id]:
                    if component_ids[neighbor_id] < 0:
                        component_ids[neighbor_id] = component_id
                        queue.append(neighbor_id)
            component_id += 1
        timed("face_components", stage_started)
    report(85, "Calculated face connectivity")

    neighbor_counts = np.asarray([len(neighbors) for neighbors in adjacency], dtype=int)
    stage_started = time.perf_counter()
    timed("face_quality", stage_started)
    report(100, "Finished mesh properties")

    return {
        "faces": faces,
        "centers": centers,
        "edges": edge_properties,
        "dual_links": dual_links,
        "neighbor_counts": neighbor_counts,
        "boundary_flags": boundary_flags,
        "nonmanifold_flags": nonmanifold_flags,
        "component_ids": np.asarray(component_ids, dtype=int),
        "face_orthogonality": face_quality,
        "timings": timings,
    }


def maximum_orthogonality(
    node_x: np.ndarray,
    node_y: np.ndarray,
    face_nodes: Sequence[Sequence[int]],
) -> float:
    """Return the worst internal-edge orthogonality cosine."""
    return float(np.max(orthogonality_cosines(node_x, node_y, face_nodes)))
