"""Froude number calculation for 2D MAP output."""

import os

import numpy as np


class FroudeError(RuntimeError):
    """Raised when MAP output cannot provide a valid Froude input."""


def compute_froude_number(flow_depth, velocity_magnitude, gravity=9.81):
    """Compute Froude number from face flow depth and velocity magnitude."""
    depth = np.ma.asarray(flow_depth)
    velocity = np.ma.asarray(velocity_magnitude)
    if depth.shape != velocity.shape:
        raise ValueError("flow depth and velocity magnitude must have matching shapes")
    if depth.ndim != 2:
        raise ValueError("flow depth and velocity magnitude must have shape (time, face)")
    depth = np.asarray(depth.filled(np.nan), dtype=float)
    velocity = np.asarray(velocity.filled(np.nan), dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return velocity / np.sqrt(float(gravity) * depth)


def create_froude_sidecar(source_path, output_path=None):
    """Create a UGRID sidecar containing a time-dependent face Froude field."""
    try:
        import netCDF4 as nc
    except ModuleNotFoundError as exc:
        raise FroudeError("The netCDF4 package is required") from exc

    source_path = os.path.abspath(source_path)
    if output_path is None:
        base, extension = os.path.splitext(source_path)
        output_path = f"{base}_qgis_froude{extension}"
    output_path = os.path.abspath(output_path)

    with nc.Dataset(source_path, "r") as source:
        depth_name = _find_field(source, ("waterdepth", "flowdepth", "depth"))
        velocity_name = _find_field(source, ("ucmag", "umag", "velocitymagnitude", "velocity"))
        if not depth_name or not velocity_name:
            raise FroudeError("The MAP output lacks required 2D flow depth and velocity magnitude variables")

        depth = _read_time_face(source.variables[depth_name], source)
        velocity = _read_time_face(source.variables[velocity_name], source)
        values = compute_froude_number(depth, velocity)
        face_dimension = _face_dimension(source.variables[depth_name], source)
        time_dimension = _time_dimension(source.variables[depth_name], source)

        with nc.Dataset(output_path, "w", format="NETCDF4") as derived:
            _copy_dimensions(source, derived, {time_dimension, face_dimension})
            _copy_topology(source, derived)
            froude = derived.createVariable("froude_number", "f8", (time_dimension, face_dimension), fill_value=np.nan)
            froude[:] = values
            froude.mesh = "mesh2d"
            froude.location = "face"
            froude.coordinates = "mesh2d_face_x mesh2d_face_y"
            froude.long_name = "Froude number"
            froude.units = "1"
            _copy_time(source, derived, time_dimension)

    return output_path


def _find_field(dataset, suffixes):
    for name, variable in dataset.variables.items():
        text = " ".join(
            (
                str(name),
                str(getattr(variable, "standard_name", "") or ""),
                str(getattr(variable, "long_name", "") or ""),
            )
        ).lower().replace("_", "")
        if any(suffix in text for suffix in suffixes) and _time_dimension(variable, dataset) and _face_dimension(variable, dataset):
            return name
    return None


def _time_dimension(variable, dataset):
    return next((dimension for dimension in variable.dimensions if "time" in dimension.lower()), None)


def _face_dimension(variable, dataset):
    return next((dimension for dimension in variable.dimensions if "nfaces" in dimension.lower()), None)


def _read_time_face(variable, dataset):
    time_dimension = _time_dimension(variable, dataset)
    face_dimension = _face_dimension(variable, dataset)
    values = np.ma.asarray(variable[:])
    axes = [variable.dimensions.index(time_dimension), variable.dimensions.index(face_dimension)]
    return np.ma.asarray(np.transpose(values, axes))


def _copy_dimensions(source, derived, required):
    for name in required:
        derived.createDimension(name, len(source.dimensions[name]))
    for name in ("mesh2d_nNodes", "mesh2d_nEdges", "mesh2d_nMax_face_nodes", "Two"):
        if name in source.dimensions and name not in derived.dimensions:
            derived.createDimension(name, len(source.dimensions[name]))


def _copy_topology(source, derived):
    topology_names = {
        "mesh2d",
        "mesh2d_node_x",
        "mesh2d_node_y",
        "mesh2d_edge_nodes",
        "mesh2d_face_nodes",
    }
    for name in topology_names:
        if name not in source.variables:
            continue
        source_variable = source.variables[name]
        target = derived.createVariable(name, source_variable.datatype, source_variable.dimensions)
        for attribute in source_variable.ncattrs():
            setattr(target, attribute, getattr(source_variable, attribute))
        target[:] = source_variable[:]


def _copy_time(source, derived, time_dimension):
    if time_dimension not in source.variables:
        return
    source_variable = source.variables[time_dimension]
    target = derived.createVariable(time_dimension, source_variable.datatype, source_variable.dimensions)
    for attribute in source_variable.ncattrs():
        setattr(target, attribute, getattr(source_variable, attribute))
    target[:] = source_variable[:]