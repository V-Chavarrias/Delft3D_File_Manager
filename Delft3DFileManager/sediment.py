"""Readers for Delft3D sediment definition files."""

from dataclasses import dataclass
import math
import os


class SedimentFileError(ValueError):
    """Raised when a sediment file contains an invalid sediment definition."""


@dataclass(frozen=True)
class SedimentRecord:
    """Sediment properties needed by postprocessing."""

    name: str
    sediment_type: str
    characteristic_diameter: float
    diameter: float = None
    minimum_diameter: float = None
    maximum_diameter: float = None
    dry_density: float = None


def _parse_sections(filepath):
    sections = []
    current_name = None
    current_values = {}

    with open(filepath, "r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                if current_name is not None:
                    sections.append((current_name, current_values))
                current_name = line[1:-1].strip()
                current_values = {}
                continue
            if "=" not in line:
                continue
            if current_name is None:
                raise SedimentFileError(
                    f"Line {line_number} contains a key outside a section"
                )
            key, value = line.split("=", 1)
            current_values[key.strip().lower()] = value.strip()

    if current_name is not None:
        sections.append((current_name, current_values))
    return sections


def _positive_float(values, key, block_name):
    try:
        value = float(values[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise SedimentFileError(
            f"{block_name} has an invalid {key} value"
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise SedimentFileError(f"{block_name} has a non-positive {key} value")
    return value


def read_sediment_file(filepath):
    """Read repeated ``[Sediment]`` blocks from a Delft3D ``.sed`` file.

    Diameters are returned in metres. ``SedDia`` is used directly; when it is
    absent, the characteristic diameter is the geometric mean of
    ``SedMinDia`` and ``SedMaxDia``.
    """
    if not isinstance(filepath, (str, os.PathLike)):
        raise TypeError("filepath must be a path-like value")

    records = []
    for section_name, values in _parse_sections(filepath):
        if section_name.lower() != "sediment":
            continue

        block_name = values.get("name", "[Sediment]")
        sediment_type = values.get("sedtyp", "").strip()
        dry_density = (
            _positive_float(values, "rhosol", block_name)
            if "rhosol" in values
            else None
        )
        if "seddia" in values:
            diameter = _positive_float(values, "seddia", block_name)
            records.append(SedimentRecord(
                name=block_name,
                sediment_type=sediment_type,
                characteristic_diameter=diameter,
                diameter=diameter,
                dry_density=dry_density,
            ))
            continue

        minimum = _positive_float(values, "sedmindia", block_name)
        maximum = _positive_float(values, "sedmaxdia", block_name)
        if maximum < minimum:
            raise SedimentFileError(
                f"{block_name} has SedMaxDia smaller than SedMinDia"
            )
        records.append(SedimentRecord(
            name=block_name,
            sediment_type=sediment_type,
            characteristic_diameter=math.sqrt(minimum * maximum),
            minimum_diameter=minimum,
            maximum_diameter=maximum,
            dry_density=dry_density,
        ))

    if not records:
        raise SedimentFileError("No [Sediment] blocks were found")
    return records


def characteristic_grain_sizes(filepath):
    """Return characteristic sediment diameters in file order, in metres."""
    return [record.characteristic_diameter for record in read_sediment_file(filepath)]