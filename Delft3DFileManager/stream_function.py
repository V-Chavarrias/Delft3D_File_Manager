"""Streamfunction calculation for UGRID edge discharge data."""

import hashlib
import os
import re
from collections import deque

import numpy as np


class StreamFunctionError(RuntimeError):
    """Raised when a map output cannot provide a valid streamfunction input."""


def compute_stream_function(discharge, edge_node_connectivity, n_nodes, start_index=0):
    """Compute node streamfunction values for one or more time steps.

    This follows the Delft3D MATLAB implementation: discharge is positive in
    the direction from the first to the second edge node, and each connected
    component is shifted so its minimum value is zero.
    """
    values = np.ma.asarray(discharge)
    if values.ndim == 1:
        values = values[np.newaxis, :]
    elif values.ndim != 2:
        raise ValueError("discharge must have shape (time, edge) or (edge,)")
    values = np.asarray(values.filled(np.nan), dtype=float)

    connectivity = np.ma.asarray(edge_node_connectivity)
    if connectivity.ndim != 2:
        raise ValueError("edge_node_connectivity must be a two-dimensional array")
    if connectivity.shape[0] == 2 and connectivity.shape[1] != 2:
        connectivity = connectivity.T
    if connectivity.shape[1] != 2:
        raise ValueError("edge_node_connectivity must have two node columns")
    connectivity = np.asarray(connectivity.filled(-1), dtype=int) - int(start_index)

    if values.shape[1] != connectivity.shape[0]:
        raise ValueError("discharge edge count does not match connectivity")
    if np.any(connectivity < 0) or np.any(connectivity >= int(n_nodes)):
        raise ValueError("edge connectivity contains a node outside the mesh")

    result = np.full((values.shape[0], int(n_nodes)), np.nan, dtype=float)
    for time_index, time_values in enumerate(values):
        valid = np.isfinite(time_values)
        valid_edges = connectivity[valid]
        valid_discharge = time_values[valid]
        psi = np.zeros(int(n_nodes), dtype=float)
        if valid_edges.size:
            psi[np.unique(valid_edges)] = np.nan

        adjacency = [[] for _ in range(int(n_nodes))]
        for edge, flow in zip(valid_edges, valid_discharge):
            start, end = int(edge[0]), int(edge[1])
            adjacency[start].append((end, float(flow)))
            adjacency[end].append((start, -float(flow)))

        referenced_nodes = set(np.asarray(valid_edges, dtype=int).reshape(-1).tolist())
        while referenced_nodes:
            seed = min(referenced_nodes)
            psi[seed] = 0.0
            component_nodes = []
            pending = deque([seed])
            referenced_nodes.remove(seed)
            while pending:
                current = pending.popleft()
                component_nodes.append(current)
                for neighbor, delta in adjacency[current]:
                    if np.isnan(psi[neighbor]):
                        psi[neighbor] = psi[current] + delta
                        referenced_nodes.discard(neighbor)
                        pending.append(neighbor)
            component_nodes = np.asarray(component_nodes, dtype=int)
            psi[component_nodes] -= np.min(psi[component_nodes])

        result[time_index] = psi

    return result


def create_stream_function_sidecar(source_paths, output_path=None):
    """Create a minimal UGRID sidecar containing a time-dependent node field.

    Multiple source files are merged by coincident node coordinates. Duplicate
    edges and faces from partition ghost regions are removed; duplicate finite
    discharges must agree after orientation is reconciled.
    """
    try:
        import netCDF4 as nc
    except ModuleNotFoundError as exc:
        raise StreamFunctionError("The netCDF4 package is required") from exc

    paths = [os.path.abspath(path) for path in source_paths]
    if not paths:
        raise StreamFunctionError("No map output was supplied")
    if output_path is None:
        base, extension = os.path.splitext(paths[0])
        output_path = f"{base}_qgis_stream_function{extension}"
    output_path = os.path.abspath(output_path)

    source_signature = "|".join(
        f"{path}:{os.path.getmtime(path)}" for path in paths
    )
    signature = hashlib.sha256(
        f"v2|{source_signature}".encode("utf-8")
    ).hexdigest()
    if os.path.exists(output_path):
        try:
            with nc.Dataset(output_path, "r") as dataset:
                if getattr(dataset, "qgis_stream_function_signature", "") == signature:
                    return output_path
        except (OSError, RuntimeError):
            pass

    merged = _read_and_merge_sources(paths)
    values = compute_stream_function(
        merged["discharge"], merged["edges"], len(merged["node_x"])
    )

    with nc.Dataset(output_path, "w", format="NETCDF4") as dataset:
        dataset.createDimension("mesh2d_nNodes", len(merged["node_x"]))
        dataset.createDimension("mesh2d_nEdges", len(merged["edges"]))
        dataset.createDimension("mesh2d_nFaces", len(merged["faces"]))
        dataset.createDimension("mesh2d_nMax_face_nodes", merged["faces"].shape[1])
        dataset.createDimension("Two", 2)
        dataset.createDimension("time", len(merged["time"]))

        topology = dataset.createVariable("mesh2d", "i4")
        topology.cf_role = "mesh_topology"
        topology.topology_dimension = 2
        topology.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        topology.node_dimension = "mesh2d_nNodes"
        topology.max_face_nodes_dimension = "mesh2d_nMax_face_nodes"
        topology.edge_node_connectivity = "mesh2d_edge_nodes"
        topology.edge_dimension = "mesh2d_nEdges"
        topology.face_node_connectivity = "mesh2d_face_nodes"
        topology.face_dimension = "mesh2d_nFaces"

        node_x = dataset.createVariable("mesh2d_node_x", "f8", ("mesh2d_nNodes",))
        node_y = dataset.createVariable("mesh2d_node_y", "f8", ("mesh2d_nNodes",))
        node_x[:] = merged["node_x"]
        node_y[:] = merged["node_y"]
        node_x.units = "m"
        node_y.units = "m"
        node_x.standard_name = "projection_x_coordinate"
        node_y.standard_name = "projection_y_coordinate"

        edges = dataset.createVariable("mesh2d_edge_nodes", "i4", ("mesh2d_nEdges", "Two"))
        edges.cf_role = "edge_node_connectivity"
        edges.start_index = 1
        edges[:] = np.asarray(merged["edges"], dtype=np.int32) + 1

        faces = dataset.createVariable(
            "mesh2d_face_nodes",
            "i4",
            ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"),
            fill_value=-999,
        )
        faces.cf_role = "face_node_connectivity"
        faces.start_index = 1
        face_data = np.asarray(merged["faces"], dtype=np.int32)
        faces[:] = np.where(face_data >= 0, face_data + 1, -999)

        time = dataset.createVariable("time", "f8", ("time",))
        time[:] = merged["time"]
        for name, value in merged["time_attrs"].items():
            setattr(time, name, value)

        stream_function = dataset.createVariable(
            "stream_function", "f8", ("time", "mesh2d_nNodes"), fill_value=np.nan
        )
        stream_function[:] = values
        stream_function.mesh = "mesh2d"
        stream_function.location = "node"
        stream_function.coordinates = "mesh2d_node_x mesh2d_node_y"
        stream_function.long_name = "Streamfunction"
        stream_function.units = "m3 s-1"
        dataset.qgis_stream_function_signature = signature
        dataset.qgis_stream_function_sources = "|".join(paths)

    return output_path


def _read_and_merge_sources(paths):
    import netCDF4 as nc

    node_lookup = {}
    node_x = []
    node_y = []
    edge_lookup = {}
    edge_values = {}
    faces = []
    face_lookup = set()
    time_values = None
    time_attrs = {}

    for path in paths:
        with nc.Dataset(path, "r") as dataset:
            node_x_name = _find_name(dataset, "mesh2d_node_x")
            node_y_name = _find_name(dataset, "mesh2d_node_y")
            edge_name = _find_name(dataset, "mesh2d_edge_nodes")
            face_name = _find_name(dataset, "mesh2d_face_nodes")
            discharge_name = _find_discharge_name(dataset)
            if not all((node_x_name, node_y_name, edge_name, face_name, discharge_name)):
                raise StreamFunctionError(f"{os.path.basename(path)} lacks required mesh2d/q1 variables")

            local_x = np.asarray(dataset.variables[node_x_name][:], dtype=float)
            local_y = np.asarray(dataset.variables[node_y_name][:], dtype=float)
            local_edges = _connectivity(
                dataset.variables[edge_name][:], dataset.variables[edge_name], edge_data=True
            )
            local_faces = _connectivity(dataset.variables[face_name][:], dataset.variables[face_name])
            local_edges = local_edges[~np.any(local_edges < 0, axis=1)]
            local_faces = [row[row >= 0] for row in local_faces if np.count_nonzero(row >= 0) >= 3]
            local_discharge, local_time = _normalise_discharge(
                dataset.variables[discharge_name], len(local_edges)
            )
            edge_owner_mask = _owned_edge_mask(dataset, len(local_edges))
            if edge_owner_mask is not None:
                local_edges = local_edges[edge_owner_mask]
                local_discharge = local_discharge[:, edge_owner_mask]
            if time_values is None:
                time_values = local_time
                time_variable = _find_time_variable(dataset, dataset.variables[discharge_name])
                if time_variable is not None:
                    time_attrs = {
                        name: getattr(time_variable, name)
                        for name in time_variable.ncattrs()
                    }
            elif not np.array_equal(time_values, local_time):
                raise StreamFunctionError("Partition time axes do not match")

            local_to_global = []
            for x_value, y_value in zip(local_x, local_y):
                key = (round(float(x_value), 9), round(float(y_value), 9))
                if key not in node_lookup:
                    node_lookup[key] = len(node_x)
                    node_x.append(float(x_value))
                    node_y.append(float(y_value))
                local_to_global.append(node_lookup[key])

            for edge_index, (start, end) in enumerate(local_edges):
                first = local_to_global[int(start)]
                second = local_to_global[int(end)]
                key = tuple(sorted((first, second)))
                oriented_values = local_discharge[:, edge_index]
                if (first, second) != key:
                    oriented_values = -oriented_values
                if key not in edge_lookup:
                    edge_lookup[key] = len(edge_lookup)
                    edge_values[key] = np.asarray(oriented_values, dtype=float)
                elif not _equal_with_nan(edge_values[key], oriented_values):
                    raise StreamFunctionError("Partition edges contain conflicting q1 values")

            for local_face in local_faces:
                global_face = tuple(local_to_global[int(node)] for node in local_face)
                face_key = tuple(sorted(global_face))
                if face_key not in face_lookup:
                    face_lookup.add(face_key)
                    faces.append(global_face)

    if time_values is None:
        raise StreamFunctionError("No time-dependent q1 data was found")
    max_face_nodes = max((len(face) for face in faces), default=0)
    padded_faces = np.full((len(faces), max_face_nodes), -1, dtype=int)
    for index, face in enumerate(faces):
        padded_faces[index, :len(face)] = face
    ordered_edges = [None] * len(edge_lookup)
    ordered_values = [None] * len(edge_lookup)
    for edge, index in edge_lookup.items():
        ordered_edges[index] = edge
        ordered_values[index] = edge_values[edge]
    return {
        "node_x": np.asarray(node_x),
        "node_y": np.asarray(node_y),
        "edges": np.asarray(ordered_edges, dtype=int),
        "faces": padded_faces,
        "discharge": np.asarray(ordered_values, dtype=float).T,
        "time": np.asarray(time_values),
        "time_attrs": time_attrs,
    }


def _find_name(dataset, expected):
    expected = expected.lower()
    return next((name for name in dataset.variables if name.lower() == expected), None)


def _find_discharge_name(dataset):
    for name in dataset.variables:
        if name.lower() in ("q1", "mesh2d_q1"):
            return name
    return None


def _find_time_variable(dataset, variable):
    for dimension in variable.dimensions:
        if "time" in dimension.lower() and dimension in dataset.variables:
            return dataset.variables[dimension]
    return None


def _owned_edge_mask(dataset, n_edges):
    """Return the partition-owned edge mask when face ownership is available."""
    partition_match = re.search(r"_(\d{4})_(?:map|fou|rst|his)\.", str(dataset.filepath()))
    domain_name = _find_name(dataset, "mesh2d_flowelem_domain")
    edge_faces_name = _find_name(dataset, "mesh2d_edge_faces")
    if not partition_match or not domain_name or not edge_faces_name:
        return None

    partition_id = int(partition_match.group(1))
    domains = np.asarray(dataset.variables[domain_name][:]).reshape(-1)
    edge_faces = _connectivity(
        dataset.variables[edge_faces_name][:], dataset.variables[edge_faces_name], edge_data=True
    )
    if edge_faces.shape[0] != n_edges:
        return None
    valid_faces = (edge_faces >= 0) & (edge_faces < len(domains))
    owned = np.zeros(n_edges, dtype=bool)
    for edge_index, face_indices in enumerate(edge_faces):
        owned[edge_index] = np.any(
            valid_faces[edge_index] & (domains[np.maximum(face_indices, 0)] == partition_id)
        )
    return owned


def _connectivity(data, variable, edge_data=False):
    values = np.ma.asarray(data)
    if values.ndim != 2:
        raise StreamFunctionError("UGRID connectivity must be two-dimensional")
    spatial_axis = next(
        (axis for axis, dimension in enumerate(variable.dimensions)
         if ("nedge" in dimension.lower() if edge_data else "nface" in dimension.lower())),
        None,
    )
    if spatial_axis is None:
        if edge_data and values.shape[0] == 2:
            spatial_axis = 1
        elif edge_data and values.shape[1] == 2:
            spatial_axis = 0
        else:
            raise StreamFunctionError("UGRID connectivity dimensions are ambiguous")
    if spatial_axis == 1:
        values = values.T
    fill_value = getattr(variable, "_FillValue", -1)
    values = values.filled(fill_value)
    return np.asarray(values, dtype=int) - int(getattr(variable, "start_index", 0))


def _normalise_discharge(variable, n_edges):
    values = np.ma.asarray(variable[:])
    if values.ndim == 1:
        if values.shape[0] != n_edges:
            raise StreamFunctionError("q1 edge count does not match mesh edges")
        values = values[np.newaxis, :]
        time_values = np.asarray([0.0])
    elif values.ndim == 2:
        edge_axis = next((axis for axis, size in enumerate(values.shape) if size == n_edges), None)
        if edge_axis is None:
            raise StreamFunctionError("q1 does not have the mesh edge dimension")
        values = np.moveaxis(values, edge_axis, -1)
        time_values = np.arange(values.shape[0], dtype=float)
        time_dimension = variable.dimensions[1 - edge_axis]
        if time_dimension in variable.group().variables:
            time_values = np.asarray(variable.group().variables[time_dimension][:])
    else:
        raise StreamFunctionError("q1 must have edge or time/edge dimensions")
    return np.asarray(values.filled(np.nan), dtype=float), time_values


def _equal_with_nan(first, second):
    return np.all((np.isclose(first, second, equal_nan=True)))