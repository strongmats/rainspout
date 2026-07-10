import pytest

from rainspout.testing import run_stage

from .stage import RefSnip

STAGE = RefSnip
EXAMPLE_SETTINGS = {"tick_dim": "tick"}


def test_known_output_uses_coordinate():
    out = run_stage(
        STAGE, EXAMPLE_SETTINGS, deps={"data": [6.0, 7.5]}, coords={"tick": 5, "node": "a"}
    )
    assert out == [1.0, 2.5]


def test_missing_coordinate_key_raises():
    with pytest.raises(Exception, match="tick_dim"):
        run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": [1.0]}, coords={"node": "a"})
