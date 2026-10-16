import numpy as np
import pytest
from types import SimpleNamespace

netCDF4 = pytest.importorskip("netCDF4")

from Delft3DFileManager import large_map_reader as reader

NX, NY = 4, 2  # faces per row / rows
TIMES = [0.0, 3600.0, 7200.0]


def _psi(x, y, t):
    return x * x + 2.0 * y + 0.5 * t * x * y


def _global_grid():
    xs, ys = np.meshgrid(np.arange(NX + 1, dtype=float), np.arange(NY + 1, dtype=float))
    node_x = xs.ravel()
    node_y = ys.ravel()
    faces = []
    for j in range(NY):
        for i in range(NX):
            n0 = j * (NX + 1) + i
            faces.append([n0, n0 + 1, n0 + NX + 2, n0 + NX + 1])
    return node_x, node_y, np.asarray(faces)


def _write_partition(path, part, local_faces, owner, reverse_edges=False):
    node_x, node_y, faces = _global_grid()
    sub = faces[local_faces]
    used = np.unique(sub)
    remap = {int(node): index for index, node in enumerate(used)}
    local = np.vectorize(remap.get)(sub)
    edges = {}
    edge_faces = {}
    for face_number, row in enumerate(local):
        for k in range(4):
            a, b = int(row[k]), int(row[(k + 1) % 4])
            key = (min(a, b), max(a, b))
            if key not in edges:
                edges[key] = (b, a) if reverse_edges else (a, b)
                edge_faces[key] = []
            edge_faces[key].append(face_number)
    edge_list = np.asarray(list(edges.values()))
    edge_face_array = np.full((len(edge_list), 2), -999, dtype=np.int32)
    for index, key in enumerate(edges):
        for column, face in enumerate(edge_faces[key]):
            edge_face_array[index, column] = face + 1
    face_ids = np.asarray(local_faces)
    domains = np.asarray([owner[face] for face in local_faces], dtype=np.int32)
    nt = len(TIMES)
    n_sed, n_layers = 2, 3

    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nmesh2d_node", len(used))
        ds.createDimension("nmesh2d_face", len(local))
        ds.createDimension("nmesh2d_edge", len(edge_list))
        ds.createDimension("max_nmesh2d_face_nodes", 4)
        ds.createDimension("Two", 2)
        ds.createDimension("nSedTot", n_sed)
        ds.createDimension("nBedLayers", n_layers)
        ds.createDimension("strlen", 8)

        topo = ds.createVariable("mesh2d", "i4")
        topo.cf_role = "mesh_topology"
        topo.topology_dimension = 2
        topo.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        topo.face_node_connectivity = "mesh2d_face_nodes"
        topo.edge_node_connectivity = "mesh2d_edge_nodes"
        topo.face_dimension = "nmesh2d_face"
        topo.edge_dimension = "nmesh2d_edge"
        crs = ds.createVariable("projected_coordinate_system", "i4")
        crs.EPSG_code = "EPSG:0"
        crs.wkt = 'PROJCS["Amersfoort / RD New"]'

        ds.createVariable("mesh2d_node_x", "f8", ("nmesh2d_node",))[:] = node_x[used]
        ds.createVariable("mesh2d_node_y", "f8", ("nmesh2d_node",))[:] = node_y[used]
        face_nodes = ds.createVariable("mesh2d_face_nodes", "i4", ("nmesh2d_face", "max_nmesh2d_face_nodes"), fill_value=-999)
        face_nodes.start_index = 1
        face_nodes[:] = local + 1
        edge_nodes = ds.createVariable("mesh2d_edge_nodes", "i4", ("nmesh2d_edge", "Two"))
        edge_nodes.start_index = 1
        edge_nodes[:] = edge_list + 1
        ef = ds.createVariable("mesh2d_edge_faces", "i4", ("nmesh2d_edge", "Two"), fill_value=-999)
        ef.start_index = 1
        ef[:] = edge_face_array
        ds.createVariable("mesh2d_flowelem_domain", "i4", ("nmesh2d_face",))[:] = domains
        ds.createVariable("mesh2d_flowelem_globalnr", "i4", ("nmesh2d_face",))[:] = face_ids + 1

        time = ds.createVariable("time", "f8", ("time",))
        time.units = "seconds since 2020-01-01 00:00:00"
        time[:] = TIMES

        def face_series(name, scale, units="m"):
            variable = ds.createVariable(name, "f8", ("time", "nmesh2d_face"))
            variable.units = units
            variable.long_name = name
            variable[:] = np.asarray([[scale * (face + 1) + 10 * t for face in face_ids] for t in range(nt)])

        face_series("mesh2d_s1", 1.0)
        face_series("mesh2d_waterdepth", 1.0)
        face_series("mesh2d_ucx", 0.3, "m s-1")
        face_series("mesh2d_ucy", 0.4, "m s-1")
        face_series("mesh2d_mor_bl", 0.01)
        node_z = ds.createVariable("mesh2d_node_z", "f8", ("nmesh2d_node",))
        node_z[:] = node_x[used] + 100 * node_y[used]

        lyr = ds.createVariable("mesh2d_lyrfrac", "f8", ("time", "nmesh2d_face", "nBedLayers", "nSedTot"))
        lyr[:] = np.asarray(
            [[[[1000 * t + 100 * (face + 1) + 10 * layer + sed for sed in range(n_sed)] for layer in range(n_layers)]
              for face in face_ids] for t in range(nt)]
        )
        odd = ds.createVariable("mesh2d_odd_order", "f8", ("nSedTot", "time", "nmesh2d_face"))
        odd[:] = np.asarray([[[1000 * sed + 100 * t + face + 1 for face in face_ids] for t in range(nt)] for sed in range(n_sed)])
        static = ds.createVariable("mesh2d_sbxcum", "f8", ("nmesh2d_face", "nSedTot"))
        static[:] = np.asarray([[face + 1 + 0.5 * sed for sed in range(n_sed)] for face in face_ids])
        names = ds.createVariable("sedfrac_name", "S1", ("nSedTot", "strlen"))
        names[:] = [[*"sand", *(["\x00"] * 4)], [*"gravel", *(["\x00"] * 2)]]
        ds.createVariable("mesh2d_face_x", "f8", ("nmesh2d_face",))[:] = 0.0

        q1 = ds.createVariable("mesh2d_q1", "f8", ("time", "nmesh2d_edge"))
        q1.location = "edge"
        gx, gy = node_x[used], node_y[used]
        q1[:] = np.asarray(
            [[_psi(gx[b], gy[b], t) - _psi(gx[a], gy[a], t) for a, b in edge_list] for t in range(nt)]
        )


@pytest.fixture
def partitioned(tmp_path):
    owner = {face: (0 if face % NX < 2 else 1) for face in range(NX * NY)}
    part0 = [face for face in range(NX * NY) if face % NX <= 2]
    part1 = [face for face in range(NX * NY) if face % NX >= 1]
    _write_partition(tmp_path / "model_0000_map.nc", 0, part0, owner)
    _write_partition(tmp_path / "model_0001_map.nc", 1, part1, owner, reverse_edges=True)
    (tmp_path / "model_0000_his.nc").write_text("not a map")
    return tmp_path


def _global_face_ids(grid):
    with netCDF4.Dataset(grid.path) as ds:
        return np.asarray(ds.variables["mesh2d_flowelem_globalnr"][:])[grid.face_index] - 1


def test_discover_partitions_and_base_name(partitioned):
    paths = reader.discover_partitions(partitioned / "model_0001_map.nc")
    assert [p.split("\\")[-1].split("/")[-1] for p in paths] == ["model_0000_map.nc", "model_0001_map.nc"]
    assert reader.partition_id(paths[1]) == 1
    assert reader.model_base_name(paths[1]) == "model_map"
    assert reader.model_base_name("single.nc") == "single"


def test_partition_grids_exclude_ghost_faces_and_compact_nodes(partitioned):
    grids = [reader.read_partition_grid(p) for p in reader.discover_partitions(partitioned / "model_0000_map.nc")]
    owned = [set(_global_face_ids(grid).tolist()) for grid in grids]
    assert owned[0].isdisjoint(owned[1])
    assert owned[0] | owned[1] == set(range(NX * NY))
    for grid in grids:
        assert grid.ghost_filtered
        assert grid.faces.max() == len(grid.node_x) - 1
        assert len(np.unique(grid.faces[grid.faces >= 0])) == len(grid.node_x)


def test_catalogue_lists_face_node_and_derived_variables(partitioned):
    entries = {entry.key: entry for entry in reader.list_variables(partitioned / "model_0000_map.nc")}
    keys = list(entries)
    assert keys[:4] == [
        reader.FROUDE_KEY,
        reader.VELOCITY_MAGNITUDE_KEY,
        reader.BED_LEVEL_CHANGE_KEY,
        reader.STREAM_FUNCTION_KEY,
    ]
    assert entries["mesh2d_node_z"].location == reader.NODE
    assert not entries["mesh2d_node_z"].has_time
    assert entries["mesh2d_s1"].location == reader.FACE
    lyr = entries["mesh2d_lyrfrac"]
    assert [d.name for d in lyr.extra_dims] == ["nBedLayers", "nSedTot"]
    assert lyr.extra_dims[0].labels == ["Layer 1", "Layer 2", "Layer 3"]
    assert lyr.extra_dims[1].labels == ["1: sand", "2: gravel"]
    for excluded in ("mesh2d_node_x", "mesh2d_face_nodes", "mesh2d_q1", "mesh2d_edge_nodes", "sedfrac_name", "mesh2d_face_x", "time"):
        assert excluded not in entries


def test_read_slice_reads_only_owned_values_in_any_dimension_order(partitioned):
    path = partitioned / "model_0000_map.nc"
    entries = {entry.key: entry for entry in reader.list_variables(path)}
    for grid in [reader.read_partition_grid(p) for p in reader.discover_partitions(path)]:
        ids = _global_face_ids(grid)
        np.testing.assert_allclose(reader.read_slice(grid, entries["mesh2d_s1"], 2), ids + 1 + 20)
        np.testing.assert_allclose(
            reader.read_slice(grid, entries["mesh2d_lyrfrac"], 1, [2, 1]), 1000 + 100 * (ids + 1) + 20 + 1
        )
        np.testing.assert_allclose(reader.read_slice(grid, entries["mesh2d_odd_order"], 2, [1]), 1000 + 200 + ids + 1)
        np.testing.assert_allclose(reader.read_slice(grid, entries["mesh2d_sbxcum"], 0, [1]), ids + 1.5)
        np.testing.assert_allclose(
            reader.read_slice(grid, entries["mesh2d_node_z"]), grid.node_x + 100 * grid.node_y
        )


def test_derived_slices(partitioned):
    path = partitioned / "model_0000_map.nc"
    entries = {entry.key: entry for entry in reader.list_variables(path)}
    grid = reader.read_partition_grid(path)
    ids = _global_face_ids(grid)
    ucx = 0.3 * (ids + 1) + 10
    ucy = 0.4 * (ids + 1) + 10
    depth = ids + 1 + 10.0
    speed = reader.read_slice(grid, entries[reader.VELOCITY_MAGNITUDE_KEY], 1)
    np.testing.assert_allclose(speed, np.hypot(ucx, ucy))
    np.testing.assert_allclose(
        reader.read_slice(grid, entries[reader.FROUDE_KEY], 1), np.hypot(ucx, ucy) / np.sqrt(9.81 * depth), rtol=1e-3
    )
    np.testing.assert_allclose(reader.read_slice(grid, entries[reader.BED_LEVEL_CHANGE_KEY], 2), 20.0)
    with pytest.raises(reader.LargeMapError):
        reader.read_slice(grid, entries[reader.STREAM_FUNCTION_KEY], 0)


def test_theta_slices_use_taus_and_sediment_records(partitioned):
    path = partitioned / "model_0000_map.nc"
    records = [SimpleNamespace(name="sand", characteristic_diameter=0.001, dry_density=2650.0)]
    with netCDF4.Dataset(path, "a") as dataset:
        taus = dataset.createVariable("mesh2d_taus", "f8", ("time", "nmesh2d_face"))
        taus[:] = 9810.0

    entries = {entry.key: entry for entry in reader.list_variables(path, records)}
    assert reader.THETA_KEY_PREFIX + "0" in entries
    grid = reader.read_partition_grid(path)
    ids = _global_face_ids(grid)
    expected = np.full(len(ids), 1.0 / ((2650.0 - 1000.0) / 1000.0 * 0.001))
    np.testing.assert_allclose(
        reader.read_slice(grid, entries[reader.THETA_KEY_PREFIX + "0"], 0, sediment_records=records),
        expected,
    )


def test_theta_slices_fall_back_to_velocity_and_chezy(partitioned):
    path = partitioned / "model_0000_map.nc"
    records = [SimpleNamespace(name="sand", characteristic_diameter=0.001, dry_density=2650.0)]
    with netCDF4.Dataset(path, "a") as dataset:
        chezy = dataset.createVariable("mesh2d_czs", "f8", ("time", "nmesh2d_face"))
        chezy[:] = 10.0

    entries = {entry.key: entry for entry in reader.list_variables(path, records)}
    assert reader.THETA_KEY_PREFIX + "0" in entries
    grid = reader.read_partition_grid(path)
    ids = _global_face_ids(grid)
    velocity = np.hypot(0.3 * (ids + 1), 0.4 * (ids + 1))
    shear = 1000.0 * velocity ** 2 * 9.81 / 10.0 ** 2
    expected = shear / (1000.0 * 9.81 * 1.65 * 0.001)
    np.testing.assert_allclose(
        reader.read_slice(grid, entries[reader.THETA_KEY_PREFIX + "0"], 0, sediment_records=records),
        expected,
    )


def test_stream_function_is_consistent_across_partitions(partitioned):
    grids = [reader.read_partition_grid(p) for p in reader.discover_partitions(partitioned / "model_0000_map.nc")]
    graph = reader.StreamFunctionGraph(grids)
    assert graph.node_count == (NX + 1) * (NY + 1)
    for t in range(len(TIMES)):
        values = graph.values_for_time(t)
        all_x = np.concatenate([grid.node_x for grid in grids])
        all_y = np.concatenate([grid.node_y for grid in grids])
        expected = _psi(all_x, all_y, t)
        expected -= _psi(np.arange(NX + 1.0)[:, None], np.arange(NY + 1.0)[None, :], t).min()
        np.testing.assert_allclose(np.concatenate(values), expected, atol=1e-9)


def test_times_and_crs(partitioned):
    values, labels = reader.read_times(partitioned / "model_0000_map.nc")
    np.testing.assert_allclose(values, TIMES)
    assert labels[1] == "2020-01-01 01:00:00"
    assert reader.read_crs_info(partitioned / "model_0000_map.nc") == (None, 'PROJCS["Amersfoort / RD New"]')


def test_single_file_without_partitions_uses_all_faces(tmp_path):
    owner = {face: 0 for face in range(NX * NY)}
    _write_partition(tmp_path / "single_map.nc", 0, list(range(NX * NY)), owner)
    grid = reader.read_partition_grid(tmp_path / "single_map.nc")
    assert grid.partition_id is None
    assert not grid.ghost_filtered
    assert grid.face_count == NX * NY
    assert reader.discover_partitions(tmp_path / "single_map.nc") == [str(tmp_path / "single_map.nc")]
