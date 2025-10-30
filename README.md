# WeirImporter

A QGIS plugin to import custom text files defining weirs as LineString geometries.

## Features
- Reads a text file where each weir is defined by X,Y coordinates and attributes.
- Automatically creates a memory layer in EPSG:28992.
- Adds attributes for crest level, sill heights, slopes, crest width, and roughness.

## Installation
1. Download the latest release ZIP from [Releases](../../releases).
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.

## Development
Clone this repository and copy the folder into your QGIS plugins directory:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`

Then restart QGIS and enable *WeirImporter*.

## License
MIT License © Victor Chavarrias