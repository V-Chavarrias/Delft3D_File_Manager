"""On-demand reading of large (partitioned) Delft3D FM MAP and restart files.

For UGRID MAP files the 2D mesh is read once. Classic D-Flow FM restart files
do not contain node coordinates, so their owned flow-element centers are read
as point grids instead. Afterwards each request reads one hyperslab (variable,
time, extra-dimension indices) from every partition. Nothing is written to
disk.
"""

import glob
import os
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

from .froude import compute_froude_number
from .stream_function import compute_stream_function

FACE = "face"
NODE = "node"
POINT = "point"

FROUDE_KEY = "derived:froude_number"
VELOCITY_MAGNITUDE_KEY = "derived:velocity_magnitude"
BED_LEVEL_CHANGE_KEY = "derived:cumulative_bed_level_change"
STREAM_FUNCTION_KEY = "derived:stream_function"
THETA_KEY_PREFIX = "derived:theta:"
WATER_DENSITY = 1000.0
GRAVITY = 9.81

_PARTITION_PATTERN = re.compile(r"^(?P<prefix>.*_)(?P<part>\d{4})(?P<suffix>_.*\.nc)$", re.IGNORECASE)


class LargeMapError(RuntimeError):
    """Raised when a MAP or restart file cannot be read by the large viewer."""


@dataclass
class ExtraDimension:
    name: str
    size: int
    labels: list


@dataclass
class VariableEntry:
    key: str
    label: str
    location: str
    has_time: bool
    extra_dims: list = field(default_factory=list)
    derived: bool = False
    units: str = ""


@dataclass
class PartitionGrid:
    """Owned (non-ghost) part of one partition's mesh or restart point grid."""

    path: str
    partition_id: object
    node_x: np.ndarray
    node_y: np.ndarray
    faces: np.ndarray
    face_index: np.ndarray
    node_index: np.ndarray
    ghost_filtered: bool
    point_mode: bool = False

    @property
    def face_count(self):
        return int(len(self.face_index))


def _netcdf():
    try:
        import netCDF4
    except ModuleNotFoundError as exc:
        raise LargeMapError("The netCDF4 package is required") from exc
    return netCDF4


def discover_partitions(path):
    """Return the sorted partition siblings of ``path`` (or ``[path]``)."""
    path = os.path.abspath(str(path))
    match = _PARTITION_PATTERN.match(os.path.basename(path))
    if not match:
        return [path]
    prefix = match.group("prefix")
    suffix = match.group("suffix")
    pattern = os.path.join(os.path.dirname(path), f"{glob.escape(prefix)}????{glob.escape(suffix)}")
    exact = re.compile(rf"^{re.escape(prefix)}\d{{4}}{re.escape(suffix)}$", re.IGNORECASE)
    siblings = sorted(
        os.path.abspath(candidate)
        for candidate in glob.glob(pattern)
        if exact.match(os.path.basename(candidate))
    )
    return siblings or [path]


def partition_id(path):
    match = _PARTITION_PATTERN.match(os.path.basename(str(path)))
    return int(match.group("part")) if match else None


def model_base_name(path):
    """File name without extension and without the partition number (``RIJN_0001_map.nc`` -> ``RIJN_map``)."""
    name = os.path.basename(str(path))
    match = _PARTITION_PATTERN.match(name)
    if match:
        name = match.group("prefix") + match.group("suffix")[1:]
    return os.path.splitext(name)[0]


def _find_variable(dataset, *suffixes):
    """Find a variable whose lower-case name equals or ends with ``_<suffix>``."""
    for suffix in suffixes:
        suffix = suffix.lower()
        for name in dataset.variables:
            lower = name.lower()
            if lower == suffix or lower.endswith(f"_{suffix}"):
                return name
    return None


def _topology(dataset):
    for name, variable in dataset.variables.items():
        attrs = variable.ncattrs()
        if (
            "cf_role" in attrs
            and str(variable.getncattr("cf_role")) == "mesh_topology"
            and int(getattr(variable, "topology_dimension", 0) or 0) == 2
        ):
            return name, variable
    return None, None


@dataclass
class _Layout:
    topology: str
    node_x: str
    node_y: str
    face_nodes: str
    face_dim: str
    node_dim: str
    edge_dim: str
    time_dim: str
    time_var: str
    excluded: set
    geometry: str = "mesh"


def _restart_layout(dataset):
    """Return a point-grid layout for a classic D-Flow FM restart dataset."""
    face_dim = next(
        (name for name in ("nFlowElem", "nNetElem") if name in dataset.dimensions),
        None,
    )
    node_x = _find_variable(dataset, "flowelem_xzw", "flowelem_xcc")
    node_y = _find_variable(dataset, "flowelem_yzw", "flowelem_ycc")
    if not face_dim or not node_x or not node_y:
        return None
    if dataset.variables[node_x].dimensions != (face_dim,) or dataset.variables[node_y].dimensions != (face_dim,):
        return None

    time_var = "time" if "time" in dataset.variables else None
    if time_var is None:
        time_var = next(
            (name for name, var in dataset.variables.items() if getattr(var, "standard_name", "") == "time" and var.ndim == 1),
            None,
        )
    time_dim = dataset.variables[time_var].dimensions[0] if time_var else None
    edge_dim = next(
        (name for name in ("nFlowLink", "nNetLink") if name in dataset.dimensions),
        None,
    )
    excluded = {node_x, node_y}
    for suffix in (
        "flowelem_xzw",
        "flowelem_yzw",
        "flowelem_xcc",
        "flowelem_ycc",
        "flowelem_domain",
        "flowelemdomain",
        "flowelem_globalnr",
        "flowelemglobalnr",
        "flowelem",
        "netelemnode",
        "flowlink",
        "netlink",
        "flowlink_xu",
        "flowlink_yu",
        "netlink_xu",
        "netlink_yu",
    ):
        name = _find_variable(dataset, suffix)
        if name:
            excluded.add(name)
    return _Layout(
        topology=None,
        node_x=node_x,
        node_y=node_y,
        face_nodes=None,
        face_dim=face_dim,
        node_dim=None,
        edge_dim=edge_dim,
        time_dim=time_dim,
        time_var=time_var,
        excluded=excluded,
        geometry="points",
    )


def _layout(dataset):
    topology_name, topology = _topology(dataset)
    if topology is not None:
        coordinates = str(getattr(topology, "node_coordinates", "")).split()
        node_x = coordinates[0] if len(coordinates) == 2 else None
        node_y = coordinates[1] if len(coordinates) == 2 else None
        face_nodes = getattr(topology, "face_node_connectivity", None)
    else:
        topology_name = None
        node_x = node_y = face_nodes = None
    node_x = node_x if node_x in dataset.variables else _find_variable(dataset, "node_x")
    node_y = node_y if node_y in dataset.variables else _find_variable(dataset, "node_y")
    face_nodes = face_nodes if face_nodes in dataset.variables else _find_variable(dataset, "face_nodes")
    if not node_x or not node_y or not face_nodes:
        restart_layout = _restart_layout(dataset)
        if restart_layout is not None:
            return restart_layout
        raise LargeMapError(f"{os.path.basename(dataset.filepath())} has no 2D mesh topology")

    node_dim = dataset.variables[node_x].dimensions[0]
    face_dim = getattr(topology, "face_dimension", None) if topology is not None else None
    if face_dim not in dataset.dimensions:
        face_dim = next(
            (dim for dim in dataset.variables[face_nodes].dimensions if "face" in dim.lower() and "max" not in dim.lower()),
            dataset.variables[face_nodes].dimensions[0],
        )
    edge_dim = getattr(topology, "edge_dimension", None) if topology is not None else None

    time_var = "time" if "time" in dataset.variables else None
    if time_var is None:
        time_var = next(
            (name for name, var in dataset.variables.items() if getattr(var, "standard_name", "") == "time" and var.ndim == 1),
            None,
        )
    time_dim = dataset.variables[time_var].dimensions[0] if time_var else None

    excluded = {name for name in (topology_name, node_x, node_y, face_nodes) if name}
    if topology is not None:
        for attribute in topology.ncattrs():
            value = topology.getncattr(attribute)
            if isinstance(value, str):
                excluded.update(part for part in value.split() if part in dataset.variables)
    return _Layout(
        topology=topology_name,
        node_x=node_x,
        node_y=node_y,
        face_nodes=face_nodes,
        face_dim=face_dim,
        node_dim=node_dim,
        edge_dim=edge_dim,
        time_dim=time_dim,
        time_var=time_var,
        excluded=excluded,
    )


def is_restart_file(path):
    """Return whether ``path`` contains a classic D-Flow FM restart layout."""
    netcdf = _netcdf()
    try:
        with netcdf.Dataset(str(path), "r") as dataset:
            return _layout(dataset).geometry == "points"
    except (LargeMapError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _connectivity(variable, spatial_dim):
    variable.set_auto_mask(False)
    values = np.asarray(variable[:])
    variable.set_auto_mask(True)
    if variable.dimensions.index(spatial_dim) == 1:
        values = values.T
    values = values.astype(np.int64)
    invalid = values < int(getattr(variable, "start_index", 0))
    fill_value = getattr(variable, "_FillValue", None)
    if fill_value is not None:
        invalid |= values == int(fill_value)
    values = values - int(getattr(variable, "start_index", 0))
    values[invalid] = -1
    return values


def _domain_values(dataset, face_dim):
    name = _find_variable(dataset, "flowelem_domain", "flowelemdomain")
    if not name or dataset.variables[name].dimensions != (face_dim,):
        return None
    return np.ma.filled(np.ma.asarray(dataset.variables[name][:]), -1).astype(np.int64)


def read_partition_grid(path):
    """Read one partition's owned mesh faces or restart flow-element centers."""
    netcdf = _netcdf()
    path = os.path.abspath(str(path))
    part = partition_id(path)
    with netcdf.Dataset(path, "r") as dataset:
        layout = _layout(dataset)
        if layout.geometry == "points":
            point_x = np.asarray(np.ma.filled(dataset.variables[layout.node_x][:], np.nan), dtype=float)
            point_y = np.asarray(np.ma.filled(dataset.variables[layout.node_y][:], np.nan), dtype=float)
            domains = _domain_values(dataset, layout.face_dim) if part is not None else None
            if domains is not None:
                face_index = np.nonzero(domains == part)[0]
            else:
                face_index = np.arange(len(point_x))
            valid = (
                np.isfinite(point_x[face_index])
                & np.isfinite(point_y[face_index])
            )
            face_index = face_index[valid]
            return PartitionGrid(
                path=path,
                partition_id=part,
                node_x=point_x[face_index],
                node_y=point_y[face_index],
                faces=np.empty((0, 0), dtype=np.int64),
                face_index=face_index,
                node_index=face_index.copy(),
                ghost_filtered=domains is not None,
                point_mode=True,
            )
        node_x = np.asarray(np.ma.filled(dataset.variables[layout.node_x][:], np.nan), dtype=float)
        node_y = np.asarray(np.ma.filled(dataset.variables[layout.node_y][:], np.nan), dtype=float)
        faces = _connectivity(dataset.variables[layout.face_nodes], layout.face_dim)
        domains = _domain_values(dataset, layout.face_dim) if part is not None else None

    if domains is not None:
        face_index = np.nonzero(domains == part)[0]
    else:
        face_index = np.arange(len(faces))
    faces = faces[face_index]
    valid = (faces >= 0) & (faces < len(node_x))
    keep = np.count_nonzero(valid, axis=1) >= 3
    face_index = face_index[keep]
    faces = faces[keep]
    valid = valid[keep]
    node_index = np.unique(faces[valid])
    remap = np.full(len(node_x), -1, dtype=np.int64)
    remap[node_index] = np.arange(len(node_index))
    compact = np.where(valid, remap[np.where(valid, faces, 0)], -1)
    return PartitionGrid(
        path=path,
        partition_id=part,
        node_x=node_x[node_index],
        node_y=node_y[node_index],
        faces=compact,
        face_index=face_index,
        node_index=node_index,
        ghost_filtered=domains is not None,
    )


def read_times(path):
    """Return ``(values, labels)`` of the MAP time axis (empty when static)."""
    netcdf = _netcdf()
    with netcdf.Dataset(str(path), "r") as dataset:
        layout = _layout(dataset)
        if not layout.time_var:
            return np.asarray([]), []
        variable = dataset.variables[layout.time_var]
        values = np.asarray(np.ma.filled(variable[:], np.nan), dtype=float)
        units = getattr(variable, "units", "")
        calendar = getattr(variable, "calendar", "standard")
    labels = None
    if units:
        try:
            dates = netcdf.num2date(values, units, calendar)
            labels = [date.strftime("%Y-%m-%d %H:%M:%S") for date in np.atleast_1d(dates)]
        except (ValueError, TypeError, AttributeError):
            labels = None
    if labels is None:
        labels = [f"{value:g}" for value in values]
    return values, labels


def read_crs_info(path):
    """Return ``(epsg, wkt)`` from grid-mapping attributes; EPSG codes <= 0 are ignored."""
    netcdf = _netcdf()
    epsg = None
    wkt = ""
    with netcdf.Dataset(str(path), "r") as dataset:
        for variable in dataset.variables.values():
            attributes = set(variable.ncattrs())
            for name in ("EPSG_code", "epsg", "EPSG"):
                if epsg is None and name in attributes:
                    numbers = re.findall(r"\d+", str(variable.getncattr(name)))
                    code = int(numbers[-1]) if numbers else 0
                    epsg = code if code > 0 else None
            for name in ("crs_wkt", "wkt", "spatial_ref"):
                if not wkt and name in attributes:
                    wkt = str(variable.getncattr(name)).strip()
    return epsg, wkt


def _string_labels(variable):
    netcdf = _netcdf()
    data = variable[:]
    if variable.dtype.kind in ("S", "U") and variable.ndim == 2:
        texts = netcdf.chartostring(np.ma.filled(data, b""))
    else:
        texts = np.ma.filled(data, "")
    return [str(text).strip() for text in np.atleast_1d(texts)]


def _dimension_labels(dataset, dim, size):
    for variable in dataset.variables.values():
        if not variable.dimensions or variable.dimensions[0] != dim:
            continue
        is_char = variable.dtype.kind in ("S", "U") or variable.dtype is str
        if is_char and variable.ndim in (1, 2):
            try:
                labels = _string_labels(variable)
            except (ValueError, TypeError):
                continue
            if len(labels) == size and any(labels):
                return [f"{index + 1}: {label}" for index, label in enumerate(labels)]
    pretty = "Layer" if "layer" in dim.lower() else "Index"
    return [f"{pretty} {index + 1}" for index in range(size)]


def _variable_label(name, variable):
    long_name = str(getattr(variable, "long_name", "") or "").strip()
    units = str(getattr(variable, "units", "") or "").strip()
    text = f"{name} - {long_name}" if long_name else name
    return f"{text} [{units}]" if units and units != "-" else text


def _plain_2d(dataset, layout, name):
    """Whether ``name`` is a face variable with dimensions (time, face) in any order."""
    if not name:
        return False
    return set(dataset.variables[name].dimensions) == {layout.time_dim, layout.face_dim}


def list_variables(path, sediment_records=None):
    """Return the plottable face/node variables plus available derived variables."""
    netcdf = _netcdf()
    entries = []
    with netcdf.Dataset(str(path), "r") as dataset:
        layout = _layout(dataset)
        for name, variable in dataset.variables.items():
            if name in layout.excluded or variable.dtype.kind not in "fiu":
                continue
            dims = variable.dimensions
            spatial = [dim for dim in dims if dim in (layout.face_dim, layout.node_dim)]
            if len(spatial) != 1:
                continue
            if name.lower().endswith(("_bnd", "_x", "_y")) and layout.time_dim not in dims:
                continue
            location = POINT if layout.geometry == "points" else (
                FACE if spatial[0] == layout.face_dim else NODE
            )
            extra = [
                ExtraDimension(dim, len(dataset.dimensions[dim]), _dimension_labels(dataset, dim, len(dataset.dimensions[dim])))
                for dim in dims
                if dim not in (layout.time_dim, spatial[0])
            ]
            if any(dimension.size == 0 for dimension in extra):
                continue
            entries.append(
                VariableEntry(
                    key=name,
                    label=_variable_label(name, variable),
                    location=location,
                    has_time=layout.time_dim in dims,
                    extra_dims=extra,
                    units=str(getattr(variable, "units", "") or ""),
                )
            )

        names = _derived_inputs(dataset, layout)
        derived_location = POINT if layout.geometry == "points" else FACE
        derived = []
        if names["depth"] and (names["ucmag"] or (names["ucx"] and names["ucy"])):
            derived.append(VariableEntry(FROUDE_KEY, "Froude number (derived) [-]", derived_location, True, derived=True, units="-"))
        if not names["ucmag"] and names["ucx"] and names["ucy"]:
            derived.append(
                VariableEntry(VELOCITY_MAGNITUDE_KEY, "Velocity magnitude (derived) [m/s]", derived_location, True, derived=True, units="m s-1")
            )
        if names["mor_bl"]:
            derived.append(
                VariableEntry(BED_LEVEL_CHANGE_KEY, "Cumulative bed level change (derived) [m]", derived_location, True, derived=True, units="m")
            )
        if _shear_stress_available(names):
            for index, record in enumerate(_valid_theta_records(sediment_records)):
                derived.append(
                    VariableEntry(
                        f"{THETA_KEY_PREFIX}{index}",
                        f"Non-dimensional bed shear stress - {record.name} (derived) [-]",
                        derived_location,
                        True,
                        derived=True,
                        units="-",
                    )
                )
        if names["q1"] and names["edge_nodes"]:
            derived.append(
                VariableEntry(STREAM_FUNCTION_KEY, "Streamfunction (derived) [m3/s]", NODE, True, derived=True, units="m3 s-1")
            )
    entries.sort(key=lambda entry: entry.key.lower())
    return derived + entries


def _valid_theta_records(records):
    valid = []
    for record in records or []:
        try:
            diameter = float(record.characteristic_diameter)
            density = float(record.dry_density)
        except (AttributeError, TypeError, ValueError):
            continue
        if not np.isfinite(diameter) or diameter <= 0:
            continue
        if not np.isfinite(density) or density <= WATER_DENSITY:
            continue
        name = str(getattr(record, "name", "fraction") or "fraction")
        valid.append(SimpleNamespace(name=name, diameter=diameter, density=density))
    return valid


def _shear_stress_available(names):
    return bool(names["taus"] or (names["chezy"] and (names["ucmag"] or (names["ucx"] and names["ucy"]))))


def _derived_inputs(dataset, layout):
    def face_var(*suffixes):
        name = _find_variable(dataset, *suffixes)
        return name if layout.time_dim and _plain_2d(dataset, layout, name) else None

    q1 = _find_variable(dataset, "q1")
    edge_nodes = _find_variable(dataset, "edge_nodes")
    if q1 and (
        not layout.time_dim
        or len(dataset.variables[q1].dimensions) != 2
        or layout.time_dim not in dataset.variables[q1].dimensions
    ):
        q1 = None
    if edge_nodes and edge_nodes.lower().startswith("mesh1d"):
        edge_nodes = None
    return {
        "depth": face_var("waterdepth"),
        "taus": face_var("taus"),
        "chezy": face_var("czs"),
        "ucmag": face_var("ucmag"),
        "ucx": face_var("ucx"),
        "ucy": face_var("ucy"),
        "mor_bl": face_var("mor_bl"),
        "q1": q1,
        "edge_nodes": edge_nodes,
    }


def _read_hyperslab(
    dataset,
    layout,
    name,
    time_index,
    extra_indices,
    spatial_dim,
    spatial_index=None,
):
    variable = dataset.variables[name]
    extra_indices = list(extra_indices or [])
    index = []
    for dim in variable.dimensions:
        if dim == spatial_dim:
            index.append(slice(None) if spatial_index is None else int(spatial_index))
        elif dim == layout.time_dim:
            index.append(time_index if isinstance(time_index, slice) else int(time_index))
        else:
            if not extra_indices:
                raise LargeMapError(f"No index selected for dimension '{dim}' of {name}")
            index.append(int(extra_indices.pop(0)))
    values = variable[tuple(index)]
    return np.asarray(np.ma.filled(np.ma.asarray(values, dtype=float), np.nan), dtype=float).reshape(-1)


def read_slice(grid, entry, time_index=0, extra_indices=None, sediment_records=None):
    """Read one plotted slice of ``entry`` for ``grid`` (owned faces / used nodes)."""
    if entry.key == STREAM_FUNCTION_KEY:
        raise LargeMapError("Use StreamFunctionGraph for the streamfunction")
    netcdf = _netcdf()
    with netcdf.Dataset(grid.path, "r") as dataset:
        layout = _layout(dataset)
        if not entry.derived:
            if entry.key not in dataset.variables:
                raise LargeMapError(f"{os.path.basename(grid.path)} has no variable '{entry.key}'")
            spatial_dim = layout.face_dim if entry.location in (FACE, POINT) else layout.node_dim
            values = _read_hyperslab(dataset, layout, entry.key, time_index, extra_indices, spatial_dim)
        else:
            values = _derived_slice(dataset, layout, entry.key, time_index, sediment_records)
    index = grid.face_index if entry.location == FACE else grid.node_index
    return values[index]


def read_point_series(grid, entry, spatial_index, extra_indices=None, sediment_records=None):
    """Read one node/face value for every time without loading spatial slices."""
    if not entry.has_time:
        raise LargeMapError(f"Variable '{entry.label}' has no time dimension")
    if entry.key == STREAM_FUNCTION_KEY:
        raise LargeMapError("Use StreamFunctionGraph for the streamfunction")

    netcdf = _netcdf()
    with netcdf.Dataset(grid.path, "r") as dataset:
        layout = _layout(dataset)
        if not layout.time_dim:
            raise LargeMapError(f"{os.path.basename(grid.path)} has no time dimension")
        spatial_dim = layout.face_dim if entry.location in (FACE, POINT) else layout.node_dim
        if spatial_index < 0 or spatial_index >= len(dataset.dimensions[spatial_dim]):
            raise LargeMapError(f"Spatial index {spatial_index} is outside {spatial_dim}")

        if not entry.derived:
            if entry.key not in dataset.variables:
                raise LargeMapError(f"{os.path.basename(grid.path)} has no variable '{entry.key}'")
            values = _read_hyperslab(
                dataset,
                layout,
                entry.key,
                slice(None),
                extra_indices,
                spatial_dim,
                spatial_index,
            )
        else:
            values = _derived_point_series(
                dataset,
                layout,
                entry.key,
                spatial_index,
                sediment_records,
            )
    return np.asarray(values, dtype=float).reshape(-1)


def _derived_point_series(dataset, layout, key, spatial_index, sediment_records=None):
    names = _derived_inputs(dataset, layout)

    def face_series(name):
        return _read_hyperslab(
            dataset,
            layout,
            name,
            slice(None),
            None,
            layout.face_dim,
            spatial_index,
        )

    def velocity_series():
        if names["ucmag"]:
            return face_series(names["ucmag"])
        return np.hypot(face_series(names["ucx"]), face_series(names["ucy"]))

    if key.startswith(THETA_KEY_PREFIX):
        try:
            fraction_index = int(key[len(THETA_KEY_PREFIX):])
        except ValueError as exc:
            raise LargeMapError(f"Invalid theta variable '{key}'") from exc
        records = _valid_theta_records(sediment_records)
        if fraction_index < 0 or fraction_index >= len(records):
            raise LargeMapError("Sediment data is unavailable for this theta variable")
        if not _shear_stress_available(names):
            raise LargeMapError(
                f"{os.path.basename(dataset.filepath())} lacks bed shear stress or velocity/Chezy inputs"
            )
        if names["taus"]:
            shear = face_series(names["taus"])
        else:
            with np.errstate(divide="ignore", invalid="ignore"):
                shear = (
                    WATER_DENSITY
                    * velocity_series() ** 2
                    * GRAVITY
                    / face_series(names["chezy"]) ** 2
                )
        record = records[fraction_index]
        delta = (record.density - WATER_DENSITY) / WATER_DENSITY
        with np.errstate(divide="ignore", invalid="ignore"):
            return shear / (WATER_DENSITY * GRAVITY * delta * record.diameter)

    if key == FROUDE_KEY and names["depth"] and (
        names["ucmag"] or (names["ucx"] and names["ucy"])
    ):
        depth = face_series(names["depth"])
        velocity = velocity_series()
        return compute_froude_number(depth[:, np.newaxis], velocity[:, np.newaxis])[:, 0]
    if key == VELOCITY_MAGNITUDE_KEY and names["ucx"] and names["ucy"]:
        return velocity_series()
    if key == BED_LEVEL_CHANGE_KEY and names["mor_bl"]:
        current = face_series(names["mor_bl"])
        initial = _read_hyperslab(
            dataset,
            layout,
            names["mor_bl"],
            0,
            None,
            layout.face_dim,
            spatial_index,
        )
        return current - initial[0]
    raise LargeMapError(
        f"{os.path.basename(dataset.filepath())} lacks the inputs for this derived variable"
    )


def _derived_slice(dataset, layout, key, time_index, sediment_records=None):
    names = _derived_inputs(dataset, layout)

    def face(name):
        return _read_hyperslab(dataset, layout, name, time_index, None, layout.face_dim)

    def velocity():
        if names["ucmag"]:
            return face(names["ucmag"])
        return np.hypot(face(names["ucx"]), face(names["ucy"]))

    if key.startswith(THETA_KEY_PREFIX):
        try:
            fraction_index = int(key[len(THETA_KEY_PREFIX):])
        except ValueError as exc:
            raise LargeMapError(f"Invalid theta variable '{key}'") from exc
        records = _valid_theta_records(sediment_records)
        if fraction_index >= len(records):
            raise LargeMapError("Sediment data is unavailable for this theta variable")
        if not _shear_stress_available(names):
            raise LargeMapError(f"{os.path.basename(dataset.filepath())} lacks bed shear stress or velocity/Chezy inputs")
        if names["taus"]:
            shear = face(names["taus"])
        else:
            with np.errstate(divide="ignore", invalid="ignore"):
                shear = WATER_DENSITY * velocity() ** 2 * GRAVITY / face(names["chezy"]) ** 2
        record = records[fraction_index]
        delta = (record.density - WATER_DENSITY) / WATER_DENSITY
        with np.errstate(divide="ignore", invalid="ignore"):
            return shear / (WATER_DENSITY * GRAVITY * delta * record.diameter)

    if key == FROUDE_KEY and names["depth"] and (names["ucmag"] or (names["ucx"] and names["ucy"])):
        return compute_froude_number(face(names["depth"])[np.newaxis, :], velocity()[np.newaxis, :])[0]
    if key == VELOCITY_MAGNITUDE_KEY and names["ucx"] and names["ucy"]:
        return velocity()
    if key == BED_LEVEL_CHANGE_KEY and names["mor_bl"]:
        return face(names["mor_bl"]) - _read_hyperslab(dataset, layout, names["mor_bl"], 0, None, layout.face_dim)
    raise LargeMapError(f"{os.path.basename(dataset.filepath())} lacks the inputs for this derived variable")


class StreamFunctionGraph:
    """Cross-partition edge graph for an in-memory streamfunction per time step.

    Nodes of all partitions are matched by coordinates; only partition-owned
    edges are used, duplicated interface edges are kept once.
    """

    def __init__(self, grids):
        netcdf = _netcdf()
        self._grids = list(grids)
        coordinates = []
        local_edges = []
        owned_masks = []
        self._q1_names = []
        for grid in self._grids:
            with netcdf.Dataset(grid.path, "r") as dataset:
                layout = _layout(dataset)
                names = _derived_inputs(dataset, layout)
                if not names["q1"] or not names["edge_nodes"]:
                    raise LargeMapError(f"{os.path.basename(grid.path)} lacks q1 discharge or edge connectivity")
                edge_variable = dataset.variables[names["edge_nodes"]]
                edge_dim = layout.edge_dim if layout.edge_dim in edge_variable.dimensions else next(
                    dim for dim in edge_variable.dimensions if dim in dataset.variables[names["q1"]].dimensions
                )
                edges = _connectivity(edge_variable, edge_dim)
                owned = np.all(edges >= 0, axis=1)
                if grid.partition_id is not None:
                    edge_faces_name = _find_variable(dataset, "edge_faces")
                    domains = _domain_values(dataset, layout.face_dim)
                    if edge_faces_name and domains is not None:
                        edge_faces = _connectivity(dataset.variables[edge_faces_name], edge_dim)
                        valid = (edge_faces >= 0) & (edge_faces < len(domains))
                        face_domain = np.where(valid, domains[np.where(valid, edge_faces, 0)], -1)
                        owned &= np.any(face_domain == grid.partition_id, axis=1)
                x = np.asarray(np.ma.filled(dataset.variables[layout.node_x][:], np.nan), dtype=float)
                y = np.asarray(np.ma.filled(dataset.variables[layout.node_y][:], np.nan), dtype=float)
                self._q1_names.append(names["q1"])
            coordinates.append(np.column_stack((x, y)))
            local_edges.append(edges)
            owned_masks.append(owned)

        offsets = np.cumsum([0] + [len(item) for item in coordinates])
        stacked = np.round(np.vstack(coordinates), 9)
        _, global_ids = np.unique(stacked, axis=0, return_inverse=True)
        global_ids = np.asarray(global_ids).reshape(-1)
        self._node_count = int(global_ids.max()) + 1 if len(global_ids) else 0
        self._node_maps = [global_ids[offsets[i]:offsets[i + 1]] for i in range(len(self._grids))]

        edge_keys = []
        sources = []
        for part, (edges, owned) in enumerate(zip(local_edges, owned_masks)):
            local_index = np.nonzero(owned)[0]
            mapped = self._node_maps[part][edges[local_index]]
            sign = np.where(mapped[:, 0] <= mapped[:, 1], 1.0, -1.0)
            edge_keys.append(np.sort(mapped, axis=1))
            sources.append((local_index, sign))
        all_keys = np.vstack(edge_keys) if edge_keys else np.empty((0, 2), dtype=np.int64)
        unique_keys, first = np.unique(all_keys, axis=0, return_index=True)
        self._edges = unique_keys
        part_offsets = np.cumsum([0] + [len(keys) for keys in edge_keys])
        self._selections = []
        for part, (local_index, sign) in enumerate(sources):
            in_part = (first >= part_offsets[part]) & (first < part_offsets[part + 1])
            positions = first[in_part] - part_offsets[part]
            self._selections.append((np.nonzero(in_part)[0], local_index[positions], sign[positions]))

    @property
    def node_count(self):
        return self._node_count

    def values_for_time(self, time_index):
        """Return per-partition node values aligned with each grid's ``node_index``."""
        netcdf = _netcdf()
        discharge = np.full(len(self._edges), np.nan)
        for grid, q1_name, (target, local_index, sign) in zip(self._grids, self._q1_names, self._selections):
            with netcdf.Dataset(grid.path, "r") as dataset:
                layout = _layout(dataset)
                variable = dataset.variables[q1_name]
                spatial_dim = next(dim for dim in variable.dimensions if dim != layout.time_dim)
                values = _read_hyperslab(dataset, layout, q1_name, time_index, None, spatial_dim)
            discharge[target] = values[local_index] * sign
        psi = compute_stream_function(discharge[np.newaxis, :], self._edges, self._node_count)[0]
        return [psi[node_map[grid.node_index]] for grid, node_map in zip(self._grids, self._node_maps)]
