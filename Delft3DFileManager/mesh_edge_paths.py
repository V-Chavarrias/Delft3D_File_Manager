"""Mesh-edge routing and click-segment history, independent of QGIS."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import heapq
import math
import operator
from types import MappingProxyType
from typing import Optional


class UnreachableCornerError(ValueError):
    """The selected corners belong to disconnected mesh components."""


@dataclass(frozen=True)
class MeshEdgeGraph:
    coordinates: tuple[tuple[float, float], ...]
    neighbors: Mapping[int, tuple[tuple[int, float], ...]]

    def shortest_path(self, start: int, end: int) -> list[int]:
        if start not in self.neighbors or end not in self.neighbors:
            raise ValueError("Selected corner is not part of a mesh face")
        if start == end:
            return [start]
        distances = {start: 0.0}
        previous: dict[int, int] = {}
        queue = [(0.0, start)]
        settled = set()
        while queue:
            distance, node = heapq.heappop(queue)
            if node in settled:
                continue
            settled.add(node)
            if node == end:
                path = [end]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                return list(reversed(path))
            for neighbor, length in self.neighbors[node]:
                candidate = distance + length
                if neighbor not in settled and candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(queue, (candidate, neighbor))
        raise UnreachableCornerError(
            "The selected corner cannot be reached along this mesh's cell edges."
        )


def normalize_face_connectivity(
    face_nodes: Iterable[Sequence[int]],
    start_index: int = 0,
    fill_value: Optional[int] = None,
) -> list[tuple[int, ...]]:
    """Return zero-based faces, omitting masked and padded connectivity values."""
    if isinstance(start_index, bool):
        raise ValueError("Connectivity start_index must be an integer")
    try:
        start_index = operator.index(start_index)
    except TypeError as exc:
        raise ValueError("Connectivity start_index must be an integer") from exc
    try:
        fill_value = operator.index(fill_value) if fill_value is not None else None
    except TypeError as exc:
        raise ValueError("Connectivity fill_value must be an integer") from exc

    mask = getattr(face_nodes, "mask", None)
    normalized = []
    for face_index, raw_face in enumerate(face_nodes):
        row_mask = mask[face_index] if mask is not None and getattr(mask, "ndim", 0) > 1 else None
        face = []
        for column, raw_node in enumerate(raw_face):
            if row_mask is not None and bool(row_mask[column]):
                continue
            try:
                node = operator.index(raw_node)
            except TypeError:
                try:
                    numeric = float(raw_node)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(
                        f"Face {face_index} contains a non-integer corner index"
                    ) from exc
                if not math.isfinite(numeric) or not numeric.is_integer():
                    raise ValueError(
                        f"Face {face_index} contains a non-integer corner index"
                    )
                node = int(numeric)
            if fill_value is not None and node == fill_value:
                continue
            face.append(node - start_index)
        if not face:
            continue
        if len(face) < 3:
            raise ValueError(
                f"Face {face_index} has fewer than three valid corner indices"
            )
        normalized.append(tuple(face))
    return normalized


def build_edge_graph(
    coordinates: Iterable[Sequence[float]],
    faces: Iterable[Sequence[int]],
    edge_length: Callable[[tuple[float, float], tuple[float, float]], float],
) -> MeshEdgeGraph:
    """Build from normalized, zero-based native mesh faces, never face diagonals."""
    nodes = tuple((float(point[0]), float(point[1])) for point in coordinates)
    if not nodes or any(not all(math.isfinite(value) for value in point) for point in nodes):
        raise ValueError("Mesh corner coordinates must be nonempty and finite")
    edges: set[tuple[int, int]] = set()
    for raw_face in faces:
        face = tuple(operator.index(node) for node in raw_face)
        if len(face) > 1 and face[0] == face[-1]:
            face = face[:-1]
        if len(face) < 3 or len(set(face)) != len(face):
            raise ValueError("Mesh faces must contain at least three distinct corners")
        if any(node < 0 or node >= len(nodes) for node in face):
            raise ValueError("Mesh face references a corner outside the coordinate array")
        for first, second in zip(face, face[1:] + face[:1]):
            edges.add((min(first, second), max(first, second)))
    if not edges:
        raise ValueError("The active mesh has no 2D cell edges")

    adjacency: dict[int, list[tuple[int, float]]] = {}
    for first, second in sorted(edges):
        length = float(edge_length(nodes[first], nodes[second]))
        if not math.isfinite(length) or length < 0:
            raise ValueError("Mesh edge lengths must be finite and nonnegative")
        adjacency.setdefault(first, []).append((second, length))
        adjacency.setdefault(second, []).append((first, length))
    return MeshEdgeGraph(
        nodes,
        MappingProxyType({
            node: tuple(sorted(neighbors)) for node, neighbors in adjacency.items()
        }),
    )


class MeshPolylineDraft:
    def __init__(self, graph: MeshEdgeGraph):
        self.graph = graph
        self.nodes: list[int] = []
        self._undo_lengths: list[int] = []

    def append_corner(self, node: int) -> bool:
        if node not in self.graph.neighbors:
            raise ValueError("Selected corner is not part of a mesh face")
        if self.nodes and node == self.nodes[-1]:
            return False
        segment = self.graph.shortest_path(self.nodes[-1], node)[1:] if self.nodes else [node]
        self._undo_lengths.append(len(self.nodes))
        self.nodes.extend(segment)
        return True

    def undo(self) -> None:
        if self._undo_lengths:
            del self.nodes[self._undo_lengths.pop():]

    def can_finish(self) -> bool:
        return len(set(self.nodes)) >= 2
