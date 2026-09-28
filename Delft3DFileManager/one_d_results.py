"""Data and topology helpers for visualizing 1D Delft3D results."""

from dataclasses import dataclass
import heapq
import math
import re

import numpy as np


@dataclass(frozen=True)
class ResultVariable:
    name: str
    location: str
    dimensions: tuple
    units: str = ""
    long_name: str = ""

    @property
    def label(self):
        description = self.long_name or self.name
        if self.units:
            return f"{description} [{self.units}]"
        return description


def _read_numeric(value, fill_value=np.nan):
    if isinstance(value, np.ma.MaskedArray):
        value = value.filled(fill_value)
    return np.asarray(value)


def parse_time_indices(expression, time_count):
    """Parse one-based inclusive indices such as ``1:10,20:25``."""
    if time_count < 0:
        raise ValueError("time_count must be non-negative")
    text = str(expression or "").strip()
    if not text:
        raise ValueError("Enter one or more time indices")

    selected = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        match = re.fullmatch(r"(\d+)\s*(?::\s*(\d+))?", token)
        if match is None:
            raise ValueError(f"Invalid time index expression: {token}")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < 1 or start > time_count or end > time_count:
            raise ValueError(f"Time index out of range: {token}")
        step = 1 if end >= start else -1
        selected.extend(range(start - 1, end - 1 + step, step))

    if not selected:
        raise ValueError("Enter one or more time indices")
    return list(dict.fromkeys(selected))


def discover_result_variables(dataset, time_dimension="time"):
    """Return numeric variables located at mesh1d nodes or edges."""
    node_dimension = _find_dimension(dataset, "mesh1d_nNodes")
    edge_dimension = _find_dimension(dataset, "mesh1d_nEdges")
    variables = []
    for name, variable in dataset.variables.items():
        dimensions = tuple(getattr(variable, "dimensions", ()))
        if time_dimension not in dimensions or len(dimensions) != 2:
            continue
        location = None
        if node_dimension in dimensions:
            location = "node"
        elif edge_dimension in dimensions:
            location = "edge"
        if location is None:
            continue
        if not np.issubdtype(np.asarray(variable[:]).dtype, np.number):
            continue
        variables.append(
            ResultVariable(
                name=name,
                location=location,
                dimensions=dimensions,
                units=str(getattr(variable, "units", "") or ""),
                long_name=str(getattr(variable, "long_name", "") or ""),
            )
        )
    location_order = {"node": 0, "edge": 1}
    return sorted(variables, key=lambda item: (location_order[item.location], item.name.lower()))


def _find_dimension(dataset, suffix):
    for name in dataset.dimensions:
        if str(name).lower() == suffix.lower():
            return name
    return None


def read_mesh1d_topology(dataset):
    """Read normalized mesh1d coordinates and zero-based edge connectivity."""
    node_x_name = _find_variable(dataset, "mesh1d_node_x")
    node_y_name = _find_variable(dataset, "mesh1d_node_y")
    edge_name = _find_variable(dataset, "mesh1d_edge_nodes")
    if not node_x_name or not node_y_name or not edge_name:
        raise ValueError("The NetCDF file does not contain complete mesh1d topology")

    node_x = _read_numeric(dataset.variables[node_x_name][:], np.nan).astype(float)
    node_y = _read_numeric(dataset.variables[node_y_name][:], np.nan).astype(float)
    edge_variable = dataset.variables[edge_name]
    edges = _read_numeric(edge_variable[:], -1).astype(int)
    edges -= int(getattr(edge_variable, "start_index", 0))
    if edges.ndim != 2 or edges.shape[1] != 2:
        raise ValueError("mesh1d_edge_nodes must contain pairs of node indices")
    if len(node_x) != len(node_y):
        raise ValueError("mesh1d node coordinate arrays have different lengths")
    if np.any((edges < 0) | (edges >= len(node_x))):
        raise ValueError("mesh1d edge connectivity contains invalid node indices")
    return {"node_x": node_x, "node_y": node_y, "edges": edges}


def build_mesh1d_graph(topology):
    """Build an undirected weighted adjacency graph from mesh1d topology."""
    node_x = topology["node_x"]
    node_y = topology["node_y"]
    edges = topology["edges"]
    graph = [[] for _ in range(len(node_x))]
    for edge_index, (start, end) in enumerate(edges):
        distance = math.hypot(node_x[end] - node_x[start], node_y[end] - node_y[start])
        graph[start].append((end, distance, edge_index))
        graph[end].append((start, distance, edge_index))
    return graph


def shortest_mesh1d_path(topology, start_node, end_node):
    """Return node indices, edge indices, and cumulative distance for a shortest path."""
    graph = build_mesh1d_graph(topology)
    if not 0 <= start_node < len(graph) or not 0 <= end_node < len(graph):
        raise ValueError("Selected node is outside the mesh1d topology")
    distances = {start_node: 0.0}
    previous = {}
    queue = [(0.0, start_node)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node == end_node:
            break
        for neighbor, weight, edge_index in graph[node]:
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = (node, edge_index)
                heapq.heappush(queue, (candidate, neighbor))
    if end_node not in distances:
        raise ValueError("The selected mesh1d nodes are disconnected")

    nodes = [end_node]
    edge_indices = []
    current = end_node
    while current != start_node:
        prior, edge_index = previous[current]
        nodes.append(prior)
        edge_indices.append(edge_index)
        current = prior
    nodes.reverse()
    edge_indices.reverse()
    cumulative = [0.0]
    for edge_index in edge_indices:
        start, end = topology["edges"][edge_index]
        length = math.hypot(
            topology["node_x"][end] - topology["node_x"][start],
            topology["node_y"][end] - topology["node_y"][start],
        )
        cumulative.append(cumulative[-1] + length)
    return nodes, edge_indices, cumulative


def nearest_node(topology, x, y):
    distances = (topology["node_x"] - x) ** 2 + (topology["node_y"] - y) ** 2
    return int(np.nanargmin(distances))


def nearest_edge(topology, x, y):
    """Return the nearest edge index and projected distance along that edge."""
    best = None
    for edge_index, (start, end) in enumerate(topology["edges"]):
        ax, ay = topology["node_x"][start], topology["node_y"][start]
        bx, by = topology["node_x"][end], topology["node_y"][end]
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        fraction = 0.0 if length_squared == 0 else ((x - ax) * dx + (y - ay) * dy) / length_squared
        fraction = min(1.0, max(0.0, fraction))
        distance_squared = (x - (ax + fraction * dx)) ** 2 + (y - (ay + fraction * dy)) ** 2
        candidate = (distance_squared, edge_index, math.sqrt(length_squared) * fraction)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise ValueError("The mesh1d topology contains no edges")
    return best[1], best[2]


def read_result_values(dataset, variable, time_indices, spatial_indices):
    """Read values as a time-by-space array regardless of NetCDF dimension order."""
    netcdf_variable = dataset.variables[variable.name if hasattr(variable, "name") else variable]
    dimensions = tuple(netcdf_variable.dimensions)
    time_dimension = _find_dimension(dataset, "time")
    time_axis = dimensions.index(time_dimension)
    spatial_axis = 1 - time_axis
    values = _read_numeric(netcdf_variable[:], np.nan).astype(float)
    values = np.take(values, time_indices, axis=time_axis)
    values = np.take(values, spatial_indices, axis=spatial_axis)
    if time_axis == 1:
        values = values.T
    return np.asarray(values, dtype=float)


def _find_variable(dataset, expected_name):
    for name in dataset.variables:
        if str(name).lower() == expected_name.lower():
            return name
    return None