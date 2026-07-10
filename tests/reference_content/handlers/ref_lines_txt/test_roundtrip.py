from pathlib import Path

from rainspout.testing import assert_roundtrip

from .handler import RefLinesTxt

HANDLER = RefLinesTxt
EXAMPLE_RESOURCES = {"base_dir": Path(__file__).parent / "example_data"}
EXAMPLE_COORDS = {"tick": 7, "node": "alpha"}


def test_roundtrip(tmp_path):
    # metadata-ignoring: passes because data survives; never failed for
    # dropping the block it does not claim to handle
    assert_roundtrip(HANDLER, EXAMPLE_RESOURCES, EXAMPLE_COORDS, tmp_path)
