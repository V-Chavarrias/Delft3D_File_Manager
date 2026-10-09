from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from Delft3DFileManager import mesh_polyline_capture
from Delft3DFileManager.mesh_edge_paths import build_edge_graph


@pytest.fixture
def capture_tool(monkeypatch):
    monkeypatch.setattr(
        mesh_polyline_capture,
        "_qt_enum",
        lambda container, group_name, name: {
            "RightButton": 2,
            "LeftButton": 1,
            "Key_Backspace": 8,
            "Key_Escape": 27,
        }[name],
    )
    monkeypatch.setattr(mesh_polyline_capture, "QgsRubberBand", lambda *args: MagicMock())
    graph = build_edge_graph(
        [(0, 0), (1, 0), (1, 1), (0, 1), (3, 0), (4, 0), (3, 1)],
        [(0, 1, 2, 3), (4, 5, 6)],
        lambda first, second: 1.0,
    )
    tool = mesh_polyline_capture.MeshPolylineCaptureTool(
        canvas=MagicMock(),
        graph=graph,
        spatial_index=MagicMock(),
        display_coordinates={node: object() for node in graph.neighbors},
        previous_map_tool=None,
        source_layer_id="mesh",
        on_finished=MagicMock(return_value=True),
        on_closed=MagicMock(),
        on_warning=MagicMock(),
    )
    tool._nearest_corner = MagicMock(return_value=2)
    return tool


def _event(button=1):
    return SimpleNamespace(
        button=lambda: button,
        pos=lambda: SimpleNamespace(x=lambda: 12, y=lambda: 34),
    )


def test_canvas_release_converts_event_position_with_canvas_transform(monkeypatch):
    monkeypatch.setattr(
        mesh_polyline_capture,
        "_qt_enum",
        lambda container, group_name, name: {
            "RightButton": 2,
            "LeftButton": 1,
        }[name],
    )

    canvas = MagicMock(spec=["getCoordinateTransform"])
    transform = canvas.getCoordinateTransform.return_value
    map_point = object()
    transform.toMapCoordinates.return_value = map_point
    tool = mesh_polyline_capture.MeshPolylineCaptureTool(
        canvas=canvas,
        graph=MagicMock(),
        spatial_index=MagicMock(),
        display_coordinates={},
        previous_map_tool=None,
        source_layer_id="mesh",
        on_finished=MagicMock(),
        on_closed=MagicMock(),
        on_warning=MagicMock(),
    )
    tool._nearest_corner = MagicMock(return_value=4)
    tool.draft.append_corner = MagicMock()
    tool._redraw = MagicMock()
    event = SimpleNamespace(
        button=lambda: 1,
        pos=lambda: SimpleNamespace(x=lambda: 12, y=lambda: 34),
    )

    tool.canvasReleaseEvent(event)

    tool.on_warning.assert_not_called()
    transform.toMapCoordinates.assert_called_once_with(12, 34)
    tool._nearest_corner.assert_called_once_with(map_point)
    tool.draft.append_corner.assert_called_once_with(4)


@pytest.mark.parametrize("qt6", [False, True])
def test_hover_draws_full_route_without_committing(capture_tool, qt6):
    tool = capture_tool
    tool.draft.append_corner(0)
    event = _event()
    if qt6:
        point = event.pos()
        event.position = lambda: SimpleNamespace(toPoint=lambda: point)
        event.pos = MagicMock(side_effect=AssertionError("Qt6 should use position()"))

    tool.canvasMoveEvent(event)

    tool.canvas.getCoordinateTransform().toMapCoordinates.assert_called_once_with(12, 34)
    assert tool.draft.nodes == [0]
    assert not tool.draft.can_finish()
    assert tool.preview_band.addPoint.call_args_list == [
        call(tool.display_coordinates[node], False) for node in (0, 1, 2)
    ]
    tool.preview_band.show.assert_called_once()
    tool.preview_band.update.assert_called_once()
    tool.line_band.addPoint.assert_not_called()
    tool.on_warning.assert_not_called()
    tool.draft.undo()
    assert tool.draft.nodes == []


def test_hover_waits_for_first_click(capture_tool):
    capture_tool.canvasMoveEvent(_event())
    capture_tool._nearest_corner.assert_not_called()


def test_hover_caches_route_until_snapped_corner_changes(capture_tool, monkeypatch):
    tool = capture_tool
    tool.draft.append_corner(0)
    shortest_path = MagicMock(wraps=tool.graph.shortest_path)
    monkeypatch.setattr(type(tool.graph), "shortest_path", shortest_path)

    tool.canvasMoveEvent(_event())
    tool.canvasMoveEvent(_event())
    shortest_path.assert_called_once_with(0, 2)
    tool._nearest_corner.return_value = 3
    tool.canvasMoveEvent(_event())
    assert shortest_path.call_args_list == [call(0, 2), call(0, 3)]


def test_unreachable_hover_clears_previous_preview_and_warns_once(capture_tool):
    tool = capture_tool
    tool.draft.append_corner(0)
    tool.canvasMoveEvent(_event())
    tool.preview_band.reset.reset_mock()
    tool.preview_band.addPoint.reset_mock()
    tool._nearest_corner.return_value = 4

    tool.canvasMoveEvent(_event())
    tool.canvasMoveEvent(_event())

    tool.preview_band.reset.assert_called_once()
    tool.preview_band.addPoint.assert_not_called()
    tool.on_warning.assert_called_once()
    assert "cannot be reached" in tool.on_warning.call_args.args[0]
    assert tool.draft.nodes == [0]


def test_hovering_current_endpoint_clears_preview(capture_tool):
    tool = capture_tool
    tool.draft.append_corner(0)
    tool.canvasMoveEvent(_event())
    tool.preview_band.reset.reset_mock()
    tool.preview_band.addPoint.reset_mock()
    tool._nearest_corner.return_value = 0

    tool.canvasMoveEvent(_event())

    tool.preview_band.reset.assert_called_once()
    tool.preview_band.addPoint.assert_not_called()
    tool.on_warning.assert_not_called()


def test_click_commits_preview_and_undo_invalidates_cached_route(capture_tool):
    tool = capture_tool
    tool.draft.append_corner(0)
    tool.canvasMoveEvent(_event())
    tool.canvasReleaseEvent(_event())

    assert tool.draft.nodes == [0, 1, 2]
    assert tool._preview_key is None
    assert tool.line_band.addPoint.call_args_list == [
        call(tool.display_coordinates[node], False) for node in (0, 1, 2)
    ]
    tool.line_band.update.assert_called_once()
    tool.canvasMoveEvent(_event())
    tool.keyPressEvent(SimpleNamespace(key=lambda: 8))
    assert tool.draft.nodes == [0]
    assert tool._preview_key is None
    tool.preview_band.addPoint.reset_mock()
    tool.canvasMoveEvent(_event())
    assert tool.preview_band.addPoint.call_count == 3
    tool.keyPressEvent(SimpleNamespace(key=lambda: 8))
    assert tool.draft.nodes == []
    assert tool._preview_key is None


@pytest.mark.parametrize("close_action", ["finish", "cancel", "remove_layer", "deactivate"])
def test_closing_capture_clears_preview_and_never_saves_hover(capture_tool, close_action):
    tool = capture_tool
    tool.draft.append_corner(0)
    tool.draft.append_corner(1)
    tool.canvasMoveEvent(_event())
    tool.preview_band.reset.reset_mock()
    if close_action == "remove_layer":
        tool._layers_will_be_removed(["mesh"])
    else:
        getattr(tool, close_action)()

    tool.preview_band.reset.assert_called_once()
    assert tool._preview_key is None
    if close_action == "finish":
        tool.on_finished.assert_called_once_with((0, 1))
    else:
        tool.on_finished.assert_not_called()


def test_hover_coordinate_error_clears_preview_and_reports_failure(capture_tool):
    tool = capture_tool
    tool.draft.append_corner(0)
    tool.canvasMoveEvent(_event())
    tool.canvas.getCoordinateTransform.side_effect = RuntimeError("transform unavailable")
    tool.preview_band.reset.reset_mock()

    tool.canvasMoveEvent(_event())

    tool.preview_band.reset.assert_called_once()
    assert tool._preview_key is None
    tool.on_warning.assert_called_once_with(
        "Could not preview the mesh route: transform unavailable"
    )
    assert tool.draft.nodes == [0]
