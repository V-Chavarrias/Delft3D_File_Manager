import numpy as np
from netCDF4 import Dataset

from Delft3DFileManager.one_d_results import (
    build_mesh1d_graph,
    discover_result_variables,
    nearest_edge,
    nearest_node,
    parse_time_indices,
    read_mesh1d_topology,
    read_result_values,
    shortest_mesh1d_path,
)


def _create_results_file(path):
    with Dataset(str(path), "w") as dataset:
        dataset.createDimension("time", 4)
        dataset.createDimension("mesh1d_nNodes", 4)
        dataset.createDimension("mesh1d_nEdges", 3)
        dataset.createDimension("Two", 2)

        node_x = dataset.createVariable("mesh1d_node_x", "f8", ("mesh1d_nNodes",))
        node_y = dataset.createVariable("mesh1d_node_y", "f8", ("mesh1d_nNodes",))
        edges = dataset.createVariable("mesh1d_edge_nodes", "i4", ("mesh1d_nEdges", "Two"))
        times = dataset.createVariable("time", "f8", ("time",))
        node_values = dataset.createVariable("waterlevel", "f8", ("mesh1d_nNodes", "time"))
        edge_values = dataset.createVariable("discharge", "f8", ("time", "mesh1d_nEdges"))
        node_values.units = "m"
        edge_values.units = "m3/s"

        node_x[:] = [0.0, 1.0, 2.0, 1.0]
        node_y[:] = [0.0, 0.0, 0.0, 1.0]
        edges[:] = [[0, 1], [1, 2], [1, 3]]
        times[:] = [0.0, 1.0, 2.0, 3.0]
        node_values[:] = np.arange(16).reshape(4, 4)
        edge_values[:] = np.arange(12).reshape(4, 3)


def test_parse_time_indices_uses_one_based_inclusive_ranges():
    assert parse_time_indices("1:3,3,4", 4) == [0, 1, 2, 3]
    assert parse_time_indices("3:1", 4) == [2, 1, 0]


def test_results_engine_discovers_node_and_edge_variables_and_reads_dimension_order(tmp_path):
    source = tmp_path / "results.nc"
    _create_results_file(source)
    with Dataset(str(source), "r") as dataset:
        variables = discover_result_variables(dataset)
        topology = read_mesh1d_topology(dataset)
        node_variable = next(item for item in variables if item.location == "node")
        edge_variable = next(item for item in variables if item.location == "edge")

        assert [(item.name, item.location) for item in variables] == [
            ("waterlevel", "node"),
            ("discharge", "edge"),
        ]
        assert read_result_values(dataset, node_variable, [0, 2], [1, 3]).tolist() == [[4.0, 12.0], [6.0, 14.0]]
        assert read_result_values(dataset, edge_variable, [1, 3], [0, 2]).tolist() == [[3.0, 5.0], [9.0, 11.0]]
        assert nearest_node(topology, 1.05, 0.02) == 1
        assert nearest_edge(topology, 1.0, 0.8)[0] == 2


def test_shortest_path_returns_nodes_edges_and_cumulative_distance(tmp_path):
    source = tmp_path / "results.nc"
    _create_results_file(source)
    with Dataset(str(source), "r") as dataset:
        topology = read_mesh1d_topology(dataset)
        graph = build_mesh1d_graph(topology)
        nodes, edges, cumulative = shortest_mesh1d_path(topology, 0, 3)

        assert len(graph) == 4
        assert nodes == [0, 1, 3]
        assert edges == [0, 2]
        assert cumulative == [0.0, 1.0, 2.0]