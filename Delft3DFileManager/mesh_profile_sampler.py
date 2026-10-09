"""Pure helpers for sampling scalar mesh datasets along a polyline."""

import math


def cumulative_chainage(points):
    """Return cumulative 2D distances for an iterable of ``(x, y)`` points."""
    points = list(points or [])
    if not points:
        return []

    chainage = [0.0]
    for previous, current in zip(points, points[1:]):
        dx = float(current[0]) - float(previous[0])
        dy = float(current[1]) - float(previous[1])
        chainage.append(chainage[-1] + math.hypot(dx, dy))
    return chainage


def densify_polyline(points, maximum_spacing=None):
    """Insert vertices so no segment exceeds ``maximum_spacing``."""
    points = [(float(point[0]), float(point[1])) for point in (points or [])]
    if len(points) < 2 or maximum_spacing in (None, 0):
        return points

    spacing = float(maximum_spacing)
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("maximum_spacing must be a positive finite number")

    result = [points[0]]
    for start, end in zip(points, points[1:]):
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, int(math.ceil(distance / spacing)))
        for step in range(1, steps + 1):
            fraction = step / steps
            result.append(
                (
                    start[0] + fraction * (end[0] - start[0]),
                    start[1] + fraction * (end[1] - start[1]),
                )
            )
    return result


def mesh_edge_crossings(node_x, node_y, face_nodes, polyline, tolerance=1e-9):
    """Return ``(chainage, (x, y))`` for exact intersections with mesh edges.

    Edges are derived from face connectivity because Delft3D UGRID files may
    omit an explicit edge-connectivity variable. Shared face edges and vertex
    hits are deduplicated, while the returned chainage remains ordered along
    the drawn polyline.
    """
    import numpy as np

    coordinates = [(float(x), float(y)) for x, y in zip(node_x, node_y)]
    line = [(float(point[0]), float(point[1])) for point in (polyline or [])]
    if len(coordinates) == 0 or len(line) < 2:
        return []

    chainage = cumulative_chainage(line)
    faces = np.asarray(face_nodes, dtype=int)
    if faces.ndim != 2 or faces.shape[1] < 2:
        return []
    starts = faces
    ends = np.roll(faces, -1, axis=1)
    valid_edges = (
        (starts >= 0) & (starts < len(coordinates)) &
        (ends >= 0) & (ends < len(coordinates)) &
        (starts != ends)
    )
    edges = np.column_stack((starts[valid_edges], ends[valid_edges]))
    if len(edges) == 0:
        return []
    edges.sort(axis=1)
    edges = np.unique(edges, axis=0)
    coordinate_array = np.asarray(coordinates, dtype=float)
    edge_start = coordinate_array[edges[:, 0]]
    edge_end = coordinate_array[edges[:, 1]]
    edge_direction = edge_end - edge_start

    def point_inside_face(point, face):
        vertices = [coordinates[int(index)] for index in face if 0 <= int(index) < len(coordinates)]
        if len(vertices) < 3:
            return False
        inside = False
        previous = vertices[-1]
        for current in vertices:
            if ((current[1] > point[1]) != (previous[1] > point[1]) and
                    point[0] < (previous[0] - current[0]) * (point[1] - current[1]) /
                    (previous[1] - current[1]) + current[0]):
                inside = not inside
            previous = current
        return inside

    hits = []
    for line_index, (line_start, line_end) in enumerate(zip(line, line[1:])):
        direction = np.asarray(line_end, dtype=float) - np.asarray(line_start, dtype=float)
        segment_length = float(np.hypot(direction[0], direction[1]))
        if segment_length <= tolerance:
            continue

        offset = edge_start - np.asarray(line_start, dtype=float)
        denominator = direction[0] * edge_direction[:, 1] - direction[1] * edge_direction[:, 0]
        nonparallel = np.abs(denominator) > tolerance
        if np.any(nonparallel):
            line_parameter = np.full(len(edges), np.nan, dtype=float)
            edge_parameter = np.full(len(edges), np.nan, dtype=float)
            line_parameter[nonparallel] = (
                edge_direction[nonparallel, 1] * offset[nonparallel, 0] -
                edge_direction[nonparallel, 0] * offset[nonparallel, 1]
            ) / denominator[nonparallel]
            edge_parameter[nonparallel] = (
                direction[1] * offset[nonparallel, 0] -
                direction[0] * offset[nonparallel, 1]
            ) / denominator[nonparallel]
            crossing = (
                nonparallel &
                (line_parameter >= -tolerance) & (line_parameter <= 1.0 + tolerance) &
                (edge_parameter >= -tolerance) & (edge_parameter <= 1.0 + tolerance)
            )
            for parameter in np.clip(line_parameter[crossing], 0.0, 1.0):
                point = np.asarray(line_start, dtype=float) + parameter * direction
                hits.append((chainage[line_index] + parameter * segment_length, tuple(point)))

        parallel = ~nonparallel
        if np.any(parallel):
            collinear = np.abs(offset[parallel, 0] * direction[1] - offset[parallel, 1] * direction[0]) <= tolerance
            parallel_edges = edges[parallel][collinear]
            for candidate_index in parallel_edges.reshape(-1):
                candidate = coordinate_array[int(candidate_index)]
                parameter = float(np.dot(candidate - line_start, direction) / (segment_length ** 2))
                if -tolerance <= parameter <= 1.0 + tolerance:
                    parameter = min(1.0, max(0.0, parameter))
                    point = np.asarray(line_start, dtype=float) + parameter * direction
                    hits.append((chainage[line_index] + parameter * segment_length, tuple(point)))

    if not hits:
        # A line can be entirely contained in one face. Such a valid slice has no
        # edge crossing, so retain its clicked vertices as exact face samples.
        for line_index, point in enumerate(line):
            if any(point_inside_face(point, face) for face in face_nodes):
                hits.append((chainage[line_index], point))

    unique = {}
    for distance, point in hits:
        key = (round(distance, 8), round(point[0], 8), round(point[1], 8))
        unique[key] = (distance, point)
    return [unique[key] for key in sorted(unique, key=lambda item: item[0])]


def _dataset_value(layer, dataset_index, point):
    """Read a QGIS dataset value, accommodating the supported call order."""
    method = getattr(layer, "datasetValue", None)
    if not callable(method):
        return None

    try:
        value = method(dataset_index, point)
    except (TypeError, AttributeError):
        value = method(point, dataset_index)

    if hasattr(value, "scalar") and callable(value.scalar):
        value = value.scalar()
    elif hasattr(value, "value") and callable(value.value):
        value = value.value()
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def sample_partitioned_mesh(layers, points, dataset_index, point_factory=None, maximum_spacing=None):
    """Sample a scalar dataset across owner-masked partition layers.

    The first finite partition value at each chainage wins. Owner-masked
    partitions therefore produce one continuous profile without duplicate
    values at partition boundaries. Missing values are represented by ``None``
    so chart backends can render gaps.
    """
    layers = [layer for layer in (layers or []) if layer is not None]
    sampled_points = densify_polyline(points, maximum_spacing)
    chainage = cumulative_chainage(sampled_points)
    if point_factory is None:
        point_factory = lambda point: point

    profile = []
    for distance, point in zip(chainage, sampled_points):
        value = None
        qgis_point = point_factory(point)
        for layer in layers:
            candidate = _dataset_value(layer, dataset_index, qgis_point)
            if candidate is not None:
                value = candidate
                break
        profile.append((distance, value))
    return profile


def active_scalar_dataset_group(layer):
    """Return the displayed scalar group index, or ``None`` if unavailable."""
    method = getattr(layer, "activeScalarDatasetGroup", None)
    value = None
    if callable(method):
        try:
            value = method()
        except (RuntimeError, TypeError, AttributeError):
            value = None
    if value is None:
        try:
            value = layer.rendererSettings().activeScalarDatasetGroup()
        except (RuntimeError, TypeError, AttributeError):
            return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def dataset_index_for_displayed_scalar(layer):
    """Resolve a QGIS mesh dataset index for the active scalar group.

    QGIS exposes the active group consistently; the active dataset within that
    group is obtained from the layer's time-aware index method when available.
    """
    group_index = active_scalar_dataset_group(layer)
    if group_index is None:
        return None

    for method_name in ("activeScalarDatasetIndex", "activeDatasetIndex"):
        method = getattr(layer, method_name, None)
        if not callable(method):
            continue
        try:
            dataset_index = int(method())
        except (RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if dataset_index >= 0:
            return (group_index, dataset_index)

    return (group_index, 0)