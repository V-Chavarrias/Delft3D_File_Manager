# Delft3D File Manager

A QGIS plugin to manage Delft3D files.

## Features
- Reads a fixed-weir text file where each weir is defined by X,Y coordinates and attributes.
- Reads point-cloud `.xyn` files as point layers with optional generated names.
- Reads `.xyz` point files as 2D point layers with a `z` attribute.
- Loads UGRID mesh NetCDF files with a native 2D mesh layer plus 1D vector layers.
- Exports line features and fixed-weir point layers with the main `Export` action.
- Exports generic point layers to ASCII `.xyn` files.
- Writes bed level data into UGRID mesh NetCDF files.
- Creates trachytopes point layers from UGRID mesh edge coordinates.
- Bulk-updates trachytope values for points inside polygons.
- Exports trachytopes to ASCII `.arl` files.

## File Import

Load Delft3D files into QGIS. File type is detected automatically by extension and, for `.pliz`, by the number of columns declared in the file header.

### Supported File Extensions
- **`.fxw`** — Fixed weir file (creates line + point layers)
- **`.pli`, `.ldb`, `.pol`** — Polyline files (creates line layer)
- **`.pliz`** — Auto-detected as polyline or fixed weir based on header column count
- **`.xyn`** — Point files (creates point layer)
- **`.xyz`** — Point files with elevation attribute (creates point layer)
- **`.nc`** — UGRID mesh NetCDF files (creates a native mesh2d layer + 1D polyline/point layers)
- **`.mat`** — ShorelineS results file (creates coastline + optional hard structures/groynes layers)
- **`.csl`, `.csd`** — FM cross-section locations/definitions (prompts for required companion files and creates one point layer)

### Import: Fixed Weir (`.fxw`, `.pliz` with more than 2 columns)

Parse a fixed-weir text file into two memory layers:
- a line layer containing one polyline per weir
- a point layer containing per-point weir attributes

#### Expected Input Format
Each weir block is read in this structure:
1. Weir name line
2. Header line: `<number_of_rows> <number_of_columns>`
3. One row per weir point with:
	 - X, Y
	 - crest level
	 - left sill height
	 - right sill height
	 - crest width
	 - left slope
	 - right slope
	 - roughness coefficient

#### Output Layers
- `<file_name>_lines` (LineString, EPSG:28992)
	- field: `weir_name`
- `<file_name>_points` (Point, EPSG:28992)
	- fields: `weir_name`, `crest_lvl`, `sill_hL`, `sill_hR`, `crest_w`, `slope_L`, `slope_R`, `rough_cd`

### Import: Polyline (`.pli`, `.ldb`, `.pol`, `.pliz` with 2 columns)

Parse a polyline file into a memory line layer with named polylines.

#### Expected Input Format
Each polyline block is read in this structure:
1. Polyline name line
2. Header line: `<number_of_points> 2`
3. One row per vertex with:
	 - X Y

#### Output Layer
- `<file_name>` (LineString, EPSG:28992)
	- field: `weir_name` (contains the polyline block name)

### `.pliz` Detection Rule

When loading a `.pliz` file, the plugin reads the block header line and checks the declared number of columns:
- If the header column count is greater than `2`, the file is loaded as a fixed weir.
- If the header column count is `2`, the file is loaded as a polyline.

### Import: Point (`.xyn`)

Parse an ASCII point file into a memory point layer.

#### Expected Input Format
Each non-empty row contains:
- `x y name`
- or `x y` when name is missing

Columns are whitespace-separated.

#### Name Handling
- If a row has a name value, that value is used.
- If name is missing, the plugin generates `obs_%d` in import order (`obs_1`, `obs_2`, ...).

#### Output Layer
- `<file_name>` (Point, EPSG:28992)
	- fields: `x`, `y`, `name`

### Import: XYZ Point (`.xyz`)

Parse an ASCII point file with elevation values into a 2D memory point layer.

#### Expected Input Format
Each non-empty row contains exactly:
- `x y z`

All three columns must be numeric and whitespace-separated.

#### Output Layer
- `<file_name>` (Point, EPSG:28992)
	- fields: `x`, `y`, `z`

#### Data Handling
- Geometry is imported as standard 2D points
- Elevation is stored in the `z` attribute
- Rows with missing or non-numeric `x`, `y`, or `z` values trigger a validation warning

### Import: UGRID Mesh (`.nc`)

Load UGRID-format NetCDF files containing 1D and/or 2D computational mesh components.
The plugin automatically detects and creates separate layers for each component found.

#### Supported Components

**2D Mesh (mesh2d)**
- Creates a native QGIS mesh layer from the `Mesh2d` topology
- Loads only the 2D mesh topology as mesh, so mesh1d is not added as a separate mesh layer

**1D Mesh Branches (mesh1d)**
- Creates a polyline layer from mesh1d discretization
- Aggregates `mesh1d_edge_nodes` by branch (via `mesh1d_edge_branch` mapping)
- One polyline feature per branch
- Field: `name` (e.g., "Branch_0", "Branch_1", ...)

**Network Geometry Edges**
- Creates a polyline layer from network topology geometry
- Built from `network_edge_nodes` and network node coordinates
- One polyline feature per network edge/branch
- Field: `name` (from `network_branch_long_name` if available)

**Network Geometry Nodes**
- Creates a point layer from detailed geometry nodes
- Extracted from `network_geom_x`, `network_geom_y` coordinates
- One point feature per geometry node
- Field: `name` (descriptive node identifier)

#### Output Layers
When loading a mesh file, the following layers are created (if components exist):
- `<file_name>_mesh2d` (Mesh layer)
- `<file_name>_mesh1d_branches` (LineString layer, with `name` field)
- `<file_name>_geometry_edges` (LineString layer, with `name` field)
- `<file_name>_geometry_nodes` (Point layer, with `name` field)

#### CRS Handling
- The plugin attempts to read EPSG code from NetCDF metadata
- If not found, defaults to EPSG:28992 (RD New projection, common for Dutch models)

### Import: ShorelineS Results (`.mat`)

Load ShorelineS coastal evolution model results from MATLAB files into separate line layers for coastline and hard features.

#### Expected Input Format

A MATLAB `.mat` file containing ShorelineS results with the following required structure:

The data is organized in a nested structure: **`output.O`** contains the ShorelineS data fields:

- **`output.O.x`** — 2D numeric array (n_points × n_timesteps): x-coordinates of coastline
- **`output.O.y`** — 2D numeric array (n_points × n_timesteps): y-coordinates of coastline
- **`output.O.timenum`** — 1D numeric array (n_timesteps): time values for each timestep

Optional datasets (processed when present in `output.O`):
- **`output.O.xhard`, `output.O.yhard`** — 1D or 2D numeric arrays: coordinates of hard structures (e.g., seawalls, dikes). If 2D, the first timestep is used.
- **`output.O.x_groyne`, `output.O.y_groyne`** — 1D or 2D numeric arrays: coordinates of groynes (hard points). If 2D, the first timestep is used.

The plugin automatically detects and extracts data from the nested `output.O` structure.

#### Output Layers

The plugin creates separate layers for each dataset found:

**Coastline Layer** (`<file_name>_coastline`, LineString, EPSG:28992)
- One feature per timestep
- Fields: `t_index` (timestep index), `timenum` (MATLAB datenum), `datetime` (native QGIS DateTime converted from MATLAB datenum)

**Hard Structures Layer** (`<file_name>_hard_structures`, LineString, EPSG:28992)
- Created only if `xhard` and `yhard` are present and contain valid coordinates
- Represents fixed structures like seawalls or dikes
- Fields: `kind` (value: "hard_structure"), `segment_id` (polyline segment index)
- Polylines are separated by NaN markers in the coordinate arrays

**Groynes Layer** (`<file_name>_groynes`, LineString, EPSG:28992)
- Created only if `x_groyne` and `y_groyne` are present and contain valid coordinates
- Represents groynes or other hard point features
- Fields: `kind` (value: "groyne"), `segment_id` (polyline segment index)
- Polylines are separated by NaN markers in the coordinate arrays

#### Data Handling

- **Time-varying coastline**: One feature per timestep; all coastline points at that time are connected in a single polyline (or multiple if NaN-separated)
- **Time-invariant structures/groynes**: Single dataset per type; multiple polylines extracted as separate features, with NaN rows treated as segment separators
- **Coordinate validation**: Only finite (non-NaN) coordinates are imported; short polylines (<2 points) are filtered
- **Empty datasets**: If optional datasets (hard structures/groynes) are all-NaN or empty, no corresponding layer is created; import still succeeds

#### Validation

The plugin validates ShorelineS file structure before import:
- Missing required fields (`x`, `y`, `timenum`) triggers a warning with available field names
- Array shape mismatches (e.g., x and y have different dimensions) trigger an error
- Incompatible data types (non-numeric) trigger an error
- Non-ShorelineS `.mat` files are rejected with a clear diagnostic message

### Import: FM Cross-Sections (`.csl` or `.csd`)

Import Delft3D Flexible Mesh 1D cross-sections into one point layer.

#### Required Input Files
The importer requires all three files:
- **Grid**: UGRID NetCDF file (`.nc`) with mesh1d topology
- **Cross-section locations**: `.csl` (`fileType = crossLoc`)
- **Cross-section definitions**: `.csd` (`fileType = crossDef`)

You can start by selecting either `.csl` or `.csd` from the normal `Import` action.
The plugin then prompts for the missing companion file and the grid file.

#### Location Input (`.csl`)
Each `[CrossSection]` block is expected to contain:
- `id`
- `branchId`
- `chainage`
- `shift`
- `definitionId`

#### Definition Input (`.csd`)
Each `[Definition]` block is keyed by `id` and merged into the output attributes.
For `yz` definitions, arrays such as `yCoordinates` and `zCoordinates` are preserved as text attributes.

#### Output Layer
- `<csl_file_name>_cross_sections` (Point, mesh EPSG from grid or fallback EPSG:28992)

Output attributes include:
- location fields: `id`, `branchId`, `chainage`, `shift`, `definitionId`
- definition fields (if found): `def_type`, `def_thalweg`, `def_singleValZ`, `def_yzCount`, `def_convey`, `def_secCount`, `def_fricIds`, `def_fricPos`, `def_diam`, `def_fricType`, `def_fricVal`, `def_yCoords`, `def_zCoords`
- full serialized definition payload: `def_raw`
- diagnostics: `def_found`, `import_note`

#### Geometry Construction
- Branch geometry is derived from mesh1d connectivity in the selected grid
- Point coordinates are interpolated along the branch at `chainage + shift`

#### Validation And Partial Import
- Cross-sections with missing branch geometry or out-of-range chainage are skipped
- Missing definitions do not block import; points are still created with `def_found = 0`
- Success message reports loaded points and skipped/missing-definition counts

### Profile Chart Window

- Open by double-clicking a cross-section point on the map.
- Also available from plugin menu: `Cross-Section Profile`.
- Supports:
	- `yz` definitions from `def_yCoords` / `def_zCoords`
	- `circle` definitions from `def_diam`
- Axes are labeled with units (`y [m]`, `z [m]`).
- The window uses a matplotlib plot when matplotlib is available, and falls back to the built-in renderer otherwise.
- The chart updates automatically when selection changes on the active cross-section layer.
- No extra dependencies are required.

### Typical Workflow
1. Open `Import` from the plugin menu or toolbar.
2. Select an input file (.fxw, .pli/.ldb/.pol/.pliz, .xyn, .xyz, .nc, .mat, .csl, or .csd).
3. The plugin creates appropriate layer(s) and adds them to the current project.

## Export

Use the main `Export` action to export the active layer to the appropriate Delft3D format.

### Dispatch Rules
- Active line layer: exported to the Delft3D-style polyline text format.
- Active point layer with the fixed-weir fields: exported to `.pliz`.
- Other point layers: use `Export Point Cloud (.xyn)` instead.

### Export: Polyline

### Input Requirements
- Active layer must be a vector line layer.
- Supports single-part and multi-part line geometries.
- A name field is selected automatically with this preference order:
	`weir_name`, `name`, `naam`, `id`, then first available field.

### Output Formats

**Polyline (`.pli`)** — Delft3D block format. For each exported line:
1. Block name (feature name or fallback `feature_<id>`)
2. Header line: `<number_of_points> 2`
3. One line per vertex with `x y`

For multi-part geometries, each part is exported as a separate block with suffix `_1`, `_2`, etc.

**XY (`.xy`)** — Two-column format, compatible with tools that expect plain coordinate lists:
- Two columns per row: `x y`
- No name or header lines
- Consecutive polylines are separated by a `NaN NaN` line
- No trailing `NaN NaN` after the last polyline

### Typical Workflow
1. Select the line layer to export.
2. Open `Export` from the plugin menu or toolbar.
3. Choose output file path — use `.pli` for Delft3D block format or `.xy` for two-column format.
   If no known extension is typed, `.pli` is appended automatically.
4. The plugin writes valid line features to the target file.

### Export: Fixed Weir (`.pliz`)

Export a compatible QGIS point layer to fixed-weir `.pliz` format.

### Input Requirements
- Active layer must be a vector point layer.
- The layer must contain these fields:
	`weir_name`, `crest_lvl`, `sill_hL`, `sill_hR`, `crest_w`, `slope_L`, `slope_R`, `rough_cd`
- `weir_name` must be non-empty.
- Numeric fixed-weir attributes must be finite values.

### Output Format
For each `weir_name`, the plugin writes one block:
1. Weir name line
2. Header line: `<number_of_rows> 9`
3. One row per point with:
	`x y crest_lvl sill_hL sill_hR crest_w slope_L slope_R rough_cd`

### Grouping And Order
- Points are grouped by `weir_name`.
- The current feature iteration order is preserved within each weir block.
- If a block name does not already end with `:`, the exporter adds it in the output file for importer compatibility.

### Typical Workflow
1. Select a compatible fixed-weir point layer.
2. Open `Export` from the plugin menu or toolbar.
3. Choose output `.pliz` path.
4. The plugin writes one fixed-weir block per `weir_name`.

## Point Cloud Export (`.xyn`)

Export a selected QGIS point layer to ASCII `.xyn` format.

### Input Requirements
- Active layer must be a vector point layer.

### Output Format
One row per point:
- `x y name`

### Name Handling
- The plugin tries to use a name-like field with priority:
	`weir_name`, `name`, `naam`, `id`, then first available field.
- If a name is missing or empty, fallback name `obs_%d` is used in export order.

### Typical Workflow
1. Select the point layer to export.
2. Open `Export Point Cloud (.xyn)` from the plugin menu.
3. Choose output `.xyn` path.
4. The plugin writes one line per valid point feature.
5. Use this action for generic point layers that are not fixed-weir `.fxw` layers.

## Bed Level To Mesh

The plugin now supports interpolation of elevation data from external datasets to
UGRID mesh nodes (for example writing to `mesh2d_node_z`).

### Supported Input Sources
- NetCDF file (user selects variable, e.g. `height`)
- QGIS raster layer (user selects band)
- QGIS vector point layer (user selects numeric attribute)

### Interpolation Method
- Mean of points in dual cell

For each mesh node, the plugin builds the node dual cell and computes the mean
of source points inside that polygon. If no point is inside the dual cell,
that mesh node is left unchanged.

### Output Behavior
- If `Output mesh` is empty: the selected mesh file is updated in place.
- If `Output mesh` is set: the input mesh is copied first, and results are
	written to the copied file.

### Dependencies
Required Python packages:
- `netCDF4`
- `pyproj`
- `scipy`

Use one-click installer from the plugin menu:
- `Delft3D File Manager -> Install Python Dependencies`

After installation, restart QGIS.

### Typical Workflow
1. Open `Write Bed Level to Mesh` from the plugin menu.
2. Select target mesh NetCDF file.
3. Select mesh elevation variable (for example `mesh2d_node_z`).
4. Select source type and source variable/layer.
5. Optionally select `Output mesh` to avoid overwriting the input.
6. Choose interpolation method and click `Run`.
7. Open the resulting mesh file and inspect updated node elevations.

## Trachytopes From Mesh

Create trachytopes points from mesh edge coordinates and export selected values
in Delft3D-style ASCII format.

### Menu Actions
- `Create Trachytopes from Mesh`
- `Set Trachytopes in Polygons`
- `Export Trachytopes (.arl)`

### Create Trachytopes Layer
The plugin reads edge coordinates from the selected UGRID NetCDF mesh:
- primary variables: `mesh2d_edge_x`, `mesh2d_edge_y`
- fallback: edge coordinates from UGRID topology metadata when available

It creates a point layer with one feature per mesh edge coordinate and these fields:
- `x`
- `y`
- `trachytope_number` (initial value `0`)
- `fraction` (initial value `0`)

### Edit Trachytope Values
Two workflows are supported:
- Manual editing in the QGIS attribute table.
- Bulk assignment using polygons:
  1. Set the trachytopes layer as active.
  2. Open `Set Trachytopes in Polygons`.
  3. Choose a polygon layer.
  4. Enter target `trachytope_number` and `fraction` values.
  5. Values are applied to points inside selected polygons (or all polygons if none are selected).

### ARL Export Format
Export writes an ASCII text file with extension `.arl` and single-space separators.

Each output row is:
- `x y 0 trachytope_number fraction`

Export rules:
- Only points with `trachytope_number != 0` are written.
- Points with invalid or non-finite numeric values are skipped.

### Typical Workflow
1. Open `Create Trachytopes from Mesh`.
2. Select the UGRID mesh file and create the trachytopes point layer.
3. Assign non-zero trachytope values (manually or with polygons).
4. Open `Export Trachytopes (.arl)`.
5. Save the ASCII `.arl` output file.

## Installation
1. Download the latest release ZIP from [Releases](../../releases).
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.

## Development
Clone this repository and copy the folder into your QGIS plugins directory:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`

Then restart QGIS and enable *Delft3D File Manager*.

Build:
```bash
python .\build_plugin.py
```

Release:
```
git tag v1.0
git push origin v1.0
```

## License
MIT License © Victor Chavarrias