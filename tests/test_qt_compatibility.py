from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "Delft3DFileManager"


def test_no_direct_pyqt5_imports_in_plugin_runtime_modules():
    """QGIS plugins should import Qt through qgis.PyQt for Qt5/Qt6 compatibility."""
    violations = []

    for path in PLUGIN_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("from PyQt5") or stripped.startswith("import PyQt5"):
                rel = path.relative_to(PLUGIN_DIR.parent)
                violations.append(f"{rel}:{line_no}: {stripped}")

    assert not violations, "Direct PyQt5 imports found:\n" + "\n".join(violations)
