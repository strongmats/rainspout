"""Packaging guarantees: what the built distribution must carry."""

from pathlib import Path

import rainspout


def test_py_typed_marker_ships_with_the_package():
    # PEP 561: without this marker, type checkers ignore every annotation in
    # the installed package — content packages could not type-check against
    # the contracts (the Typing :: Typed classifier would be a lie)
    assert (Path(rainspout.__file__).parent / "py.typed").exists()
