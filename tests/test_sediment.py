import math

import pytest

from Delft3DFileManager.sediment import (
    SedimentFileError,
    characteristic_grain_sizes,
    read_sediment_file,
)


def test_read_sediment_file_uses_seddia_and_preserves_order(tmp_path):
    path = tmp_path / "sample.sed"
    path.write_text(
        "[Sediment]\nName = sand\nSedTyp = bedload\nSedDia = 0.001\nRhoSol = 2650\n"
        "[Sediment]\nName = gravel\nSedTyp = suspended\nSedDia = 0.004\nRhoSol = 2700\n",
        encoding="utf-8",
    )

    records = read_sediment_file(path)

    assert [record.name for record in records] == ["sand", "gravel"]
    assert [record.sediment_type for record in records] == ["bedload", "suspended"]
    assert [record.dry_density for record in records] == [2650.0, 2700.0]
    assert characteristic_grain_sizes(path) == [0.001, 0.004]


def test_read_sediment_file_allows_missing_dry_density_for_existing_workflows(tmp_path):
    path = tmp_path / "legacy.sed"
    path.write_text("[Sediment]\nName = sand\nSedDia = 0.001\n", encoding="utf-8")

    assert read_sediment_file(path)[0].dry_density is None


def test_read_sediment_file_rejects_invalid_dry_density(tmp_path):
    path = tmp_path / "invalid_density.sed"
    path.write_text(
        "[Sediment]\nName = sand\nSedDia = 0.001\nRhoSol = 0\n",
        encoding="utf-8",
    )

    with pytest.raises(SedimentFileError, match="rhosol"):
        read_sediment_file(path)


def test_read_sediment_file_uses_geometric_mean_for_diameter_range(tmp_path):
    path = tmp_path / "range.sed"
    path.write_text(
        "[Sediment]\nName = graded\nSedMinDia = 0.0001\nSedMaxDia = 0.0009\n",
        encoding="utf-8",
    )

    record = read_sediment_file(path)[0]

    assert math.isclose(record.characteristic_diameter, 0.0003)
    assert record.diameter is None
    assert record.minimum_diameter == 0.0001
    assert record.maximum_diameter == 0.0009


def test_read_sediment_file_rejects_incomplete_range(tmp_path):
    path = tmp_path / "invalid.sed"
    path.write_text("[Sediment]\nSedMinDia = 0.001\n", encoding="utf-8")

    with pytest.raises(SedimentFileError, match="sedmaxdia"):
        read_sediment_file(path)