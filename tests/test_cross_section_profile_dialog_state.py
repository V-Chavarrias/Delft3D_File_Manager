from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.dialog_test_support import (
    FakeTextControl,
    load_dialog_module,
    new_widget_instance,
)
from tests.fixtures_qgis_fakes import FakeComboBox


pytestmark = pytest.mark.unit


@pytest.fixture
def dialog_module(monkeypatch):
    return load_dialog_module(
        monkeypatch,
        "cross_section_profile_dialog.py",
        "cross_section_profile_dialog_state",
    )


def _dialog(module):
    dialog = new_widget_instance(module.CrossSectionProfileDialog)
    dialog._limit_edits = {
        "y_min": FakeTextControl(),
        "y_max": FakeTextControl(),
        "c_min": FakeTextControl(),
        "c_max": FakeTextControl(),
    }
    dialog._substrate_fraction_combo = FakeComboBox()
    dialog._ve_spin = MagicMock()
    dialog._meta_label = FakeTextControl()
    dialog._message_label = FakeTextControl()
    dialog._chart_widget = MagicMock()
    dialog._profiles = []
    dialog._on_draw_requested = None
    dialog._on_selected_lines_requested = None
    dialog._on_substrate_patch_requested = None
    return dialog


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.25", 1.25),
        (" -2 ", -2.0),
        ("", None),
        ("not a number", None),
        ("nan", None),
        ("inf", None),
        ("-inf", None),
    ],
)
def test_limit_parser_accepts_only_finite_numbers(dialog_module, text, expected):
    assert dialog_module.CrossSectionProfileDialog._parse_limit(text) == expected


def test_apply_limits_parses_each_axis_and_color_bound(dialog_module):
    dialog = _dialog(dialog_module)
    dialog._limit_edits["y_min"].setText("1.5")
    dialog._limit_edits["y_max"].setText("")
    dialog._limit_edits["c_min"].setText("-2")
    dialog._limit_edits["c_max"].setText("3.5")
    dialog._chart_widget = SimpleNamespace(
        set_y_limits=MagicMock(),
        set_color_limits=MagicMock(),
    )

    dialog._apply_limits()

    dialog._chart_widget.set_y_limits.assert_called_once_with(1.5, None)
    dialog._chart_widget.set_color_limits.assert_called_once_with(-2.0, 3.5)


def test_substrate_options_preserve_selection_and_emit_mode(dialog_module):
    dialog = _dialog(dialog_module)
    dialog._substrate_fraction_combo.addItem(
        "D50",
        ("volume", "D50"),
    )
    changed = MagicMock()
    dialog.set_mesh_handlers(on_substrate_patch_requested=changed)
    dialog.set_substrate_fractions(["D16", "D50"])

    assert dialog._substrate_fraction_combo.count() == 5
    assert dialog._substrate_fraction_combo.currentData() == ("volume", "D50")
    assert dialog.substrate_patch_mode() == "volume"
    assert dialog.substrate_fraction() == "D50"

    dialog._substrate_selection_changed()
    changed.assert_called_once_with("volume", "D50")

    dialog._substrate_fraction_combo.setCurrentIndex(2)
    assert dialog.substrate_patch_mode() == "geometric"
    assert dialog.substrate_fraction() == ""

    dialog._substrate_fraction_combo.clear()
    dialog._substrate_fraction_combo.addItem("Unexpected", "unexpected")
    assert dialog.substrate_patch_mode() == ""
    assert dialog.substrate_fraction() == ""


def test_profile_setters_update_metadata_chart_and_messages(dialog_module):
    dialog = _dialog(dialog_module)
    points = [(0, 1), (1, 2)]
    metadata = {
        "id": 12,
        "definitionId": "cross-section-a",
        "def_type": "yz",
        "x_axis_label": "chainage",
        "y_axis_label": "elevation",
    }

    dialog.set_profile(points, "Profile A", metadata, "Ready")

    assert dialog._profiles == [
        {"points": points, "label": "Profile A", "metadata": metadata}
    ]
    dialog._chart_widget.set_axis_labels.assert_called_once_with(
        "chainage",
        "elevation",
    )
    dialog._chart_widget.set_profiles.assert_called_once_with(
        dialog._profiles,
        "Ready",
    )
    assert dialog._meta_label.text() == (
        "id: 12 | definitionId: cross-section-a | def_type: yz"
    )
    assert dialog._message_label.text() == "Ready"

    dialog.add_profile([(2, 3)], "Profile B")
    assert [profile["label"] for profile in dialog._profiles] == [
        "Profile A",
        "Profile B",
    ]
    dialog.clear_profiles()
    assert dialog._profiles == []
    assert dialog._message_label.text() == ""


def test_profile_setter_falls_back_to_single_profile_chart(dialog_module):
    dialog = _dialog(dialog_module)
    chart = SimpleNamespace(
        set_axis_labels=MagicMock(),
        set_profile=MagicMock(),
    )
    dialog._chart_widget = chart

    dialog.set_profiles(
        [{"points": [(0, 2)], "label": "Profile"}],
        "Profile",
        {},
        "No additional profiles",
    )

    chart.set_axis_labels.assert_called_once_with("y [m]", "z [m]")
    chart.set_profile.assert_called_once_with([(0, 2)], "No additional profiles")
    assert dialog._meta_label.text() == ""


def test_substrate_patch_reset_and_status_message(dialog_module):
    dialog = _dialog(dialog_module)
    dialog._meta_label.setText("metadata")
    dialog.set_substrate_patch(
        [0, 1],
        [0, 1],
        [[1]],
        "Substrate",
        {
            "x_axis_label": "distance",
            "y_axis_label": "bed level",
            "colorbar_label": "fraction",
        },
        "Patch ready",
    )

    dialog._chart_widget.set_axis_labels.assert_called_once_with(
        "distance",
        "bed level",
    )
    dialog._chart_widget.set_patch.assert_called_once_with(
        [0, 1],
        [0, 1],
        [[1]],
        "fraction",
    )
    assert dialog._meta_label.text() == ""
    assert dialog._message_label.text() == "Patch ready"

    dialog.set_status_message(None)
    assert dialog._message_label.text() == ""
    dialog._on_reset()
    dialog._ve_spin.setValue.assert_called_once_with(1.0)
    assert all(edit.text() == "" for edit in dialog._limit_edits.values())
    dialog._chart_widget.reset_view.assert_called_once_with()


def test_mesh_capture_handlers_are_optional(dialog_module):
    dialog = _dialog(dialog_module)
    draw = MagicMock()
    selected_lines = MagicMock()
    substrate = MagicMock()
    draw_point = MagicMock()
    selected_points = MagicMock()
    dialog.set_mesh_handlers(
        draw,
        selected_lines,
        substrate,
        on_point_draw_requested=draw_point,
        on_selected_points_requested=selected_points,
    )

    dialog._draw_profile()
    dialog._add_selected_lines()
    dialog._substrate_selection_changed()
    dialog._draw_point_series()
    dialog._add_selected_points()

    draw.assert_called_once_with()
    selected_lines.assert_called_once_with()
    substrate.assert_called_once_with("", "")
    draw_point.assert_called_once_with()
    selected_points.assert_called_once_with()

    dialog.set_mesh_handlers()
    dialog._draw_profile()
    dialog._add_selected_lines()
    dialog._substrate_selection_changed()
    dialog._draw_point_series()
    dialog._add_selected_points()
