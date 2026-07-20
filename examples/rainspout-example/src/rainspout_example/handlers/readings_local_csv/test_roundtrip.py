from pathlib import Path

from rainspout.testing import assert_roundtrip

from .handler import ReadingsLocalCsv

HANDLER = ReadingsLocalCsv
EXAMPLE_RESOURCES = {"base_dir": Path(__file__).parent / "example_data"}
EXAMPLE_COORDS = {"day": "2026-01-01", "sensor": "s1"}


def test_roundtrip(tmp_path):
    assert_roundtrip(HANDLER, EXAMPLE_RESOURCES, EXAMPLE_COORDS, tmp_path)
