import pytest

from fake_package import write_fake_package
from rainspout.conformance import check_package
from rainspout.errors import DefinitionError


def check(tmp_path, monkeypatch, pkg, overrides=None):
    write_fake_package(tmp_path, pkg, overrides)
    monkeypatch.syspath_prepend(str(tmp_path))
    return check_package(pkg)


def test_conforming_package_passes_with_lint_warning(tmp_path, monkeypatch):
    report = check(tmp_path, monkeypatch, "confpkg_ok")
    assert report.ok
    assert {c.name for c in report.components} == {"confpkg_ok_double", "confpkg_ok_json_cell"}
    stage_check = next(c for c in report.components if c.axis == "stage")
    assert any("unbounded str domain" in w for w in stage_check.warnings)  # the 'note' field


def test_missing_stage_test_file_fails(tmp_path, monkeypatch):
    report = check(
        tmp_path, monkeypatch, "confpkg_notest",
        {"stages/double_values/test_double_values.py": None},
    )
    stage_check = next(c for c in report.components if c.axis == "stage")
    assert not stage_check.ok
    assert any("no mandated test file" in p for p in stage_check.problems)


def test_test_module_without_mandated_names_fails(tmp_path, monkeypatch):
    report = check(
        tmp_path, monkeypatch, "confpkg_nonames",
        {"stages/double_values/test_double_values.py": "def test_something(): pass\n"},
    )
    stage_check = next(c for c in report.components if c.axis == "stage")
    assert any("STAGE and EXAMPLE_SETTINGS" in p for p in stage_check.problems)


def test_invalid_example_settings_fails(tmp_path, monkeypatch):
    bad = (
        "from .stage import Double\n"
        "STAGE = Double\n"
        "EXAMPLE_SETTINGS = {'factor': 99}\n"
        "def test_x(): pass\n"
    )
    report = check(
        tmp_path, monkeypatch, "confpkg_badsettings",
        {"stages/double_values/test_double_values.py": bad},
    )
    stage_check = next(c for c in report.components if c.axis == "stage")
    assert any("EXAMPLE_SETTINGS does not validate" in p for p in stage_check.problems)


def test_wrong_example_coords_fails(tmp_path, monkeypatch):
    bad = (
        "from pathlib import Path\n"
        "from .handler import JsonCell\n"
        "HANDLER = JsonCell\n"
        "EXAMPLE_RESOURCES = {'base_dir': Path(__file__).parent / 'example_data'}\n"
        "EXAMPLE_COORDS = {'wrong_role': 'k1'}\n"
        "def test_x(): pass\n"
    )
    report = check(
        tmp_path, monkeypatch, "confpkg_badcoords",
        {"handlers/json_cell/test_roundtrip.py": bad},
    )
    handler_check = next(c for c in report.components if c.axis == "handler")
    assert any("do not match the declared roles" in p for p in handler_check.problems)


def test_missing_example_data_fails(tmp_path, monkeypatch):
    report = check(
        tmp_path, monkeypatch, "confpkg_nodata",
        {"handlers/json_cell/example_data/k1.json": None},
    )
    handler_check = next(c for c in report.components if c.axis == "handler")
    assert any("example data" in p for p in handler_check.problems)


def test_empty_collector_module_is_caught(tmp_path, monkeypatch):
    # the silent-failure mode from PACKAGE_AUTHORING §4: components not imported
    # in components.py simply never register — this is where it gets caught
    with pytest.raises(DefinitionError, match="registered no components"):
        check(tmp_path, monkeypatch, "confpkg_empty", {"components.py": "# forgot imports\n"})


def test_unknown_package_named(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(DefinitionError, match="no_such_pkg"):
        check_package("no_such_pkg")


# -- the bounded-settings lint recurses into nested models ----------------------


def test_unbounded_lint_sees_inside_union_arms():
    from typing import Annotated, Literal, Union

    from pydantic import BaseModel, Field

    from rainspout.conformance import _unbounded_warnings

    class MeanMethod(BaseModel):
        kind: Literal["mean"]

    class WeightedMethod(BaseModel):
        kind: Literal["weighted"]
        weights: list[float] = Field(min_length=1, max_length=1000)
        scale: float  # unbounded, hiding inside an arm

    class Settings(BaseModel):
        # the legacy Union[...] spelling on purpose: the lint must see through
        # both typing.Union and X | Y origins (the self-reference test covers | )
        method: Annotated[Union[MeanMethod, WeightedMethod], Field(discriminator="kind")]  # noqa: UP007

    warnings = _unbounded_warnings(Settings, "stage 'ws'")
    assert warnings == [
        "stage 'ws': field 'method[WeightedMethod].scale' has an unbounded "
        "float domain — add Field constraints, a Literal/Enum, "
        "or a justifying comment (docs, bounded-settings rule)"
    ]


def test_unbounded_lint_sees_plain_nested_models_and_containers():
    from pydantic import BaseModel, Field

    from rainspout.conformance import _unbounded_warnings

    class Knob(BaseModel):
        level: int  # unbounded

    class Settings(BaseModel):
        sub: Knob
        many: list[Knob]
        bounded: int = Field(ge=0, le=10)

    warnings = _unbounded_warnings(Settings, "stage 's'")
    assert [w.split("'")[3] for w in warnings] == ["sub.level", "many.level"]


def test_unbounded_lint_survives_self_reference():
    from pydantic import BaseModel

    from rainspout.conformance import _unbounded_warnings

    class Node(BaseModel):
        depth: int  # unbounded
        child: "Node | None" = None

    Node.model_rebuild()
    warnings = _unbounded_warnings(Node, "stage 'tree'")
    assert len(warnings) == 1 and "'depth'" in warnings[0]
