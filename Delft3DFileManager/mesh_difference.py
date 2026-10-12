"""Compare native mesh datasets and write a persistent UGRID difference."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
import tempfile

import numpy as np


@dataclass
class DifferenceGroup:
    name: str
    left_group: int
    right_group: int
    location: str
    scalar: bool
    units: str
    pairs: list
    absolute_time: bool


def validate_topology(left_vertices, left_faces, right_vertices, right_faces):
    """Require identical coordinates, connectivity and native element ordering."""
    left = np.asarray([(point.x(), point.y()) for point in left_vertices])
    right = np.asarray([(point.x(), point.y()) for point in right_vertices])
    if not left_faces or not len(left):
        raise ValueError("A 2D mesh with nodes and faces is required.")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("Mesh coordinates must be finite.")
    if left.shape != right.shape or not np.array_equal(left, right):
        raise ValueError("The meshes have different node coordinates or node ordering.")
    if left_faces != right_faces:
        raise ValueError("The meshes have different face connectivity or face ordering.")
    for face in left_faces:
        if len(face) < 3 or any(node < 0 or node >= len(left) for node in face):
            raise ValueError("The mesh has invalid face connectivity.")


def _index(group, dataset=0):
    from qgis.core import QgsMeshDatasetIndex

    return QgsMeshDatasetIndex(group, dataset)


def _dataset_access(layer):
    # Layer indexes include attached/virtual groups; provider indexes do not.
    if callable(getattr(layer, "datasetGroupsIndexes", None)):
        return layer, list(layer.datasetGroupsIndexes()), True
    provider = layer.dataProvider()
    return provider, range(provider.datasetGroupCount()), False


def _group_metadata(access, group, layer_indexes):
    return access.datasetGroupMetadata(_index(group) if layer_indexes else group)


def _location(metadata):
    from qgis.core import QgsMeshDatasetGroupMetadata

    enum = getattr(QgsMeshDatasetGroupMetadata, "DataType", QgsMeshDatasetGroupMetadata)
    for label, name in (("node", "DataOnVertices"), ("face", "DataOnFaces")):
        value = getattr(QgsMeshDatasetGroupMetadata, name, None)
        if value is None:
            value = getattr(enum, name, None)
        if metadata.dataType() == value:
            return label
    return None


def _units(metadata):
    return str(next(
        (value for key, value in metadata.extraOptions().items() if key.lower() == "units"),
        "",
    )).strip()


def _times(layer, access, group, metadata, layer_indexes):
    count = access.datasetCount(_index(group) if layer_indexes else group)
    if count <= 0:
        raise ValueError("dataset group is empty")
    temporal_method = getattr(metadata, "isTemporal", None)
    temporal = temporal_method() if callable(temporal_method) else count > 1
    if not temporal:
        if count != 1:
            raise ValueError("non-temporal group contains multiple datasets")
        return {None: 0}, False
    reference = metadata.referenceTime()
    if not reference.isValid():
        properties = getattr(layer, "temporalProperties", None)
        if callable(properties):
            reference = properties().referenceTime()
    absolute = reference.isValid()
    origin = reference.toMSecsSinceEpoch() if absolute else 0
    times = {}
    for dataset in range(count):
        item = access.datasetMetadata(_index(group, dataset))
        if not item.isValid():
            raise ValueError(f"dataset {dataset} is invalid")
        hours = float(item.time())
        if not math.isfinite(hours):
            raise ValueError("dataset time is not finite")
        # QGIS temporal indexes have millisecond precision; time() is in hours.
        timestamp = origin + round(hours * 3_600_000)
        if timestamp in times:
            raise ValueError("dataset group has duplicate timestamps")
        times[timestamp] = dataset
    return times, absolute


def prepare_groups(left_layer, right_layer):
    """Return matching groups and explicit reasons for skipped groups."""
    left, left_indexes, left_scope = _dataset_access(left_layer)
    right, right_indexes, right_scope = _dataset_access(right_layer)
    catalogs = []
    for access, indexes, scope in (
        (left, left_indexes, left_scope), (right, right_indexes, right_scope)
    ):
        catalog = {}
        for group in indexes:
            metadata = _group_metadata(access, group, scope)
            catalog.setdefault(metadata.name(), []).append((group, metadata))
        catalogs.append(catalog)
    groups, skipped = [], []
    for name in sorted(set(catalogs[0]) | set(catalogs[1])):
        entries_a, entries_b = catalogs[0].get(name, []), catalogs[1].get(name, [])
        reason = None
        if not entries_a or not entries_b:
            reason = "not present in both layers"
        elif len(entries_a) != 1 or len(entries_b) != 1:
            reason = "ambiguous duplicate dataset name"
        else:
            group_a, metadata_a = entries_a[0]
            group_b, metadata_b = entries_b[0]
            location = _location(metadata_a)
            if location is None or location != _location(metadata_b):
                reason = "unsupported or different data locations (only nodes/faces supported)"
            elif metadata_a.isScalar() != metadata_b.isScalar():
                reason = "scalar/vector mismatch"
            elif _units(metadata_a) != _units(metadata_b):
                reason = "different declared units"
            else:
                try:
                    times_a, absolute_a = _times(
                        left_layer, left, group_a, metadata_a, left_scope
                    )
                    times_b, absolute_b = _times(
                        right_layer, right, group_b, metadata_b, right_scope
                    )
                    static_a, static_b = None in times_a, None in times_b
                    if not static_a and not static_b and absolute_a != absolute_b:
                        raise ValueError("only one dataset has an absolute reference time")
                    if static_a and static_b:
                        pairs = [(None, 0, 0)]
                    elif static_a:
                        pairs = [(time, 0, index) for time, index in sorted(times_b.items())]
                    elif static_b:
                        pairs = [(time, index, 0) for time, index in sorted(times_a.items())]
                    else:
                        pairs = [
                            (time, times_a[time], times_b[time])
                            for time in sorted(times_a.keys() & times_b.keys())
                        ]
                    if not pairs:
                        raise ValueError("no common timestamps")
                    groups.append(DifferenceGroup(
                        name, group_a, group_b, location, metadata_a.isScalar(),
                        _units(metadata_a), pairs,
                        absolute_b if static_a else absolute_a,
                    ))
                except ValueError as exc:
                    reason = str(exc)
        if reason:
            skipped.append(f"{name}: {reason}")
    if not groups:
        raise ValueError("No compatible matching datasets.\n" + "\n".join(skipped))
    temporal = [group for group in groups if group.pairs[0][0] is not None]
    if len({group.absolute_time for group in temporal}) > 1:
        raise ValueError("Cannot combine absolute and relative time axes in one output mesh.")
    return groups, skipped


def _read_values(layer, group, dataset, scalar, location, vertices, faces):
    access, _, _ = _dataset_access(layer)
    index = _index(group, dataset)
    if not access.datasetMetadata(index).isValid():
        raise ValueError(f"Dataset {group}/{dataset} is invalid.")
    count = len(vertices) if location == "node" else len(faces)
    block = access.datasetValues(index, 0, count)
    if not block.isValid() or block.count() != count:
        raise ValueError(f"Could not read dataset {group}/{dataset}.")
    values = np.asarray(block.values(), dtype=float).copy()
    components = 1 if scalar else 2
    if values.size != count * components:
        raise ValueError(f"Dataset {group}/{dataset} has an unexpected value count.")
    values = values.reshape(count, components)
    active_method = getattr(access, "areFacesActive", None)
    if callable(active_method):
        active_block = active_method(index, 0, len(faces))
        if not active_block.isValid():
            raise ValueError(f"Could not read active faces for dataset {group}/{dataset}.")
        flags = active_block.active()
        if len(flags):
            if len(flags) != len(faces):
                raise ValueError("Active face flags have an unexpected count.")
            active = np.asarray(flags, dtype=bool)
            if location == "node":
                active_nodes = np.zeros(len(vertices), dtype=bool)
                for face, enabled in zip(faces, active):
                    if enabled:
                        active_nodes[list(face)] = True
                active = active_nodes
            values[~active] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def write_difference(output_path, left_layer, right_layer, vertices, faces, groups):
    """Stream differences to a new file; never overwrite an existing file."""
    try:
        import netCDF4 as nc
    except ImportError as exc:
        raise RuntimeError(
            "netCDF4 is required. Use Install Python Dependencies, then restart QGIS."
        ) from exc
    output_path = os.path.abspath(output_path)
    if os.path.exists(output_path):
        raise ValueError("The output file already exists. Choose a new filename.")
    descriptor, temporary = tempfile.mkstemp(
        suffix=".nc", prefix=".mesh_difference_", dir=os.path.dirname(output_path)
    )
    os.close(descriptor)
    try:
        with nc.Dataset(temporary, "w", format="NETCDF4") as output:
            output.Conventions = "CF-1.8 UGRID-1.0"
            output.description = f"Mesh difference: {left_layer.name()} - {right_layer.name()}"
            output.source_a = left_layer.source()
            output.source_b = right_layer.source()
            output.createDimension("mesh2d_nNodes", len(vertices))
            output.createDimension("mesh2d_nFaces", len(faces))
            output.createDimension("mesh2d_nMax_face_nodes", max(map(len, faces)))
            topology = output.createVariable("mesh2d", "i4")
            topology.cf_role = "mesh_topology"
            topology.topology_dimension = 2
            topology.node_coordinates = "mesh2d_node_x mesh2d_node_y"
            topology.node_dimension = "mesh2d_nNodes"
            topology.face_dimension = "mesh2d_nFaces"
            topology.face_node_connectivity = "mesh2d_face_nodes"
            crs = output.createVariable("projected_coordinate_system", "i4")
            crs.crs_wkt = left_layer.crs().toWkt()
            crs.spatial_ref = crs.crs_wkt
            authority = left_layer.crs().authid()
            if authority.upper().startswith("EPSG:"):
                crs.epsg = int(authority.split(":")[1])
                crs.epsg_code = authority
            for axis in ("x", "y"):
                coordinate = output.createVariable(
                    f"mesh2d_node_{axis}", "f8", ("mesh2d_nNodes",)
                )
                coordinate.standard_name = (
                    "longitude" if axis == "x" else "latitude"
                ) if left_layer.crs().isGeographic() else f"projection_{axis}_coordinate"
                if left_layer.crs().isGeographic():
                    coordinate.units = "degrees_east" if axis == "x" else "degrees_north"
                coordinate.grid_mapping = "projected_coordinate_system"
                coordinate[:] = [getattr(vertex, axis)() for vertex in vertices]
            connectivity = output.createVariable(
                "mesh2d_face_nodes", "i4",
                ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), fill_value=-1,
            )
            connectivity.cf_role = "face_node_connectivity"
            connectivity.start_index = 0
            for index, face in enumerate(faces):
                connectivity[index, :len(face)] = face
            timestamps = sorted({
                time for group in groups for time, _, _ in group.pairs if time is not None
            })
            if not timestamps and any(not group.scalar for group in groups):
                timestamps = [0]
            time_indexes = {time: index for index, time in enumerate(timestamps)}
            if timestamps:
                output.createDimension("time", len(timestamps))
                time_variable = output.createVariable("time", "f8", ("time",))
                temporal_group = next(
                    (group for group in groups if group.pairs[0][0] is not None), None
                )
                origin = timestamps[0]
                if temporal_group is not None and temporal_group.absolute_time:
                    date = datetime.fromtimestamp(origin / 1000, tz=timezone.utc)
                    time_variable.units = f"seconds since {date.strftime('%Y-%m-%d %H:%M:%S.%f')} +00:00"
                else:
                    origin = 0
                    time_variable.units = "seconds"
                time_variable.standard_name = "time"
                time_variable.calendar = "standard"
                time_variable[:] = [(time - origin) / 1000 for time in timestamps]
            for group_index, group in enumerate(groups):
                dimension = "mesh2d_nNodes" if group.location == "node" else "mesh2d_nFaces"
                temporal = group.pairs[0][0] is not None
                # MDAL's time-independent vector reader reads X for both components.
                # Store constant vectors on the shared time axis to retain Y.
                time_dimension = temporal or not group.scalar
                dimensions = ("time", dimension) if time_dimension else (dimension,)
                components = ("",) if group.scalar else ("x", "y")
                variables = []
                for component in components:
                    variable = output.createVariable(
                        f"difference_{group_index}{'_' + component if component else ''}",
                        "f8", dimensions, fill_value=np.nan,
                    )
                    label = f"{group.name} difference (A - B)"
                    variable.long_name = f"{component} component of {label}" if component else label
                    variable.mesh = "mesh2d"
                    variable.location = group.location
                    variable.grid_mapping = "projected_coordinate_system"
                    variable.units = group.units
                    variable.source_is_temporal = int(temporal)
                    variables.append(variable)
                for timestamp, dataset_a, dataset_b in group.pairs:
                    a = _read_values(
                        left_layer, group.left_group, dataset_a, group.scalar,
                        group.location, vertices, faces,
                    )
                    b = _read_values(
                        right_layer, group.right_group, dataset_b, group.scalar,
                        group.location, vertices, faces,
                    )
                    with np.errstate(invalid="ignore", over="ignore"):
                        values = a - b
                    values[~np.isfinite(values)] = np.nan
                    for component, variable in enumerate(variables):
                        if temporal:
                            variable[time_indexes[timestamp], :] = values[:, component]
                        elif time_dimension:
                            for row in range(len(timestamps)):
                                variable[row, :] = values[:, component]
                        else:
                            variable[:] = values[:, component]
        if os.path.exists(output_path):
            raise ValueError("The output file already exists. Choose a new filename.")
        os.rename(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return output_path
