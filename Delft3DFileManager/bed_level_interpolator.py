# -*- coding: utf-8 -*-
"""
Bed level interpolation engine for UGRID mesh files.

Supports reading source elevation from:
  - NetCDF files (regular lat/lon or projected grids)
  - NumPy arrays (x, y, z) – used internally when called from the dialog

Available interpolation methods
---------------------------------
dual_mean
    For each mesh node the bed level is set to the arithmetic mean of all
    source points that fall inside the node's *dual grid cell*.  The dual
    cell is approximated by the polygon formed by the centroids of the mesh
    faces that share the node, sorted by angle around the node.  If no
    source point falls inside the dual cell, the original value in the mesh
    file is left unchanged.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Public registry of available methods
# ---------------------------------------------------------------------------

INTERP_METHODS: Dict[str, str] = {
    "dual_mean": "Mean of points in dual cell",
}


# ---------------------------------------------------------------------------
# UGRID auto-detection helpers
# ---------------------------------------------------------------------------

def auto_detect_mesh_info(nc_dataset) -> dict:
    """Return a dict describing the UGRID topology variables in *nc_dataset*.

    Raises ``ValueError`` if no ``mesh_topology`` variable is found.
    """
    import netCDF4 as nc  # noqa – imported locally so the module loads in env without it

    # Find topology variable (cf_role = mesh_topology)
    topology_var = None
    for vname, v in nc_dataset.variables.items():
        if getattr(v, "cf_role", "") == "mesh_topology":
            topology_var = vname
            break
    if topology_var is None:
        raise ValueError(
            "No UGRID mesh topology variable found (cf_role=mesh_topology). "
            "Is this a valid UGRID NetCDF file?"
        )

    topo = nc_dataset[topology_var]
    node_coord_names = getattr(topo, "node_coordinates", "").split()
    face_conn_var = getattr(topo, "face_node_connectivity", "mesh2d_face_nodes")

    # Classify node coordinate variables as x/y
    node_x_var = node_y_var = None
    for vname in node_coord_names:
        if vname not in nc_dataset.variables:
            continue
        v = nc_dataset[vname]
        sn = getattr(v, "standard_name", "").lower()
        ln = getattr(v, "long_name", "").lower()
        if "x" in sn or "longitude" in sn or "_x" in vname.lower() or "x-coord" in ln:
            node_x_var = vname
        else:
            node_y_var = vname

    # Fallback: look for obvious names when topology attrs are missing
    node_x_var = node_x_var or _first_match(nc_dataset, ["mesh2d_node_x", "node_x"])
    node_y_var = node_y_var or _first_match(nc_dataset, ["mesh2d_node_y", "node_y"])

    # Face centroid variables  (single dimension over faces)
    face_x_var = face_y_var = None
    face_dim = None
    if face_conn_var in nc_dataset.variables:
        face_dim = nc_dataset[face_conn_var].dimensions[0]
    for vname, v in nc_dataset.variables.items():
        if len(v.dimensions) != 1 or (face_dim and face_dim not in v.dimensions):
            continue
        sn = getattr(v, "standard_name", "").lower()
        ln = getattr(v, "long_name", "").lower()
        if "x" in sn or "projection_x" in sn or ("characteristic" in ln and " x-coord" in ln):
            face_x_var = face_x_var or vname
        elif "y" in sn or "projection_y" in sn or ("characteristic" in ln and " y-coord" in ln):
            face_y_var = face_y_var or vname

    face_x_var = face_x_var or _first_match(nc_dataset, ["mesh2d_face_x", "face_x"])
    face_y_var = face_y_var or _first_match(nc_dataset, ["mesh2d_face_y", "face_y"])

    # Node z variables: location=node or name contains "node_z"
    node_z_vars: List[str] = []
    for vname, v in nc_dataset.variables.items():
        if getattr(v, "location", "") == "node" and vname not in (node_x_var, node_y_var):
            node_z_vars.append(vname)
    for vname in nc_dataset.variables:
        if "node_z" in vname and vname not in node_z_vars:
            node_z_vars.append(vname)

    return {
        "topology_var": topology_var,
        "node_x_var": node_x_var or "mesh2d_node_x",
        "node_y_var": node_y_var or "mesh2d_node_y",
        "node_z_vars": node_z_vars,
        "face_conn_var": face_conn_var or "mesh2d_face_nodes",
        "face_x_var": face_x_var or "mesh2d_face_x",
        "face_y_var": face_y_var or "mesh2d_face_y",
    }


def _first_match(nc_dataset, candidates):
    for name in candidates:
        if name in nc_dataset.variables:
            return name
    return None


def list_source_variables(source_path: str) -> Tuple[List[str], dict]:
    """Inspect *source_path* and return ``(variable_names, coord_info)``.

    ``coord_info`` has keys ``lat_var``, ``lon_var``, ``is_geographic``.
    """
    import netCDF4 as nc

    ds = nc.Dataset(source_path, "r")
    try:
        lat_var = lon_var = None
        for vname, v in ds.variables.items():
            sn = getattr(v, "standard_name", "").lower()
            if sn == "latitude":
                lat_var = vname
            elif sn == "longitude":
                lon_var = vname

        data_vars = [
            vname
            for vname, v in ds.variables.items()
            if vname not in (lat_var, lon_var) and len(v.dimensions) >= 2
        ]
        coord_info = {
            "lat_var": lat_var,
            "lon_var": lon_var,
            "is_geographic": lat_var is not None and lon_var is not None,
        }
    finally:
        ds.close()

    return data_vars, coord_info


# ---------------------------------------------------------------------------
# Source data loading
# ---------------------------------------------------------------------------

def load_source_netcdf(
    source_path: str,
    var_name: str,
    bbox_source_crs: Optional[Tuple[float, float, float, float]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load (x, y, z) arrays from a NetCDF source file.

    Parameters
    ----------
    source_path:
        Path to the source NetCDF file.
    var_name:
        Name of the elevation variable to read.
    bbox_source_crs:
        Optional bounding box ``(xmin, ymin, xmax, ymax)`` *in source CRS*
        used to extract only the relevant subset of the grid.

    Returns
    -------
    source_x, source_y, source_z : 1-D numpy arrays (NaN values excluded).
    """
    import netCDF4 as nc

    ds = nc.Dataset(source_path, "r")
    try:
        # Find coordinate arrays
        lat = lon = None
        for vname, v in ds.variables.items():
            sn = getattr(v, "standard_name", "").lower()
            if sn == "latitude":
                lat = np.asarray(v[:], dtype=float)
            elif sn == "longitude":
                lon = np.asarray(v[:], dtype=float)

        if lat is None or lon is None:
            raise ValueError(
                f"Could not find latitude/longitude variables in {source_path}"
            )

        v_data = ds[var_name]

        # Determine row/col subset if a bbox is given (in lat/lon)
        if bbox_source_crs is not None:
            xmin, ymin, xmax, ymax = bbox_source_crs
            r0, r1, c0, c1 = _grid_subset_indices(lat, lon, ymin, ymax, xmin, xmax)
        else:
            r0, r1 = 0, len(lat)
            c0, c1 = 0, len(lon)

        # Read subset – read once and handle masked arrays and fill values
        raw = v_data[r0:r1, c0:c1]
        if isinstance(raw, np.ma.MaskedArray):
            z_sub = raw.filled(np.nan).astype(float)
        else:
            z_sub = np.asarray(raw, dtype=float)
            fill = getattr(v_data, "_FillValue", None)
            if fill is not None:
                try:
                    fv = float(fill)
                    if np.isfinite(fv):
                        z_sub[z_sub == fv] = np.nan
                except (TypeError, ValueError):
                    pass

        lat_sub = lat[r0:r1]
        lon_sub = lon[c0:c1]
        lon_grid, lat_grid = np.meshgrid(lon_sub, lat_sub)

    finally:
        ds.close()

    sx = lon_grid.ravel()
    sy = lat_grid.ravel()
    sz = z_sub.ravel()

    valid = np.isfinite(sz)
    return sx[valid], sy[valid], sz[valid]


def _grid_subset_indices(lat, lon, lat_min, lat_max, lon_min, lon_max):
    """Return (row_start, row_end, col_start, col_end) for grid subsetting."""
    # Handle descending latitude
    if lat[0] > lat[-1]:
        r1 = int(np.searchsorted(-lat, -lat_min, side="left")) + 1
        r0 = max(0, int(np.searchsorted(-lat, -lat_max, side="right")) - 1)
    else:
        r0 = max(0, int(np.searchsorted(lat, lat_min, side="left")) - 1)
        r1 = min(len(lat), int(np.searchsorted(lat, lat_max, side="right")) + 1)

    c0 = max(0, int(np.searchsorted(lon, lon_min, side="left")) - 1)
    c1 = min(len(lon), int(np.searchsorted(lon, lon_max, side="right")) + 1)
    return r0, r1, c0, c1


# ---------------------------------------------------------------------------
# Dual-grid construction
# ---------------------------------------------------------------------------

def build_dual_polygons(
    node_x: np.ndarray,
    node_y: np.ndarray,
    face_nodes: np.ndarray,
    face_x: np.ndarray,
    face_y: np.ndarray,
) -> Tuple[list, dict]:
    """Build the dual grid polygon for every mesh node.

    The dual polygon around node *n* is formed by the centroids of all mesh
    faces that contain *n*, sorted by angle around *n*.  This gives a
    Voronoi-like cell for each node.

    Parameters
    ----------
    node_x, node_y : 1-D arrays of node coordinates.
    face_nodes : 2-D int array ``(nFaces, maxNodes)``, **0-indexed**.
        Fill/invalid entries should be negative.
    face_x, face_y : 1-D arrays of face centroid coordinates.

    Returns
    -------
    dual_polys : list of ``(poly_x, poly_y)`` tuples or ``None``.
        Index *i* gives the dual polygon for node *i*.  ``None`` means fewer
        than 2 adjacent faces were found (degenerate node).
    node_to_faces : dict mapping node index → list of adjacent face indices.
    """
    nNodes = len(node_x)
    nFaces, maxFN = face_nodes.shape

    # Build adjacency in one pass
    node_to_faces: Dict[int, List[int]] = defaultdict(list)
    for fi in range(nFaces):
        for nj in range(maxFN):
            ni = int(face_nodes[fi, nj])
            if 0 <= ni < nNodes:
                node_to_faces[ni].append(fi)

    dual_polys: list = []
    for ni in range(nNodes):
        face_idx = node_to_faces.get(ni)
        if not face_idx or len(face_idx) < 2:
            dual_polys.append(None)
            continue

        fi_arr = np.asarray(face_idx, dtype=int)
        cx = face_x[fi_arr]
        cy = face_y[fi_arr]

        # Sort face centroids by angle around the node
        angles = np.arctan2(cy - node_y[ni], cx - node_x[ni])
        order = np.argsort(angles)
        dual_polys.append((cx[order], cy[order]))

    return dual_polys, node_to_faces


# ---------------------------------------------------------------------------
# Point-in-polygon (vectorised ray-casting, no external deps)
# ---------------------------------------------------------------------------

def _points_in_polygon(
    poly_x: np.ndarray,
    poly_y: np.ndarray,
    px: np.ndarray,
    py: np.ndarray,
) -> np.ndarray:
    """Return a boolean array ``True`` where ``(px[i], py[i])`` is inside
    the (closed) polygon defined by ``(poly_x, poly_y)``.

    Uses the ray-casting algorithm.  The outer loop iterates over the
    (typically small) number of polygon edges while the inner workload over
    ``len(px)`` candidate points is fully vectorised with NumPy.
    """
    n = len(poly_x)
    inside = np.zeros(len(px), dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = poly_x[i], poly_y[i]
        xj, yj = poly_x[j], poly_y[j]
        dy = yj - yi
        if abs(dy) > 1e-14:  # skip horizontal edges
            cross_cond = (yi > py) != (yj > py)
            x_intersect = (xj - xi) * (py - yi) / dy + xi
            inside ^= cross_cond & (px < x_intersect)
        j = i
    return inside


# ---------------------------------------------------------------------------
# Main interpolation entry point
# ---------------------------------------------------------------------------

def interpolate_dual_mean(
    mesh_path: str,
    z_var_name: str,
    source_x: np.ndarray,
    source_y: np.ndarray,
    source_z: np.ndarray,
    mesh_epsg: Optional[int],
    source_epsg: int = 4326,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Write bed level to a UGRID mesh using the *mean of points in dual cell*
    interpolation method.

    Only nodes whose dual cell contains at least one source point are updated;
    all other nodes retain their existing values in the mesh file.

    Parameters
    ----------
    mesh_path:
        Path to the UGRID NetCDF file (opened read/write).
    z_var_name:
        Name of the node elevation variable to write (e.g. ``mesh2d_node_z``).
    source_x, source_y, source_z:
        Source elevation data as 1-D arrays.  May contain NaN/Inf which are
        removed automatically.  Coordinates are in *source_epsg*.
    mesh_epsg:
        EPSG code of the mesh coordinate system.  ``None`` means "same as
        source; skip transformation".
    source_epsg:
        EPSG code of the source coordinate system (default 4326 for lat/lon).
    progress_callback:
        Optional ``callable(current_node: int, total_nodes: int)`` invoked
        after every node is processed.

    Returns
    -------
    int
        Number of mesh nodes whose elevation was updated.
    """
    import netCDF4 as nc

    # ------------------------------------------------------------------
    # 1. Open mesh file
    # ------------------------------------------------------------------
    ds = nc.Dataset(mesh_path, "r+")
    try:
        mesh_info = auto_detect_mesh_info(ds)

        node_x = np.asarray(ds[mesh_info["node_x_var"]][:], dtype=float)
        node_y = np.asarray(ds[mesh_info["node_y_var"]][:], dtype=float)
        face_x = np.asarray(ds[mesh_info["face_x_var"]][:], dtype=float)
        face_y = np.asarray(ds[mesh_info["face_y_var"]][:], dtype=float)

        fn_var = ds[mesh_info["face_conn_var"]]
        fn_raw = fn_var[:]
        if isinstance(fn_raw, np.ma.MaskedArray):
            fn_data = fn_raw.filled(-999).astype(int)
        else:
            fn_data = np.asarray(fn_raw, dtype=int)

        start_index = int(getattr(fn_var, "start_index", 1))
        face_nodes = fn_data - start_index  # convert to 0-indexed; fills become ≤ -1

        nNodes = len(node_x)

        # ------------------------------------------------------------------
        # 2. CRS transformation: source → mesh CRS
        # ------------------------------------------------------------------
        sx = source_x.copy()
        sy = source_y.copy()
        sz = source_z.copy()

        do_transform = (
            mesh_epsg is not None
            and source_epsg is not None
            and mesh_epsg != source_epsg
        )
        if do_transform:
            try:
                from pyproj import Transformer

                transformer = Transformer.from_crs(
                    f"EPSG:{source_epsg}",
                    f"EPSG:{mesh_epsg}",
                    always_xy=True,
                )
                sx, sy = transformer.transform(sx, sy)
            except Exception as exc:
                raise RuntimeError(
                    f"CRS transformation (EPSG:{source_epsg} → EPSG:{mesh_epsg}) "
                    f"failed: {exc}\n"
                    "Install the 'pyproj' package or ensure both CRS use the same "
                    "coordinate units."
                )

        # ------------------------------------------------------------------
        # 3. Filter: remove NaN/Inf and points outside the mesh bounding box
        # ------------------------------------------------------------------
        valid = np.isfinite(sx) & np.isfinite(sy) & np.isfinite(sz)
        sx, sy, sz = sx[valid], sy[valid], sz[valid]
        if len(sz) == 0:
            return 0

        buf = max((node_x.max() - node_x.min()) * 0.005, 1.0)
        in_bbox = (
            (sx >= node_x.min() - buf)
            & (sx <= node_x.max() + buf)
            & (sy >= node_y.min() - buf)
            & (sy <= node_y.max() + buf)
        )
        sx, sy, sz = sx[in_bbox], sy[in_bbox], sz[in_bbox]
        if len(sz) == 0:
            return 0

        # ------------------------------------------------------------------
        # 4. Optional KD-tree spatial index on filtered source points
        # ------------------------------------------------------------------
        use_kdtree = False
        try:
            from scipy.spatial import cKDTree

            source_tree = cKDTree(np.column_stack([sx, sy]))
            use_kdtree = True
        except ImportError:
            pass

        # ------------------------------------------------------------------
        # 5. Build dual polygons
        # ------------------------------------------------------------------
        dual_polys, _ = build_dual_polygons(
            node_x, node_y, face_nodes, face_x, face_y
        )

        # ------------------------------------------------------------------
        # 6. Read current z values
        # ------------------------------------------------------------------
        z_var = ds[z_var_name]
        current_z = np.asarray(z_var[:], dtype=float)

        # ------------------------------------------------------------------
        # 7. Main interpolation loop
        # ------------------------------------------------------------------
        updated_count = 0

        for ni in range(nNodes):
            poly = dual_polys[ni]
            if poly is None:
                if progress_callback:
                    progress_callback(ni + 1, nNodes)
                continue

            poly_x, poly_y = poly

            # Find candidate source points
            if use_kdtree:
                # Radius = max distance from node to any face centroid
                r = float(
                    max(
                        np.max(np.hypot(poly_x - node_x[ni], poly_y - node_y[ni])),
                        1.0,
                    )
                )
                candidates = source_tree.query_ball_point(
                    [node_x[ni], node_y[ni]], r
                )
                if not candidates:
                    if progress_callback:
                        progress_callback(ni + 1, nNodes)
                    continue
                cx_cand = sx[candidates]
                cy_cand = sy[candidates]
                cz_cand = sz[candidates]
            else:
                # Bounding box filter
                xbb_min, xbb_max = poly_x.min(), poly_x.max()
                ybb_min, ybb_max = poly_y.min(), poly_y.max()
                mask = (
                    (sx >= xbb_min)
                    & (sx <= xbb_max)
                    & (sy >= ybb_min)
                    & (sy <= ybb_max)
                )
                if not mask.any():
                    if progress_callback:
                        progress_callback(ni + 1, nNodes)
                    continue
                cx_cand = sx[mask]
                cy_cand = sy[mask]
                cz_cand = sz[mask]

            # Point-in-polygon test
            inside = _points_in_polygon(poly_x, poly_y, cx_cand, cy_cand)
            if inside.any():
                current_z[ni] = float(np.mean(cz_cand[inside]))
                updated_count += 1

            if progress_callback:
                progress_callback(ni + 1, nNodes)

        # ------------------------------------------------------------------
        # 8. Write updated values back to disk
        # ------------------------------------------------------------------
        z_var[:] = current_z
        ds.sync()

    finally:
        ds.close()

    return updated_count


# ---------------------------------------------------------------------------
# Dispatcher (makes it easy to add future methods)
# ---------------------------------------------------------------------------

def run_interpolation(
    method: str,
    mesh_path: str,
    z_var_name: str,
    source_x: np.ndarray,
    source_y: np.ndarray,
    source_z: np.ndarray,
    mesh_epsg: Optional[int],
    source_epsg: int = 4326,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Dispatch to the requested interpolation routine and return update count."""
    if method == "dual_mean":
        return interpolate_dual_mean(
            mesh_path,
            z_var_name,
            source_x,
            source_y,
            source_z,
            mesh_epsg,
            source_epsg,
            progress_callback,
        )
    raise ValueError(f"Unknown interpolation method: '{method}'")
