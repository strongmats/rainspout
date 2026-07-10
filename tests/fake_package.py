"""Builds a small, fully conforming content package on disk for the
conformance and test-package tests. Shaped exactly like PACKAGE_AUTHORING §2
(one stage directory, one handler directory with example data, a components.py
collector), so it doubles as a from-scratch exercise of the whole authoring
contract."""

import json
from pathlib import Path

STAGE_PY = '''
from pydantic import Field
from rainspout.contracts import LazyReference, Stage, StageDependencies, StageSettings


class DoubleSettings(StageSettings):
    factor: int = Field(ge=1, le=10)
    note: str = "hi"  # deliberately unbounded: draws the lint warning


class DoubleDeps(StageDependencies):
    data: LazyReference


class Double(Stage):
    name = "{pkg}_double"
    version = "1.0.0"
    settings_model = DoubleSettings
    dependencies_model = DoubleDeps

    def run(self, deps):
        self.set_status("doubling")
        return [v * self.settings.factor for v in deps.data.get()]
'''

STAGE_TEST_PY = '''
import pytest

from rainspout.testing import run_stage

from .stage import Double

STAGE = Double
EXAMPLE_SETTINGS = {"factor": 2}


def test_known_output():
    assert run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": [1.0, 3.0]}) == [2.0, 6.0]


def test_failure_path():
    with pytest.raises(Exception, match="factor"):
        run_stage(STAGE, {"factor": 99}, deps={"data": []})
'''

HANDLER_PY = '''
import json
from pathlib import Path

from rainspout.contracts import CatalogEntry, Handler, HandlerResources, Meta


class JsonCellResources(HandlerResources):
    base_dir: Path


class JsonCell(Handler):
    """One JSON file per cell, metadata embedded in the document."""

    name = "{pkg}_json_cell"
    resources_model = JsonCellResources
    dimension_roles = ("key",)
    dimension_types = {{"key": str}}

    def _cell_path(self, coords):
        return self.resources.base_dir / f"{{coords['key']}}.json"

    def _load_cell(self, coords):
        payload = json.loads(self._cell_path(coords).read_text())
        raw_meta = payload.get("meta")
        meta = Meta.model_validate(raw_meta) if raw_meta else Meta.fresh(coords=dict(coords))
        return payload["data"], meta

    def _save_cell(self, coords, data, meta):
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({{"data": data, "meta": json.loads(meta.model_dump_json())}})
        )

    def _catalog_cells(self, spec):
        for key in spec["key"]:
            if self._cell_path({{"key": key}}).exists():
                yield CatalogEntry(coords={{"key": key}})
'''

HANDLER_TEST_PY = '''
from pathlib import Path

from rainspout.testing import assert_roundtrip

from .handler import JsonCell

HANDLER = JsonCell
EXAMPLE_RESOURCES = {"base_dir": Path(__file__).parent / "example_data"}
EXAMPLE_COORDS = {"key": "k1"}


def test_roundtrip(tmp_path):
    assert_roundtrip(HANDLER, EXAMPLE_RESOURCES, EXAMPLE_COORDS, tmp_path)
'''

COMPONENTS_PY = """
from {pkg}.handlers.json_cell import handler as _handler
from {pkg}.stages.double_values import stage as _stage
"""


def write_fake_package(root: Path, pkg: str, overrides: dict | None = None) -> Path:
    """Write the package tree; overrides maps relpath -> content (None omits)."""
    files = {
        "__init__.py": "",
        "components.py": COMPONENTS_PY.format(pkg=pkg),
        "stages/__init__.py": "",
        "stages/double_values/__init__.py": "",
        "stages/double_values/stage.py": STAGE_PY.format(pkg=pkg),
        "stages/double_values/test_double_values.py": STAGE_TEST_PY,
        "handlers/__init__.py": "",
        "handlers/json_cell/__init__.py": "",
        "handlers/json_cell/handler.py": HANDLER_PY.format(pkg=pkg),
        "handlers/json_cell/test_roundtrip.py": HANDLER_TEST_PY,
        "handlers/json_cell/example_data/k1.json": json.dumps(
            {"data": [1.0, 2.5], "meta": None}
        ),
    }
    files.update(overrides or {})
    package_root = root / pkg
    for relpath, content in files.items():
        if content is None:
            continue
        path = package_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return package_root
