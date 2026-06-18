from pathlib import Path

import pytest


def _make_profile(name, points, terminal_nodes, effective_length=None):
    profile_length = 0.0
    for idx in range(1, len(points)):
        x0, y0 = points[idx - 1]
        x1, y1 = points[idx]
        profile_length += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5

    return {
        "name": name,
        "points": list(points),
        "cumlen": [0.0, profile_length],
        "length": profile_length,
        "geometry_length": profile_length,
        "effective_length": float(effective_length) if effective_length is not None else profile_length,
        "imposed_length": float(effective_length) if effective_length is not None else None,
        "terminal_nodes": terminal_nodes,
        "terminal_snap_distances": (0.0, 0.0),
    }


def test_build_mesh_reuses_terminal_node_direction_agnostic(plugin):
    p1 = _make_profile("A", [(0.0, 0.0), (100.0, 0.0)], ("n_a", "j"))
    p2 = _make_profile("B", [(100.0, 100.0), (100.0, 0.0)], ("n_b", "j"))
    p3 = _make_profile("C", [(100.0, 0.0), (200.0, 0.0)], ("j", "n_c"))

    mesh_data = plugin._build_mesh_from_profiles(
        branch_profiles=[p1, p2, p3],
        spacing=100.0,
        special_constraints=[],
        offset_distance=10.0,
    )

    assert mesh_data is not None
    assert mesh_data["n_edges"] > 0

    junction_node_ids = []
    for branch in mesh_data["branch_node_chainages"]:
        for entry in branch["entries"]:
            if entry["terminal_name"] == "j":
                junction_node_ids.append(entry["node_id"])

    assert len(junction_node_ids) == 3
    assert len(set(junction_node_ids)) == 1


def test_imposed_length_used_for_mesh_chainage(plugin):
    profile = _make_profile(
        "A",
        [(0.0, 0.0), (100.0, 0.0)],
        ("n0", "n1"),
        effective_length=200.0,
    )

    mesh_data = plugin._build_mesh_from_profiles(
        branch_profiles=[profile],
        spacing=75.0,
        special_constraints=[],
        offset_distance=10.0,
    )

    assert mesh_data is not None
    branch = mesh_data["branch_node_chainages"][0]
    chainages = [item["chainage"] for item in branch["entries"]]
    # With the fix: spacing of 75m for 200m length should produce [0, 75, 200]
    # Cell sizes: 75m and 125m (all >= 75m minimum spacing)
    # Previously was [0, 75, 150, 200] with cell sizes 75, 75, 50 (last cell too short)
    assert chainages == [0.0, 75.0, 200.0]
    assert mesh_data["network_edge_length"] == [200.0]


def test_structure_offsets_use_closest_mesh_node(plugin):
    profile = _make_profile(
        "A",
        [(0.0, 0.0), (1000.0, 0.0)],
        ("n0", "n1"),
    )

    special_constraints = [
        {
            "branch_name": "A",
            "chainage": 310.0,
            "valid_flag": 1,
        }
    ]

    mesh_data = plugin._build_mesh_from_profiles(
        branch_profiles=[profile],
        spacing=200.0,
        special_constraints=special_constraints,
        offset_distance=10.0,
    )

    assert mesh_data is not None
    branch = mesh_data["branch_node_chainages"][0]
    chainages = [round(item["chainage"], 6) for item in branch["entries"]]

    # Closest base node to 310 with spacing 200 is 400, so offsets are 390 and 410.
    assert 390.0 in chainages
    assert 410.0 in chainages


def test_write_1d_network_log_contains_required_sections(plugin, tmp_path):
    profile = _make_profile("A", [(0.0, 0.0), (100.0, 0.0)], ("n0", "n1"), effective_length=120.0)
    mesh_data = plugin._build_mesh_from_profiles(
        branch_profiles=[profile],
        spacing=50.0,
        special_constraints=[],
        offset_distance=10.0,
    )

    log_path = Path(tmp_path) / "network.log"
    plugin._write_1d_network_log(str(log_path), mesh_data)

    content = log_path.read_text(encoding="utf-8")
    assert "Node-Branch Connectivity" in content
    assert "Branch Lengths" in content
    assert "Branch Node Chainages" in content
    assert "Branch Edge Chainages" in content
    assert "mesh1d_nodes=" in content
    assert "mesh1d_edges=" in content


def test_write_netcdf_string_array_accepts_numpy_bytes(plugin, tmp_path):
    nc = pytest.importorskip("netCDF4")
    np = pytest.importorskip("numpy")

    nc_path = Path(tmp_path) / "bytes_case.nc"
    with nc.Dataset(str(nc_path), "w", format="NETCDF4") as ds:
        ds.createDimension("n", 2)
        var = plugin._write_netcdf_string_array(
            ds,
            "network_branch_long_name",
            "n",
            [np.bytes_(b"branch_a"), "branch_b"],
            strlen_dim="strLengthLongNames",
        )

        assert var.dimensions == ("n", "strLengthLongNames")
        assert var.shape == (2, 8)

        row0 = b"".join(var[0, :].tolist()).decode("utf-8", errors="replace").rstrip()
        row1 = b"".join(var[1, :].tolist()).decode("utf-8", errors="replace").rstrip()
        assert row0 == "branch_a"
        assert row1 == "branch_b"


def test_write_1d_network_netcdf_includes_reference_schema_variables(plugin, tmp_path):
    nc = pytest.importorskip("netCDF4")

    profile = _make_profile("A", [(0.0, 0.0), (100.0, 0.0)], ("n0", "n1"), effective_length=120.0)
    mesh_data = plugin._build_mesh_from_profiles(
        branch_profiles=[profile],
        spacing=50.0,
        special_constraints=[],
        offset_distance=10.0,
    )

    nc_path = Path(tmp_path) / "network_schema.nc"
    plugin._write_1d_network_netcdf(str(nc_path), mesh_data, 28992)

    required_vars = {
        "network",
        "network_edge_nodes",
        "network_branch_id",
        "network_branch_long_name",
        "network_edge_length",
        "network_node_id",
        "network_node_long_name",
        "network_node_x",
        "network_node_y",
        "network_geometry",
        "network_geom_node_count",
        "network_geom_x",
        "network_geom_y",
        "network_branch_order",
        "network_branch_type",
        "mesh1d",
        "mesh1d_node_branch",
        "mesh1d_node_offset",
        "mesh1d_node_x",
        "mesh1d_node_y",
        "mesh1d_edge_branch",
        "mesh1d_edge_offset",
        "mesh1d_edge_x",
        "mesh1d_edge_y",
        "mesh1d_node_id",
        "mesh1d_node_long_name",
        "mesh1d_edge_nodes",
        "projected_coordinate_system",
    }

    with nc.Dataset(str(nc_path), "r") as ds:
        assert required_vars.issubset(set(ds.variables.keys()))
        assert ds.data_model == "NETCDF3_CLASSIC"
        assert "network_nEdges" in ds.dimensions
        assert "network_nNodes" in ds.dimensions
        assert "network_nGeometryNodes" in ds.dimensions
        assert "strLengthIds" in ds.dimensions
        assert "strLengthLongNames" in ds.dimensions
        assert getattr(ds.variables["network"], "cf_role", "") == "mesh_topology"
        assert getattr(ds.variables["mesh1d"], "cf_role", "") == "mesh_topology"
        assert getattr(ds.variables["network_node_x"], "standard_name", "") == "projection_x_coordinate"
        assert getattr(ds.variables["network_node_y"], "standard_name", "") == "projection_y_coordinate"
        assert getattr(ds.variables["network_geom_x"], "standard_name", "") == "projection_x_coordinate"
        assert getattr(ds.variables["network_geom_y"], "standard_name", "") == "projection_y_coordinate"
        assert getattr(ds.variables["mesh1d_node_x"], "standard_name", "") == "projection_x_coordinate"
        assert getattr(ds.variables["mesh1d_node_y"], "standard_name", "") == "projection_y_coordinate"
        assert getattr(ds.variables["mesh1d_edge_x"], "standard_name", "") == "projection_x_coordinate"
        assert getattr(ds.variables["mesh1d_edge_y"], "standard_name", "") == "projection_y_coordinate"

        assert ds.variables["network_branch_id"].dimensions == ("network_nEdges", "strLengthIds")
        assert ds.variables["network_branch_long_name"].dimensions == ("network_nEdges", "strLengthLongNames")
        assert ds.variables["network_node_id"].dimensions == ("network_nNodes", "strLengthIds")
        assert ds.variables["network_node_long_name"].dimensions == ("network_nNodes", "strLengthLongNames")
        assert ds.variables["mesh1d_node_id"].dimensions == ("mesh1d_nNodes", "strLengthIds")
        assert ds.variables["mesh1d_node_long_name"].dimensions == ("mesh1d_nNodes", "strLengthLongNames")


def test_cell_length_minimum_constraint_no_short_cells(plugin):
    """Test that no cell is shorter than the imposed spacing (minimum cell length).
    
    When branch length and spacing don't divide evenly, the last cell must be
    extended to accommodate the remainder, ensuring all cells >= imposed spacing.
    """
    # Case 1: Branch length 200m with spacing 75m
    # Current behavior (buggy): [0, 75, 150, 200] -> cells: 75, 75, 50 (last cell too short)
    # Fixed behavior: [0, 75, 200] -> cells: 75, 125 (all cells >= 75)
    profile_200m = _make_profile(
        "A",
        [(0.0, 0.0), (100.0, 0.0)],
        ("n0", "n1"),
        effective_length=200.0,
    )

    mesh_data = plugin._build_mesh_from_profiles(
        branch_profiles=[profile_200m],
        spacing=75.0,
        special_constraints=[],
        offset_distance=10.0,
    )

    assert mesh_data is not None
    branch = mesh_data["branch_node_chainages"][0]
    chainages = [item["chainage"] for item in branch["entries"]]
    
    # Verify all cells are >= spacing
    for i in range(len(chainages) - 1):
        cell_length = chainages[i + 1] - chainages[i]
        assert cell_length >= 75.0, f"Cell from {chainages[i]} to {chainages[i+1]} is {cell_length}m, less than imposed spacing 75m"


def test_cell_length_minimum_constraint_various_cases(plugin):
    """Test cell length minimum constraint with various branch/spacing combinations."""
    test_cases = [
        # (branch_length, spacing, description)
        (100.0, 30.0, "100m length with 30m spacing"),
        (150.0, 50.0, "150m length with 50m spacing"),
        (1000.0, 200.0, "1000m length with 200m spacing"),
    ]
    
    for branch_length, spacing, description in test_cases:
        profile = _make_profile(
            "test_branch",
            [(0.0, 0.0), (branch_length, 0.0)],
            ("n0", "n1"),
            effective_length=branch_length,
        )

        mesh_data = plugin._build_mesh_from_profiles(
            branch_profiles=[profile],
            spacing=spacing,
            special_constraints=[],
            offset_distance=10.0,
        )

        assert mesh_data is not None, f"Failed for case: {description}"
        branch = mesh_data["branch_node_chainages"][0]
        chainages = [item["chainage"] for item in branch["entries"]]
        
        # Verify start and end points
        assert chainages[0] == 0.0, f"First chainage should be 0 for {description}"
        assert abs(chainages[-1] - branch_length) < 1e-6, f"Last chainage should be {branch_length} for {description}"
        
        # Verify all cells are >= spacing (minimum constraint)
        for i in range(len(chainages) - 1):
            cell_length = chainages[i + 1] - chainages[i]
            assert cell_length >= spacing * 0.99999, (  # Small tolerance for floating point
                f"Case: {description}\n"
                f"Cell from {chainages[i]} to {chainages[i+1]} is {cell_length}m, "
                f"less than imposed spacing {spacing}m"
            )