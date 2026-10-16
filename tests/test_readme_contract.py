import re

from tests.readme_helpers import README_PATH, extract_h2_sections


REQUIRED_HEADINGS = {
    "About",
    "Compatibility",
    "Features",
    "Menu Structure",
    "File Import",
    "Export",
    "Plugin Installation",
    "Development",
    "License",
}


def _readme_sections():
    return extract_h2_sections(README_PATH.read_text(encoding="utf-8"))


def test_readme_has_required_headings():
    sections = _readme_sections()
    missing = REQUIRED_HEADINGS.difference(sections)
    assert not missing, f"README is missing required sections: {sorted(missing)}"


def test_readme_documents_supported_qgis_versions():
    compatibility = _readme_sections().get("Compatibility", "")
    assert re.search(r"\bQGIS\s+3\.x\b", compatibility)
    assert re.search(r"\bQGIS\s+4\.x\b", compatibility)


def test_readme_documents_runtime_dependency_names(plugin):
    dependency_section = _readme_sections().get("Install Python Dependencies", "")
    declaration = re.search(
        r"(?im)^\s*.*allowlisted packages are\s*(.+)$", dependency_section
    )
    assert declaration, "README must identify the allowlisted Python packages"

    documented_packages = set(re.findall(r"`([^`]+)`", declaration.group(1)))
    assert documented_packages == set(plugin._required_packages)


def test_readme_documents_current_point_cloud_export_behavior():
    point_cloud_section = _readme_sections().get("Point Cloud Export (`.xyn`)", "")
    assert re.search(
        r"\bmain\s+\*\*Export\*\*\s+menu action\b", point_cloud_section
    )
    assert re.search(r"generic\s+QGIS\s+point\s+layer", point_cloud_section, re.I)
    assert "ASCII `.xyn`" in point_cloud_section


def test_readme_documents_test_and_build_commands():
    development = _readme_sections().get("Development", "")
    code_blocks = re.findall(r"(?ms)^```[^\r\n]*\r?\n(.*?)^```", development)
    documented_commands = "\n".join(code_blocks)

    assert re.search(r"(?m)^python -m pytest\s*$", documented_commands)
    assert re.search(r"(?m)^python \.\\build_plugin\.py\s*$", documented_commands)
