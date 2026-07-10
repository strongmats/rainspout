from datetime import date

import pytest
from pydantic import Field

from rainspout import registry
from rainspout.contracts import (
    ContractViolation,
    Handler,
    HandlerError,
    HandlerResources,
    RegistrationError,
    ResourcesError,
)


class CsvResources(HandlerResources):
    base_dir: str = Field(min_length=1)
    max_rows: int = Field(default=1000, ge=1, le=1_000_000)


def hooks():
    return {
        "_load_cell": lambda self, coords: ([1.0], {"coords": dict(coords)}),
        "_save_cell": lambda self, coords, data, meta: None,
        "_catalog_cells": lambda self, spec: iter(()),
    }


def make_handler(name="readings_local_csv", **overrides):
    attrs = {
        "name": name,
        "resources_model": CsvResources,
        "dimension_roles": ("day", "sensor"),
        "dimension_types": {"day": date, "sensor": str},
        **hooks(),
    }
    attrs.update(overrides)
    return type("TestHandler", (Handler,), attrs)


# -- registration: the same uniform gesture as stages ---------------------------


def test_subclassing_registers_automatically():
    cls = make_handler()
    assert registry.get("handler", "readings_local_csv") is cls


def test_dotted_name_rejected():
    # C1: underscore names only — no dots.
    with pytest.raises(RegistrationError, match="no dots"):
        make_handler(name="readings_local.csv")


def test_missing_name_fails():
    attrs = {
        "resources_model": CsvResources,
        "dimension_roles": ("day",),
        "dimension_types": {"day": date},
        **hooks(),
    }
    with pytest.raises(RegistrationError, match="name"):
        type("TestHandler", (Handler,), attrs)


def test_stage_and_handler_may_share_a_name():
    # Axes are independent registries; the gesture is uniform, not shared.
    from rainspout.contracts import Stage, StageDependencies, StageSettings

    make_handler(name="same_name")
    stage_cls = type(
        "TestStage",
        (Stage,),
        {
            "name": "same_name",
            "version": "1.0.0",
            "settings_model": StageSettings,
            "dependencies_model": StageDependencies,
            "run": lambda self, deps: None,
        },
    )
    assert registry.get("handler", "same_name") is not stage_cls
    assert registry.get("stage", "same_name") is stage_cls


# -- class-definition-time contract rules ---------------------------------------


def test_defining_init_fails():
    with pytest.raises(ContractViolation, match="__init__"):
        make_handler(**{"__init__": lambda self: None})


def test_public_verbs_are_final():
    for verb in ("load", "load_one", "save", "catalog", "preflight"):
        with pytest.raises(ContractViolation, match=verb):
            make_handler(**{verb: lambda self, *a, **k: None})


def test_missing_hook_fails():
    attrs = {
        "name": "hookless_handler",
        "resources_model": CsvResources,
        "dimension_roles": ("day",),
        "dimension_types": {"day": date},
        **hooks(),
    }
    del attrs["_save_cell"]
    with pytest.raises(ContractViolation, match="_save_cell"):
        type("TestHandler", (Handler,), attrs)


def test_missing_resources_model_fails():
    with pytest.raises(ContractViolation, match="resources_model"):
        make_handler(resources_model=None)


def test_roles_must_be_nonempty_tuple():
    with pytest.raises(ContractViolation, match="dimension_roles"):
        make_handler(dimension_roles=())
    with pytest.raises(ContractViolation, match="dimension_roles"):
        make_handler(dimension_roles=["day", "sensor"])  # list, not tuple


def test_duplicate_roles_rejected():
    with pytest.raises(ContractViolation, match="duplicate"):
        make_handler(dimension_roles=("day", "day"))


def test_dimension_types_must_cover_roles_exactly():
    with pytest.raises(ContractViolation, match="missing.*sensor"):
        make_handler(dimension_types={"day": date})
    with pytest.raises(ContractViolation, match="extra.*hour"):
        make_handler(dimension_types={"day": date, "sensor": str, "hour": int})


def test_capability_flags_must_be_bool():
    with pytest.raises(ContractViolation, match="supports_grid_range"):
        make_handler(supports_grid_range="yes")


def test_capability_flags_default_off():
    cls = make_handler()
    assert cls.supports_grid_range is False
    assert cls.supports_windowed_read is False


# -- construction and resources validation --------------------------------------


def test_valid_resources_construct_frozen():
    handler = make_handler()({"base_dir": "/data/raw"})
    assert handler.resources.base_dir == "/data/raw"
    assert handler.resources.max_rows == 1000
    with pytest.raises(Exception, match="frozen"):
        handler.resources.base_dir = "/elsewhere"


def test_bad_resource_names_handler_and_field():
    with pytest.raises(ResourcesError, match="handler 'readings_local_csv'.*max_rows"):
        make_handler()({"base_dir": "/data", "max_rows": 0})


def test_extra_resource_key_named():
    with pytest.raises(ResourcesError, match="bogus"):
        make_handler()({"base_dir": "/data", "bogus": True})


def test_base_handler_not_instantiable():
    with pytest.raises(ContractViolation, match="abstract"):
        Handler({})


def test_post_definition_verb_assignment_blocked():
    cls = make_handler(name="patched_handler")
    with pytest.raises(ContractViolation, match="load"):
        cls.load = lambda self, spec: None
    with pytest.raises(ContractViolation, match="__init__"):
        cls.__init__ = lambda self: None


# -- the probe path --------------------------------------------------------------


def test_default_probe_loads_and_checks_structure():
    seen = {}

    def load(self, coords):
        seen["loaded"] = dict(coords)
        return [1.0], {"meta": True}

    def check(self, data, meta):
        seen["checked"] = (data, meta)

    handler = make_handler(
        name="probing_handler", _load_cell=load, _check_structure=check
    )({"base_dir": "/data"})
    handler.preflight({"day": "2026-01-01", "sensor": "s1"})
    assert seen["loaded"] == {"day": "2026-01-01", "sensor": "s1"}
    assert seen["checked"] == ([1.0], {"meta": True})


def test_probe_failure_names_handler_and_coordinate():
    def load(self, coords):
        raise ValueError("corrupt header")

    handler = make_handler(name="failing_handler", _load_cell=load)({"base_dir": "/data"})
    with pytest.raises(HandlerError, match="failing_handler.*2026-01-01.*corrupt header"):
        handler.preflight({"day": "2026-01-01", "sensor": "s1"})


def test_probe_is_overridable_without_full_load():
    def probe(self, coords):
        probe.called = dict(coords)

    handler = make_handler(name="header_handler", _probe=probe)({"base_dir": "/data"})
    handler.preflight({"day": "2026-01-01", "sensor": "s1"})
    assert probe.called == {"day": "2026-01-01", "sensor": "s1"}
