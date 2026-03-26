# Delft3D File Manager

A QGIS plugin to manage Delft3D files.

## Features
- Reads a fixed-weir text file where each weir is defined by X,Y coordinates and attributes.
- Exports line features as polyline files.
- Writes bed level data into UGRID mesh NetCDF files.

## File Import

Load Delft3D files into QGIS. File type is detected automatically by extension.

### Supported File Extensions
- **`.fxw`** — Fixed weir file (creates line + point layers)
- **`.pli`, `.ldb`, `.pol`, `.pliz`** — Polyline files (creates line layer)

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

### Typical Workflow
1. Open `Load File` from the plugin menu or toolbar.
2. Select an input file (.fxw or .pli/.ldb/.pol/.pliz).
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

## Installation
1. Download the latest release ZIP from [Releases](../../releases).
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.

## Development
Clone this repository and copy the folder into your QGIS plugins directory:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`

Then restart QGIS and enable *Delft3D File Manager*.

## License
MIT License © Victor Chavarrias