from unittest.mock import MagicMock

import numpy as np
import pytest
from netCDF4 import Dataset

from Delft3DFileManager.m2d_cell_vector import (
    M2D_CELL_VECTOR_DESCRIPTION,
    M2DCellVectorError,
    create_m2d_cell_vector_sidecar,
    is_m2d_cell_vector_file,
)


def _write_cell_values(path, values=(1.5, 2.5)):
    with Dataset(str(path), "w") as dataset:
        dataset.description = M2D_CELL_VECTOR_DESCRIPTION
        dataset.createDimension("n", len(values))
        variable = dataset.createVariable("data", "f8", ("n",))
        variable.long_name = "bed level"
        variable.units = "m"
        variable[:] = values


def _write_grid(path, face_count=2):
    with Dataset(str(path), "w") as dataset:
        dataset.Conventions = "CF-1.8 UGRID-1.0"
        dataset.createDimension("mesh2d_nNodes", face_count + 2)
        dataset.createDimension("mesh2d_nEdges", face_count + 2)
        dataset.createDimension("mesh2d_nFaces", face_count)
        dataset.createDimension("mesh2d_nMax_face_nodes", 3)
        dataset.createDimension("Two", 2)

        topology = dataset.createVariable("mesh2d", "i4")
        topology.cf_role = "mesh_topology"
        topology.topology_dimension = 2
        topology.node_dimension = "mesh2d_nNodes"
        topology.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        topology.edge_dimension = "mesh2d_nEdges"
        topology.edge_node_connectivity = "mesh2d_edge_nodes"
        topology.face_node_connectivity = "mesh2d_face_nodes"
        topology.face_coordinates = "mesh2d_face_x mesh2d_face_y"

        dataset.createVariable("projected_coordinate_system", "i4")
        for axis in ("x", "y"):
            coordinate = dataset.createVariable(
                f"mesh2d_node_{axis}",
                "f8",
                ("mesh2d_nNodes",),
            )
            coordinate.grid_mapping = "projected_coordinate_system"
            coordinate[:] = np.arange(face_count + 2, dtype=float)
            face_coordinate = dataset.createVariable(
                f"mesh2d_face_{axis}",
                "f8",
                ("mesh2d_nFaces",),
            )
            face_coordinate.grid_mapping = "projected_coordinate_system"
            face_coordinate[:] = np.arange(face_count, dtype=float)

        dataset.createVariable(
            "mesh2d_edge_nodes",
            "i4",
            ("mesh2d_nEdges", "Two"),
        )[:] = np.zeros((face_count + 2, 2), dtype=int)
        dataset.createVariable(
            "mesh2d_face_nodes",
            "i4",
            ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"),
            fill_value=-999,
        )[:] = np.tile([0, 1, 2], (face_count, 1))


def test_m2d_detection_requires_exact_description(tmp_path):
    source = tmp_path / "cell_values.nc"
    _write_cell_values(source)

    assert is_m2d_cell_vector_file(source)

    with Dataset(str(source), "a") as dataset:
        dataset.description = f" {M2D_CELL_VECTOR_DESCRIPTION}"

    assert not is_m2d_cell_vector_file(source)


def test_create_m2d_sidecar_copies_grid_topology_and_face_data(tmp_path):
    data_path = tmp_path / "cell_values.nc"
    grid_path = tmp_path / "grid.nc"
    output_path = tmp_path / "cell_values_mesh.nc"
    _write_cell_values(data_path)
    _write_grid(grid_path)

    result = create_m2d_cell_vector_sidecar(
        data_path,
        grid_path,
        output_path=output_path,
        expected_face_count=2,
    )

    assert result == str(output_path.resolve())
    with Dataset(result) as dataset:
        assert dataset.variables["mesh2d"].cf_role == "mesh_topology"
        assert dataset.variables["mesh2d"].face_dimension == "mesh2d_nFaces"
        assert (
            dataset.variables["mesh2d"].max_face_nodes_dimension
            == "mesh2d_nMax_face_nodes"
        )
        assert dataset.variables["mesh2d_face_nodes"].shape == (2, 3)
        assert dataset.variables["projected_coordinate_system"] is not None
        values = dataset.variables["data"]
        assert values.dimensions == ("mesh2d_nFaces",)
        assert values.mesh == "mesh2d"
        assert values.location == "face"
        assert values.coordinates == "mesh2d_face_x mesh2d_face_y"
        assert values.long_name == "bed level"
        assert values.units == "m"
        np.testing.assert_allclose(values[:], [1.5, 2.5])


def test_create_m2d_sidecar_rejects_value_face_count_mismatch(tmp_path):
    data_path = tmp_path / "cell_values.nc"
    grid_path = tmp_path / "grid.nc"
    output_path = tmp_path / "mismatch.nc"
    _write_cell_values(data_path)
    _write_grid(grid_path, face_count=3)

    with pytest.raises(M2DCellVectorError, match="2 cell values.*3 faces"):
        create_m2d_cell_vector_sidecar(data_path, grid_path, output_path=output_path)

    assert not output_path.exists()


def test_create_m2d_sidecar_checks_active_layer_face_count(tmp_path):
    data_path = tmp_path / "cell_values.nc"
    grid_path = tmp_path / "grid.nc"
    _write_cell_values(data_path)
    _write_grid(grid_path)

    with pytest.raises(M2DCellVectorError, match="active mesh layer has 3 faces"):
        create_m2d_cell_vector_sidecar(
            data_path,
            grid_path,
            expected_face_count=3,
        )


def test_create_m2d_sidecar_rejects_non_1d_data(tmp_path):
    data_path = tmp_path / "cell_values.nc"
    grid_path = tmp_path / "grid.nc"
    with Dataset(str(data_path), "w") as dataset:
        dataset.description = M2D_CELL_VECTOR_DESCRIPTION
        dataset.createDimension("rows", 1)
        dataset.createDimension("columns", 2)
        dataset.createVariable("data", "f8", ("rows", "columns"))[:] = [[1.5, 2.5]]
    _write_grid(grid_path)

    with pytest.raises(M2DCellVectorError, match="one-dimensional numeric"):
        create_m2d_cell_vector_sidecar(data_path, grid_path)


def test_load_m2d_cell_vector_file_renders_scalar_group_on_active_mesh(
    plugin,
    tmp_path,
):
    source = tmp_path / "cell_values.nc"
    grid = tmp_path / "grid.nc"
    _write_cell_values(source)
    _write_grid(grid)

    active_layer = MagicMock()
    active_layer.isValid.return_value = True
    active_layer.meshFaceCount.return_value = 2
    active_layer.customProperty.return_value = str(grid)
    active_layer.name.return_value = "active grid"
    grid_crs = MagicMock()
    grid_crs.isValid.return_value = True
    active_layer.crs.return_value = grid_crs
    plugin.iface.activeLayer.return_value = active_layer
    plugin._is_mesh_layer = MagicMock(return_value=True)
    plugin._read_epsg_from_nc = MagicMock(return_value=None)

    renderer_settings = MagicMock()
    result_layer = MagicMock()
    result_layer.dataProvider.return_value.datasetGroupCount.return_value = 1
    result_layer.rendererSettings.return_value = renderer_settings
    plugin._load_mesh2d_layer = MagicMock(return_value=result_layer)

    loaded = plugin.load_m2d_cell_vector_file(str(source))

    assert loaded is result_layer
    result_layer.setCrs.assert_called_once_with(grid_crs)
    renderer_settings.setActiveScalarDatasetGroup.assert_called_once_with(0)
    result_layer.setRendererSettings.assert_called_once_with(renderer_settings)
    call = plugin._load_mesh2d_layer.call_args
    assert call.args[1] == "cell_values"
    assert call.kwargs["expect_data_variables"] is True
    output_path = call.args[0]
    try:
        with Dataset(output_path) as dataset:
            np.testing.assert_allclose(dataset.variables["data"][:], [1.5, 2.5])
    finally:
        import os

        os.remove(output_path)


def test_load_m2d_cell_vector_file_warns_when_face_counts_differ(
    plugin,
    tmp_path,
):
    source = tmp_path / "cell_values.nc"
    grid = tmp_path / "grid.nc"
    _write_cell_values(source)
    _write_grid(grid)

    active_layer = MagicMock()
    active_layer.isValid.return_value = True
    active_layer.meshFaceCount.return_value = 3
    active_layer.customProperty.return_value = str(grid)
    active_layer.name.return_value = "active grid"
    plugin.iface.activeLayer.return_value = active_layer
    plugin._is_mesh_layer = MagicMock(return_value=True)
    plugin._read_epsg_from_nc = MagicMock(return_value=28992)
    plugin._load_mesh2d_layer = MagicMock()

    assert plugin.load_m2d_cell_vector_file(str(source)) is None
    plugin._load_mesh2d_layer.assert_not_called()
    plugin.iface.messageBar().pushWarning.assert_called_once()


def test_load_m2d_cell_vector_file_warns_without_active_mesh(plugin):
    plugin.iface.activeLayer.return_value = None
    plugin._is_mesh_layer = MagicMock(return_value=False)

    assert plugin.load_m2d_cell_vector_file("/fake/cell_values.nc") is None
    plugin.iface.messageBar().pushWarning.assert_called_once()
