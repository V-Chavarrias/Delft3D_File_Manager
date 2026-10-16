import os

import pytest

from tests.fixtures_qgis_mocks import qgis_mocks_installed


def _runtime_unavailable(message):
    if os.environ.get("QGIS_E2E_REQUIRE_RUNTIME") == "1":
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def qgis_application():
    if qgis_mocks_installed():
        _runtime_unavailable(
            "The test process has QGIS stubs; run this test in a separate QGIS "
            "Python process."
        )

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from qgis.core import QgsApplication
    except ImportError as exc:
        _runtime_unavailable(f"Real QGIS runtime is unavailable: {exc}")

    prefix_path = os.environ.get("QGIS_PREFIX_PATH")
    if prefix_path:
        QgsApplication.setPrefixPath(prefix_path, True)

    application = QgsApplication.instance()
    owns_application = application is None
    if owns_application:
        application = QgsApplication([], True)
        application.initQgis()

    try:
        yield application
    finally:
        if owns_application:
            application.exitQgis()
