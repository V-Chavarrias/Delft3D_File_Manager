from pathlib import Path
import shutil

import numpy as np
import pytest

from Delft3DFileManager.bed_level_interpolator import interpolate_dual_mean


DATA_DIR = Path(__file__).parent.parent / "data"
BED_LEVEL_MESH = DATA_DIR / "bed_level_coverage_mesh.nc"
BED_LEVEL_SOURCE = DATA_DIR / "bed_level_coverage_source.xyz"


def _source_points():
    return np.loadtxt(BED_LEVEL_SOURCE, unpack=True)


def test_dual_mean_preserves_uncovered_node_with_sample_data(tmp_path):
    nc = pytest.importorskip("netCDF4")
    mesh_path = tmp_path / BED_LEVEL_MESH.name
    shutil.copyfile(BED_LEVEL_MESH, mesh_path)
    source_x, source_y, source_z = _source_points()

    updated_count = interpolate_dual_mean(
        str(mesh_path),
        "mesh2d_node_z",
        source_x,
        source_y,
        source_z,
        mesh_epsg=None,
    )

    with nc.Dataset(mesh_path) as dataset:
        node_z = dataset["mesh2d_node_z"][:]

    assert updated_count == 1
    assert node_z[3] == pytest.approx(-103.0)


def test_dual_mean_uses_closest_value_for_uncovered_node(tmp_path):
    nc = pytest.importorskip("netCDF4")
    mesh_path = tmp_path / BED_LEVEL_MESH.name
    shutil.copyfile(BED_LEVEL_MESH, mesh_path)
    source_x, source_y, source_z = _source_points()

    interpolate_dual_mean(
        str(mesh_path),
        "mesh2d_node_z",
        source_x,
        source_y,
        source_z,
        mesh_epsg=None,
        outside_policy="closest",
    )

    with nc.Dataset(mesh_path) as dataset:
        node_z = dataset["mesh2d_node_z"][:]

    assert node_z[3] == pytest.approx(14.4)


def test_dual_mean_extrapolates_uncovered_node_from_sample_plane(tmp_path):
    nc = pytest.importorskip("netCDF4")
    mesh_path = tmp_path / BED_LEVEL_MESH.name
    shutil.copyfile(BED_LEVEL_MESH, mesh_path)
    source_x, source_y, source_z = _source_points()

    interpolate_dual_mean(
        str(mesh_path),
        "mesh2d_node_z",
        source_x,
        source_y,
        source_z,
        mesh_epsg=None,
        outside_policy="extrapolate",
    )

    with nc.Dataset(mesh_path) as dataset:
        node_z = dataset["mesh2d_node_z"][:]

    assert node_z[3] == pytest.approx(13.0)