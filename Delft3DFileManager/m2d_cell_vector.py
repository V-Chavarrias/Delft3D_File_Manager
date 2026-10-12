"""Create a temporary UGRID mesh for imported per-cell M2D values."""

import os
import tempfile

import numpy as np


M2D_CELL_VECTOR_DESCRIPTION = "gdm_write_M2D_netcdf; v1.0"


class M2DCellVectorError(RuntimeError):
    """Raised when M2D cell values cannot be matched to an active mesh."""


def is_m2d_cell_vector_file(filepath):
    """Return whether a NetCDF file has the supported M2D description."""
    import netCDF4 as nc

    with nc.Dataset(filepath, "r") as dataset:
        return str(getattr(dataset, "description", "")) == M2D_CELL_VECTOR_DESCRIPTION


def create_m2d_cell_vector_sidecar(
    data_path,
    grid_path,
    output_path=None,
    expected_face_count=None,
):
    """Combine one face-value array with the topology of a UGRID mesh."""
    import netCDF4 as nc

    data_path = os.path.abspath(data_path)
    grid_path = os.path.abspath(grid_path)
    if output_path is None:
        descriptor, output_path = tempfile.mkstemp(
            prefix="delft3d_m2d_cell_",
            suffix=".nc",
        )
        os.close(descriptor)
    output_path = os.path.abspath(output_path)

    try:
        with nc.Dataset(data_path, "r") as data_dataset:
            if str(getattr(data_dataset, "description", "")) != M2D_CELL_VECTOR_DESCRIPTION:
                raise M2DCellVectorError(
                    "The NetCDF description does not identify a supported M2D cell-data file"
                )
            data_variable = data_dataset.variables.get("data")
            if data_variable is None:
                raise M2DCellVectorError("The M2D file does not contain a 'data' variable")
            if len(data_variable.dimensions) != 1 or not np.issubdtype(
                data_variable.dtype, np.number
            ):
                raise M2DCellVectorError(
                    "The M2D 'data' variable must be a one-dimensional numeric array"
                )
            values = np.ma.asarray(data_variable[:])

            with nc.Dataset(grid_path, "r") as grid_dataset:
                topology_name = _find_mesh2d_topology(grid_dataset)
                topology = grid_dataset.variables[topology_name]
                face_dimension = _face_dimension_name(
                    grid_dataset,
                    topology,
                )
                if face_dimension not in grid_dataset.dimensions:
                    raise M2DCellVectorError(
                        "The active grid has no valid 2D mesh face dimension"
                    )
                face_count = len(grid_dataset.dimensions[face_dimension])
                if (
                    expected_face_count is not None
                    and face_count != int(expected_face_count)
                ):
                    raise M2DCellVectorError(
                        f"The active mesh layer has {int(expected_face_count)} faces, but "
                        f"its NetCDF source has {face_count}"
                    )
                if values.shape != (face_count,):
                    raise M2DCellVectorError(
                        f"The M2D file contains {values.size} cell values, but the active grid "
                        f"has {face_count} faces"
                    )

                topology_variables = _topology_variables(grid_dataset, topology_name)
                with nc.Dataset(output_path, "w", format="NETCDF4") as derived:
                    for attribute in grid_dataset.ncattrs():
                        derived.setncattr(attribute, grid_dataset.getncattr(attribute))
                    derived.setncattr(
                        "description",
                        "Temporary mesh-backed view of imported M2D cell values",
                    )

                    dimension_names = set()
                    for variable_name in topology_variables:
                        dimension_names.update(
                            grid_dataset.variables[variable_name].dimensions
                        )
                    dimension_names.add(face_dimension)
                    for dimension_name in dimension_names:
                        dimension = grid_dataset.dimensions[dimension_name]
                        size = None if dimension.isunlimited() else len(dimension)
                        derived.createDimension(dimension_name, size)

                    for variable_name in topology_variables:
                        _copy_variable(
                            grid_dataset.variables[variable_name],
                            derived,
                            variable_name,
                        )
                    _complete_topology_dimensions(
                        derived.variables[topology_name],
                        grid_dataset.variables[topology_name],
                        grid_dataset,
                        face_dimension,
                    )

                    coordinates = str(
                        getattr(topology, "face_coordinates", "")
                    ).strip()
                    attributes = {
                        name: getattr(data_variable, name)
                        for name in data_variable.ncattrs()
                        if name not in {"_FillValue", "mesh", "location", "coordinates"}
                    }
                    attributes["mesh"] = topology_name
                    attributes["location"] = "face"
                    if coordinates:
                        attributes["coordinates"] = coordinates
                    if not attributes.get("long_name"):
                        attributes["long_name"] = "M2D cell value"

                    fill_value = getattr(data_variable, "_FillValue", None)
                    variable_options = {}
                    if fill_value is not None:
                        variable_options["fill_value"] = fill_value
                    output_variable = derived.createVariable(
                        "data",
                        data_variable.datatype,
                        (face_dimension,),
                        **variable_options,
                    )
                    for name, value in attributes.items():
                        output_variable.setncattr(name, value)
                    output_variable[:] = values
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        if output_path is not None and os.path.exists(output_path):
            os.remove(output_path)
        raise

    return output_path


def _find_mesh2d_topology(dataset):
    for name, variable in dataset.variables.items():
        if (
            str(getattr(variable, "cf_role", "")).strip().lower() == "mesh_topology"
            and int(getattr(variable, "topology_dimension", -1)) == 2
        ):
            return name
    for name in ("mesh2d", "Mesh2d"):
        if name in dataset.variables:
            return name
    raise M2DCellVectorError("The active grid has no 2D UGRID mesh topology")


def _face_dimension_name(dataset, topology):
    face_dimension = str(getattr(topology, "face_dimension", "")).strip()
    if face_dimension in dataset.dimensions:
        return face_dimension

    connectivity_name = str(
        getattr(topology, "face_node_connectivity", "")
    ).strip()
    connectivity = dataset.variables.get(connectivity_name)
    if connectivity is not None and connectivity.dimensions:
        return connectivity.dimensions[0]

    if "mesh2d_nFaces" in dataset.dimensions:
        return "mesh2d_nFaces"
    return ""


def _complete_topology_dimensions(
    target_topology,
    source_topology,
    source_dataset,
    face_dimension,
):
    if not str(getattr(target_topology, "face_dimension", "")).strip():
        target_topology.face_dimension = face_dimension

    node_dimension = str(getattr(source_topology, "node_dimension", "")).strip()
    if not node_dimension:
        node_coordinates = str(
            getattr(source_topology, "node_coordinates", "")
        ).split()
        if node_coordinates:
            coordinates = source_dataset.variables[node_coordinates[0]]
            if coordinates.dimensions:
                node_dimension = coordinates.dimensions[0]
                target_topology.node_dimension = node_dimension

    if not str(
        getattr(target_topology, "max_face_nodes_dimension", "")
    ).strip():
        connectivity_name = str(
            getattr(source_topology, "face_node_connectivity", "")
        ).strip()
        connectivity = source_dataset.variables.get(connectivity_name)
        if connectivity is not None and len(connectivity.dimensions) > 1:
            target_topology.max_face_nodes_dimension = connectivity.dimensions[1]


def _topology_variables(dataset, topology_name):
    topology = dataset.variables[topology_name]
    names = {topology_name}
    for attribute in topology.ncattrs():
        if attribute.endswith("_coordinates") or attribute.endswith("_connectivity"):
            names.update(str(getattr(topology, attribute, "")).split())
    pending = list(names)
    while pending:
        name = pending.pop()
        variable = dataset.variables.get(name)
        if variable is None:
            raise M2DCellVectorError(
                f"The active grid references missing topology variable '{name}'"
            )
        grid_mapping = str(getattr(variable, "grid_mapping", "")).strip()
        if grid_mapping and grid_mapping not in names:
            names.add(grid_mapping)
            pending.append(grid_mapping)
    return sorted(names)


def _copy_variable(source_variable, target_dataset, variable_name):
    fill_value = getattr(source_variable, "_FillValue", None)
    variable_options = {}
    if fill_value is not None:
        variable_options["fill_value"] = fill_value
    target_variable = target_dataset.createVariable(
        variable_name,
        source_variable.datatype,
        source_variable.dimensions,
        **variable_options,
    )
    for attribute in source_variable.ncattrs():
        if attribute != "_FillValue":
            target_variable.setncattr(attribute, getattr(source_variable, attribute))
    target_variable[...] = source_variable[...]
