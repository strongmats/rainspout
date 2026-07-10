from pathlib import Path

from rainspout.testing import assert_roundtrip

from .handler import RefTableJson

HANDLER = RefTableJson
EXAMPLE_RESOURCES = {"base_dir": Path(__file__).parent / "example_data"}
EXAMPLE_COORDS = {"station": "alpha"}


def test_roundtrip(tmp_path):
    assert_roundtrip(HANDLER, EXAMPLE_RESOURCES, EXAMPLE_COORDS, tmp_path)
