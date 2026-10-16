import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple


_QGIS_VERSION_PROBE = (
    "from qgis.core import Qgis; print(Qgis.QGIS_VERSION)"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _candidate_launchers() -> List[Path]:
    candidates = []
    configured_python = os.environ.get("QGIS_PYTHON", "").strip().strip('"')
    if configured_python:
        expanded_python = os.path.expandvars(os.path.expanduser(configured_python))
        resolved_python = shutil.which(expanded_python)
        candidates.append(Path(resolved_python or expanded_python))

    qgis_prefix = os.environ.get("QGIS_PREFIX_PATH")
    if qgis_prefix:
        prefix_path = Path(os.path.expandvars(qgis_prefix))
        if prefix_path.name.lower() == "qgis" and prefix_path.parent.name.lower() == "apps":
            candidates.append(prefix_path.parent.parent / "bin" / "python-qgis.bat")

    osgeo4w_roots = [
        os.environ.get("OSGEO4W_ROOT"),
        r"C:\OSGeo4W",
        r"C:\OSGeo4W64",
    ]
    candidates.extend(
        Path(root) / "bin" / "python-qgis.bat"
        for root in osgeo4w_roots
        if root
    )

    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        installation_roots = list(Path(program_files).glob("QGIS*"))
        local_programs = os.environ.get("LOCALAPPDATA")
        if local_programs:
            installation_roots.extend(
                (Path(local_programs) / "Programs").glob("QGIS*")
            )
        candidates.extend(
            root / "bin" / "python-qgis.bat"
            for root in sorted(installation_roots, key=lambda path: path.name, reverse=True)
        )
    else:
        candidates.append(Path("/usr/bin/python3"))

    candidates.append(Path(sys.executable))

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)
    return unique_candidates


def find_qgis4_python() -> Tuple[Optional[Path], List[str]]:
    """Find a Python launcher that can import QGIS 4."""
    diagnostics = []
    for candidate in _candidate_launchers():
        if not candidate.is_file():
            continue
        try:
            result = subprocess.run(
                [str(candidate), "-c", _QGIS_VERSION_PROBE],
                cwd=str(_REPOSITORY_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            diagnostics.append(f"{candidate}: {exc}")
            continue

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            diagnostics.append(
                f"{candidate}: {detail[-1] if detail else 'QGIS import failed'}"
            )
            continue

        version_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        version = version_lines[-1] if version_lines else ""
        if version.startswith("4."):
            return candidate, diagnostics
        diagnostics.append(
            f"{candidate}: found QGIS {version or 'with no version output'}, expected 4.x"
        )

    return None, diagnostics


def run_qgis4_tests(launcher: Path, marker_expression: str):
    """Run the real-QGIS tier in its own process, isolated from unit-test stubs."""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [
            str(launcher),
            "-m",
            "pytest",
            "-q",
            "--confcutdir=tests/integration",
            "tests/integration",
            "-m",
            marker_expression or "qgis_runtime",
        ],
        cwd=str(_REPOSITORY_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
