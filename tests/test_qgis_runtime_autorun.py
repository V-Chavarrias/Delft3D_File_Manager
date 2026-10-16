import os
import re

import pytest

from tests.qgis_runtime_runner import find_qgis4_python, run_qgis4_tests


pytestmark = [pytest.mark.qgis_runtime, pytest.mark.e2e]


def test_installed_qgis4_runtime_runs_automatically(pytestconfig):
    launcher, diagnostics = find_qgis4_python()
    if launcher is None:
        details = "; ".join(diagnostics[-3:])
        message = "QGIS 4 Python runtime was not found"
        if details:
            message = f"{message}: {details}"
        if os.environ.get("QGIS_PYTHON"):
            pytest.fail(f"{message}; QGIS_PYTHON was explicitly configured")
        pytest.skip(f"{message}; set QGIS_PYTHON to a QGIS-aware Python launcher")

    result = run_qgis4_tests(
        launcher,
        pytestconfig.getoption("markexpr"),
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    assert result.returncode == 0, (
        f"QGIS 4 tests failed using {launcher} "
        f"(exit code {result.returncode}):\n{output}"
    )
    assert re.search(r"\b[1-9]\d* passed\b", output), (
        f"QGIS 4 test process completed without reporting a passing test:\n{output}"
    )
