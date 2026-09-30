import numpy as np
from netCDF4 import Dataset

from Delft3DFileManager.froude import compute_froude_number, create_froude_sidecar


def _write_map(path):
    with Dataset(str(path), "w") as dataset:
        dataset.createDimension("time", 2)
        dataset.createDimension("mesh2d_nNodes", 3)
        dataset.createDimension("mesh2d_nEdges", 2)
        dataset.createDimension("mesh2d_nFaces", 1)
        dataset.createDimension("mesh2d_nMax_face_nodes", 3)
        dataset.createDimension("Two", 2)
        dataset.createVariable("mesh2d", "i4")
        dataset.createVariable("mesh2d_node_x", "f8", ("mesh2d_nNodes",))[:] = [0, 1, 0]
        dataset.createVariable("mesh2d_node_y", "f8", ("mesh2d_nNodes",))[:] = [0, 0, 1]
        dataset.createVariable("mesh2d_edge_nodes", "i4", ("mesh2d_nEdges", "Two"))[:] = [[0, 1], [1, 2]]
        dataset.createVariable("mesh2d_face_nodes", "i4", ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"))[:] = [[0, 1, 2]]
        dataset.createVariable("time", "f8", ("time",))[:] = [0, 1]
        dataset.variables["time"].units = "seconds since 2000-01-01"
        dataset.createVariable("mesh2d_waterdepth", "f8", ("time", "mesh2d_nFaces"))[:] = [[4], [1]]
        dataset.createVariable("mesh2d_ucmag", "f8", ("mesh2d_nFaces", "time"))[:] = [[9.81, 9.81]]


def test_compute_froude_number_uses_gravity_9_81():
    np.testing.assert_allclose(compute_froude_number([[4.0]], [[9.81]]), [[1.5660459763]])


def test_create_froude_sidecar_writes_time_face_field(tmp_path):
    source = tmp_path / "map.nc"
    output = tmp_path / "froude.nc"
    _write_map(source)

    assert create_froude_sidecar(source, output) == str(output.resolve())
    with Dataset(str(output)) as dataset:
        variable = dataset.variables["froude_number"]
        assert variable.dimensions == ("time", "mesh2d_nFaces")
        assert variable.location == "face"
        np.testing.assert_allclose(variable[:], [[1.5660459763], [3.1320919527]])