import pytest

from rainspout.testing import run_stage

from .science import smooth
from .stage import SmoothReadings

STAGE = SmoothReadings
EXAMPLE_SETTINGS = {"window_len": 3, "method": "mean"}


def test_smooths_known_input():
    out = run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": [1.0, 4.0, 1.0]})
    assert out == [2.5, 2.0, 2.5]


def test_rejects_non_list():
    with pytest.raises(Exception, match="expected list"):
        run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": "nope"})


def test_science_directly():  # module-level functions: test them raw
    assert smooth([1.0, 1.0], 1, "mean") == [1.0, 1.0]
