import re

from tests.menu_expectations import SUBMENU_ACTIONS, TOP_LEVEL_MENU_ACTIONS
from tests.readme_helpers import README_PATH, extract_h2_sections


_TOP_LEVEL_ITEM = re.compile(r"^\s*\d+\.\s+\[([^\]]+)\]\([^)]*\)\s*$")
_SUBMENU_ITEM = re.compile(r"^\s+-\s+\[([^\]]+)\]\([^)]*\)\s*$")


def _parse_documented_menu(section):
    top_level = []
    submenus = {}
    current_parent = None

    for line in section.splitlines():
        top_level_match = _TOP_LEVEL_ITEM.match(line)
        if top_level_match:
            current_parent = top_level_match.group(1)
            top_level.append(current_parent)
            continue

        submenu_match = _SUBMENU_ITEM.match(line)
        if submenu_match:
            assert current_parent is not None, "Submenu action has no parent"
            submenus.setdefault(current_parent, []).append(submenu_match.group(1))

    return top_level, submenus


def test_readme_menu_matches_runtime_menu_expectations():
    sections = extract_h2_sections(README_PATH.read_text(encoding="utf-8"))
    menu_section = sections.get("Menu Structure")
    assert menu_section is not None, "README is missing the Menu Structure section"

    documented_top_level, documented_submenus = _parse_documented_menu(menu_section)
    assert documented_top_level == list(TOP_LEVEL_MENU_ACTIONS)
    assert documented_submenus == {
        name: list(actions) for name, actions in SUBMENU_ACTIONS
    }
