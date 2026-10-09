"""QGIS map tool for capturing a routed polyline on a mesh."""

import math
import sys

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsPointXY, QgsRectangle, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand

from .mesh_edge_paths import MeshPolylineDraft, UnreachableCornerError


def _qt_enum(container, group_name, name):
    value = getattr(container, name, None)
    if value is None:
        group = getattr(container, group_name, None)
        value = getattr(group, name, None)
    return value


class MeshPolylineCaptureTool(QgsMapTool):
    def __init__(
        self,
        canvas,
        graph,
        spatial_index,
        display_coordinates,
        previous_map_tool,
        source_layer_id,
        on_finished,
        on_closed,
        on_warning,
    ):
        super().__init__(canvas)
        self.canvas = canvas
        self.graph = graph
        self.draft = MeshPolylineDraft(graph)
        self.spatial_index = spatial_index
        self.display_coordinates = display_coordinates
        self.previous_map_tool = previous_map_tool
        self.source_layer_id = source_layer_id
        self.on_finished = on_finished
        self.on_closed = on_closed
        self.on_warning = on_warning
        self.line_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.corner_band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self.preview_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.line_band.setColor(QColor(38, 139, 210, 230))
        self.line_band.setWidth(3)
        self.corner_band.setColor(QColor(38, 139, 210, 230))
        self.corner_band.setWidth(6)
        self.preview_band.setColor(QColor(255, 193, 7, 230))
        self.preview_band.setWidth(3)
        self._preview_key = None
        self._cleaning = False

        from qgis.core import QgsProject

        self.project = QgsProject.instance()
        self.project.layersWillBeRemoved.connect(self._layers_will_be_removed)

    def canvasReleaseEvent(self, event):
        button = event.button()
        if button == _qt_enum(Qt, "MouseButton", "RightButton"):
            self.finish()
            return
        if button != _qt_enum(Qt, "MouseButton", "LeftButton"):
            return
        try:
            map_point = self._map_point(event)
            node = self._nearest_corner(map_point)
            self.draft.append_corner(node)
            self._clear_preview()
            self._redraw()
        except UnreachableCornerError as exc:
            self.on_warning(str(exc))
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError) as exc:
            self.on_warning(f"Could not snap to a mesh corner: {exc}")

    def _map_point(self, event):
        event_position = getattr(event, "position", None)
        event_position = event_position() if callable(event_position) else None
        if event_position is None:
            event_position = event.pos()
        else:
            to_point = getattr(event_position, "toPoint", None)
            if callable(to_point):
                event_position = to_point()
        transform = self.canvas.getCoordinateTransform()
        return transform.toMapCoordinates(event_position.x(), event_position.y())

    def canvasMoveEvent(self, event):
        if not self.draft.nodes:
            return
        try:
            node = self._nearest_corner(self._map_point(event))
            key = (self.draft.nodes[-1], node)
            if key == self._preview_key:
                return
            self._clear_preview()
            self._preview_key = key
            if key[0] == node:
                return
            route = self.graph.shortest_path(key[0], node)
            self._draw_band(self.preview_band, QgsWkbTypes.LineGeometry, route)
        except UnreachableCornerError as exc:
            self.on_warning(str(exc))
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError) as exc:
            self._clear_preview()
            self.on_warning(f"Could not preview the mesh route: {exc}")

    def _clear_preview(self):
        self._preview_key = None
        self.preview_band.reset(QgsWkbTypes.LineGeometry)

    def keyPressEvent(self, event):
        key = event.key()
        if key == _qt_enum(Qt, "Key", "Key_Escape"):
            self.cancel()
        elif key == _qt_enum(Qt, "Key", "Key_Backspace"):
            self.draft.undo()
            self._clear_preview()
            self._redraw()

    def deactivate(self):
        if not self._cleaning:
            self._cleanup(restore=False)
            self.on_closed()
        super().deactivate()

    def _nearest_corner(self, point):
        x = float(point.x())
        y = float(point.y())
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Canvas click coordinates must be finite")
        nearest = self.spatial_index.nearestNeighbor(point, 1)
        if not nearest:
            raise ValueError("The active mesh has no corners available for snapping")
        nearest_node = int(nearest[0])
        nearest_point = self.display_coordinates[nearest_node]
        nearest_distance = math.hypot(
            float(nearest_point.x()) - x, float(nearest_point.y()) - y
        )
        epsilon = max(
            1e-12 * max(1.0, nearest_distance),
            8.0 * sys.float_info.epsilon * max(1.0, abs(x), abs(y)),
        )
        candidates = self.spatial_index.intersects(
            QgsRectangle(
                x - nearest_distance - epsilon,
                y - nearest_distance - epsilon,
                x + nearest_distance + epsilon,
                y + nearest_distance + epsilon,
            )
        )
        if nearest_node not in candidates:
            candidates.append(nearest_node)
        distances = []
        for node in candidates:
            node = int(node)
            candidate = self.display_coordinates[node]
            distance = math.hypot(float(candidate.x()) - x, float(candidate.y()) - y)
            if distance <= nearest_distance + epsilon:
                distances.append((distance, node))
        if not distances:
            return nearest_node
        return min(distances, key=lambda item: (item[0], item[1]))[1]

    def _redraw(self):
        self._draw_band(self.line_band, QgsWkbTypes.LineGeometry, self.draft.nodes)
        self._draw_band(self.corner_band, QgsWkbTypes.PointGeometry, self.draft.nodes)

    def _draw_band(self, band, geometry_type, nodes):
        band.reset(geometry_type)
        for node in nodes:
            band.addPoint(self.display_coordinates[node], False)
        if nodes:
            band.updatePosition()
            band.show()
            band.update()

    def finish(self):
        if not self.draft.can_finish():
            self.on_warning("Select at least two distinct mesh corners before finishing.")
            return False
        try:
            if not self.on_finished(tuple(self.draft.nodes)):
                return False
        except (AttributeError, IndexError, RuntimeError, TypeError, ValueError) as exc:
            self.on_warning(f"Could not create the mesh polyline: {exc}")
            return False
        self._cleanup(restore=True)
        self.on_closed()
        return True

    def cancel(self):
        self._cleanup(restore=True)
        self.on_closed()

    def _layers_will_be_removed(self, layer_ids):
        if self.source_layer_id in layer_ids:
            self.on_warning("Mesh layer removed; polyline capture cancelled.")
            self.cancel()

    def _cleanup(self, restore):
        if self._cleaning:
            return
        self._cleaning = True
        try:
            self.project.layersWillBeRemoved.disconnect(self._layers_will_be_removed)
            self._clear_preview()
            self.line_band.reset(QgsWkbTypes.LineGeometry)
            self.corner_band.reset(QgsWkbTypes.PointGeometry)
            if restore and self.canvas.mapTool() is self:
                self.canvas.setMapTool(self.previous_map_tool)
        finally:
            self._cleaning = False
