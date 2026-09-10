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


def test_qt6_event_and_button_enum_helpers(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    class _QEventType:
        MouseButtonDblClick = 123

    class _QEventQt6:
        Type = _QEventType

    class _MouseButtonEnum:
        LeftButton = 1

    class _QtQt6:
        MouseButton = _MouseButtonEnum

    monkeypatch.setattr(plugin_module, "QEvent", _QEventQt6)
    monkeypatch.setattr(plugin_module, "Qt", _QtQt6)

    assert plugin_module._double_click_event_type() == 123
    assert plugin_module._left_mouse_button_value() == 1


def test_qt6_qmessagebox_enum_helpers(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    class _Icon:
        Question = 10

    class _ButtonRole:
        AcceptRole = 20
        ActionRole = 21
        RejectRole = 22

    class _StandardButton:
        Cancel = 30

    class _QMessageBoxQt6:
        Icon = _Icon
        ButtonRole = _ButtonRole
        StandardButton = _StandardButton

    monkeypatch.setattr(plugin_module, "QMessageBox", _QMessageBoxQt6)

    assert plugin_module._qmessagebox_icon_question() == 10
    assert plugin_module._qmessagebox_button_role("AcceptRole") == 20
    assert plugin_module._qmessagebox_button_role("ActionRole") == 21
    assert plugin_module._qmessagebox_button_role("RejectRole") == 22
    assert plugin_module._qmessagebox_standard_button("Cancel") == 30


def test_mesh_properties_dialog_uses_qt6_button_enum(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    class _StandardButton:
        Ok = 1
        Cancel = 2

    class _QDialogButtonBoxQt6:
        StandardButton = _StandardButton

    monkeypatch.setattr(plugin_module, "QDialogButtonBox", _QDialogButtonBoxQt6)

    ok_button = getattr(plugin_module.QDialogButtonBox, "Ok", None) or getattr(
        plugin_module.QDialogButtonBox.StandardButton, "Ok", None
    )
    cancel_button = getattr(plugin_module.QDialogButtonBox, "Cancel", None) or getattr(
        plugin_module.QDialogButtonBox.StandardButton, "Cancel", None
    )

    assert ok_button | cancel_button == 3


def test_mesh_properties_dialog_uses_qt6_dialog_code(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    class _DialogCode:
        Accepted = 1

    class _QDialogQt6:
        DialogCode = _DialogCode

    monkeypatch.setattr(plugin_module, "QDialog", _QDialogQt6)

    accepted = getattr(plugin_module.QDialog, "Accepted", None) or getattr(
        plugin_module.QDialog.DialogCode, "Accepted", None
    )

    assert accepted == 1


def test_dialog_exec_helper_supports_qt6_exec():
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    class _DialogQt6:
        def exec(self):
            return 1

    assert plugin_module._dialog_exec(_DialogQt6()) == 1


def test_no_exec_uses_in_plugin_runtime_modules():
    """Runtime modules should avoid direct exec_ to stay Qt5/Qt6-compatible."""
    violations = []

    for path in PLUGIN_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ".exec_(" in line:
                rel = path.relative_to(PLUGIN_DIR.parent)
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert not violations, "Direct exec_ usage found:\n" + "\n".join(violations)


def test_qt_version_helpers_detect_qt6(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    monkeypatch.setattr(plugin_module, "QT_VERSION_STR", "6.8.2")

    assert plugin_module._qt_major_version() == 6
    assert plugin_module._is_qt6_runtime() is True


def test_qt_version_helpers_handle_unknown(monkeypatch):
    import Delft3DFileManager.Delft3DFileManager as plugin_module

    monkeypatch.setattr(plugin_module, "QT_VERSION_STR", "")

    assert plugin_module._qt_major_version() is None
    assert plugin_module._is_qt6_runtime() is False
