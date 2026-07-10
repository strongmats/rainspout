import pytest

from rainspout.testing import from_handler_data, run_stage

from .stage import RefEnrich

STAGE = RefEnrich
EXAMPLE_SETTINGS = {"node_dim": "node"}


def test_known_output_with_stage_computed_lookup():
    out = run_stage(
        STAGE,
        EXAMPLE_SETTINGS,
        deps={
            "data": [1.0, 2.0],
            "calibration": from_handler_data({"gain": 2.0, "offset": 1.0}),
        },
        coords={"tick": 0, "node": "alpha"},
    )
    assert out == [3.0, 5.0]


def test_bad_calibration_table_raises():
    with pytest.raises(Exception, match="gain/offset"):
        run_stage(
            STAGE,
            EXAMPLE_SETTINGS,
            deps={"data": [1.0], "calibration": from_handler_data({"nope": 1})},
            coords={"node": "alpha"},
        )
