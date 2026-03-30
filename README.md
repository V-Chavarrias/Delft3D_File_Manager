# Delft3D File Manager

A QGIS plugin to manage Delft3D files.

## Features
- Reads a fixed-weir text file where each weir is defined by X,Y coordinates and attributes.
- Reads point-cloud `.xyn` files as point layers with optional generated names.
- Exports line features as polyline files.
- Exports point layers to ASCII `.xyn` files.
- Writes bed level data into UGRID mesh NetCDF files.
- Creates trachytopes point layers from UGRID mesh edge coordinates.
- Bulk-updates trachytope values for points inside polygons.
- Exports trachytopes to ASCII `.arl` files.

## File Import

Load Delft3D files into QGIS. File type is detected automatically by extension.

### Supported File Extensions
- **`.fxw`** — Fixed weir file (creates line + point layers)
- **`.pli`, `.ldb`, `.pol`, `.pliz`** — Polyline files (creates line layer)
- **`.xyn`** — Point files (creates point layer)

### Import: Fixed Weir (`.fxw`)

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

### Import: Polyline (`.pli`, `.ldb`, `.pol`, `.pliz`)

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

### Typical Workflow
1. Open `Load File` from the plugin menu or toolbar.
2. Select an input file (.fxw, .pli/.ldb/.pol/.pliz, or .xyn).
3. The plugin creates appropriate layer(s) and adds them to the current project.

## Polyline Export

Export a selected QGIS line layer to the Delft3D-style text format.

### Input Requirements
- Active layer must be a vector line layer.
- Supports single-part and multi-part line geometries.
- A name field is selected automatically with this preference order:
	`weir_name`, `name`, `naam`, `id`, then first available field.

### Output Format
For each exported line, a text block is written:
1. Block name (feature name or fallback `feature_<id>`)
2. Header line: `<number_of_points> 2`
3. One line per vertex with `x y`

For multi-part geometries, each part is exported as a separate block with
suffix `_1`, `_2`, etc.

### Typical Workflow
1. Select the line layer to export.
2. Open `Export Polyline` from the plugin menu or toolbar.
3. Choose output text file path.
4. The plugin writes valid line features to the target file.

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
git push origin v1.0.0
```

## License
MIT License © Victor Chavarrias