from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from Delft3DFileManager import bed_level_dialog as module


def test_numeric_dtype_helper_rejects_non_numeric_values():
    assert module._is_numeric_dtype(np.float64)
    assert module._is_numeric_dtype("int32")
    assert not module._is_numeric_dtype("not-a-dtype")


def test_dialog_exec_supports_qt6_and_qt5_names():
    qt6_dialog = SimpleNamespace(exec=MagicMock(return_value=7))
    qt5_dialog = SimpleNamespace(exec_=MagicMock(return_value=8))

    assert module._dialog_exec(qt6_dialog) == 7
    assert module._dialog_exec(qt5_dialog) == 8

    with pytest.raises(AttributeError):
        module._dialog_exec(SimpleNamespace())


def test_read_epsg_finds_positive_code_from_variable_attributes():
    class Dataset:
        def __init__(self, variables):
            self.variables = variables

        def __getitem__(self, key):
            return self.variables[key]

    variables = {
        "longitude": SimpleNamespace(),
        "crs": SimpleNamespace(EPSG_code="EPSG:28992"),
    }
    dataset = Dataset(variables)

    assert module._read_epsg_from_nc(dataset) == 28992


def test_read_epsg_ignores_invalid_codes():
    class Dataset:
        def __init__(self, variables):
            self.variables = variables

        def __getitem__(self, key):
            return self.variables[key]

    variables = {
        "bad": SimpleNamespace(epsg="EPSG:-1"),
        "also_bad": SimpleNamespace(EPSG="not-a-number"),
    }
    dataset = Dataset(variables)

    assert module._read_epsg_from_nc(dataset) is None


def test_epsg_from_crs_falls_back_for_non_epsg_authid():
    assert module._epsg_from_crs(SimpleNamespace(authid=lambda: "CUSTOM:1")) == 4326
    assert module._epsg_from_crs(SimpleNamespace(authid=lambda: "EPSG:32631")) == 32631
