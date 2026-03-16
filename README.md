# Delft3D File Manager

A QGIS plugin to import fixed-weir files from Delft3D FM as LineString geometries.

## Features
- Reads a text file where each weir is defined by X,Y coordinates and attributes.
- Automatically creates a memory layer in EPSG:28992.
- Adds attributes for crest level, sill heights, slopes, crest width, and roughness.
- Exports line features from the active line layer to a custom text format.

Export output format:

```
name_1
number_lines number_columns
x1 y1
x2 y2
...
name_2
number_lines number_columns
x1 y1
x2 y2
...
```

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