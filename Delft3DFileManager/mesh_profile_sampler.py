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
    coordinates = [(float(x), float(y)) for x, y in zip(node_x, node_y)]
    line = [(float(point[0]), float(point[1])) for point in (polyline or [])]
    if len(coordinates) == 0 or len(line) < 2:
        return []

    chainage = cumulative_chainage(line)
    edges = set()
    for face in face_nodes:
        valid_nodes = [int(index) for index in face if 0 <= int(index) < len(coordinates)]
        if len(valid_nodes) < 2:
            continue
        for start, end in zip(valid_nodes, valid_nodes[1:] + valid_nodes[:1]):
            if start != end:
                edges.add(tuple(sorted((start, end))))

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

    def cross(first, second):
        return first[0] * second[1] - first[1] * second[0]

    def subtract(first, second):
        return (first[0] - second[0], first[1] - second[1])

    hits = []
    # A line can be entirely contained in one face. Such a valid slice has no
    # edge crossing, so retain its clicked vertices as exact face samples.
    for line_index, point in enumerate(line):
        if any(point_inside_face(point, face) for face in face_nodes):
            hits.append((chainage[line_index], point))

    for line_index, (line_start, line_end) in enumerate(zip(line, line[1:])):
        direction = subtract(line_end, line_start)
        segment_length = math.hypot(direction[0], direction[1])
        if segment_length <= tolerance:
            continue
        for edge_start_index, edge_end_index in edges:
            edge_start = coordinates[edge_start_index]
            edge_end = coordinates[edge_end_index]
            edge_direction = subtract(edge_end, edge_start)
            denominator = cross(direction, edge_direction)
            offset = subtract(edge_start, line_start)

            if abs(denominator) <= tolerance:
                if abs(cross(offset, direction)) > tolerance:
                    continue
                for candidate in (edge_start, edge_end):
                    parameter = ((candidate[0] - line_start[0]) * direction[0] +
                                 (candidate[1] - line_start[1]) * direction[1]) / (segment_length ** 2)
                    if -tolerance <= parameter <= 1.0 + tolerance:
                        parameter = min(1.0, max(0.0, parameter))
                        hits.append((chainage[line_index] + parameter * segment_length, candidate))
                continue

            line_parameter = cross(offset, edge_direction) / denominator
            edge_parameter = cross(offset, direction) / denominator
            if (-tolerance <= line_parameter <= 1.0 + tolerance and
                    -tolerance <= edge_parameter <= 1.0 + tolerance):
                line_parameter = min(1.0, max(0.0, line_parameter))
                hits.append((
                    chainage[line_index] + line_parameter * segment_length,
                    (
                        line_start[0] + line_parameter * direction[0],
                        line_start[1] + line_parameter * direction[1],
                    ),
                ))

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