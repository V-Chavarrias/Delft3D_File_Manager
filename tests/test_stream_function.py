import numpy as np
import pytest

from Delft3DFileManager.stream_function import (
    compute_stream_function,
    create_stream_function_sidecar,
)


def test_compute_stream_function_matches_oriented_edge_traversal():
    discharge = [[2.0, 3.0, 1.0]]
    edges = [[0, 1], [2, 1], [2, 3]]

    result = compute_stream_function(discharge, edges, 4)

    np.testing.assert_allclose(result, [[1.0, 3.0, 0.0, 1.0]])


def test_compute_stream_function_supports_one_based_transposed_connectivity():
    discharge = [[2.0, 3.0]]
    edges = [[1, 2], [2, 3]]

    result = compute_stream_function(discharge, edges, 3, start_index=1)

    np.testing.assert_allclose(result, [[0.0, 2.0, 5.0]])


def test_compute_stream_function_handles_time_steps_missing_edges_and_components():
    discharge = [[2.0, np.nan, 4.0], [1.0, 3.0, np.nan]]
    edges = [[0, 1], [1, 2], [3, 4]]

    result = compute_stream_function(discharge, edges, 5)

    np.testing.assert_allclose(
        result,
        [[0.0, 2.0, 0.0, 0.0, 4.0], [0.0, 1.0, 4.0, 0.0, 0.0]],
        equal_nan=True,
    )


def _write_map_output(path, node_x, node_y, edges, faces, q1, times):
    netcdf4 = pytest.importorskip("netCDF4")
    with netcdf4.Dataset(path, "w") as dataset:
        dataset.createDimension("mesh2d_nNodes", len(node_x))
        dataset.createDimension("mesh2d_nEdges", len(edges))
        dataset.createDimension("mesh2d_nFaces", len(faces))
        dataset.createDimension("mesh2d_nMax_face_nodes", len(faces[0]))
        dataset.createDimension("Two", 2)
        dataset.createDimension("time", len(times))
        topology = dataset.createVariable("mesh2d", "i4")
        topology.cf_role = "mesh_topology"
        topology.topology_dimension = 2
        topology.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        topology.edge_node_connectivity = "mesh2d_edge_nodes"
        topology.face_node_connectivity = "mesh2d_face_nodes"
        dataset.createVariable("mesh2d_node_x", "f8", ("mesh2d_nNodes",))[:] = node_x
        dataset.createVariable("mesh2d_node_y", "f8", ("mesh2d_nNodes",))[:] = node_y
        edge_variable = dataset.createVariable("mesh2d_edge_nodes", "i4", ("Two", "mesh2d_nEdges"))
        edge_variable[:] = np.asarray(edges).T
        face_variable = dataset.createVariable(
            "mesh2d_face_nodes", "i4", ("mesh2d_nMax_face_nodes", "mesh2d_nFaces")
        )
        face_variable[:] = np.asarray(faces).T
        time = dataset.createVariable("time", "f8", ("time",))
        time.units = "seconds since 2000-01-01"
        time[:] = times
        dataset.createVariable("mesh2d_q1", "f8", ("mesh2d_nEdges", "time"))[:] = np.asarray(q1).T


def test_create_stream_function_sidecar_writes_time_dependent_node_dataset(tmp_path):
    source = tmp_path / "map.nc"
    output = tmp_path / "stream.nc"
    _write_map_output(
        str(source),
        [0, 1, 2],
        [0, 0, 0],
        [[0, 1], [1, 2]],
        [[0, 1, 2]],
        [[2, 3], [4, 5]],
        [10, 20],
    )

    assert create_stream_function_sidecar([str(source)], str(output)) == str(output)

    netcdf4 = pytest.importorskip("netCDF4")
    with netcdf4.Dataset(output) as dataset:
        assert dataset.variables["stream_function"].dimensions == ("time", "mesh2d_nNodes")
        assert dataset.variables["stream_function"].location == "node"
        np.testing.assert_allclose(dataset.variables["stream_function"][:], [[0, 2, 5], [0, 4, 9]])
        np.testing.assert_allclose(dataset.variables["time"][:], [10, 20])
        assert dataset.variables["time"].units == "seconds since 2000-01-01"


def test_create_stream_function_sidecar_merges_duplicate_partition_topology(tmp_path):
    first = tmp_path / "map_0000.nc"
    second = tmp_path / "map_0001.nc"
    _write_map_output(
        str(first),
        [0, 1, 2],
        [0, 0, 0],
        [[0, 1], [1, 2]],
        [[0, 1, 2]],
        [[2], [3]],
        [0],
    )
    _write_map_output(
        str(second),
        [2, 1, 3],
        [0, 0, 0],
        [[0, 1], [1, 2]],
        [[0, 1, 2]],
        [[-3], [4]],
        [0],
    )

    output = tmp_path / "merged_stream.nc"
    create_stream_function_sidecar([str(first), str(second)], str(output))

    netcdf4 = pytest.importorskip("netCDF4")
    with netcdf4.Dataset(output) as dataset:
        assert len(dataset.dimensions["mesh2d_nNodes"]) == 4
        assert len(dataset.dimensions["mesh2d_nEdges"]) == 3
