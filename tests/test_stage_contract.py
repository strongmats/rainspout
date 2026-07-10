from typing import Literal

import pytest
from pydantic import Field

from rainspout import registry
from rainspout.contracts import (
    ContractViolation,
    LazyReference,
    RegistrationError,
    SettingsError,
    Stage,
    StageDependencies,
    StageError,
    StageSettings,
)


class SmoothSettings(StageSettings):
    window_len: int = Field(ge=1, le=10_000)
    method: Literal["mean", "median"] = "mean"


class SmoothDeps(StageDependencies):
    data: LazyReference


def make_stage(name="smooth_readings", **overrides):
    attrs = {
        "name": name,
        "version": "1.0.0",
        "settings_model": SmoothSettings,
        "dependencies_model": SmoothDeps,
        "run": lambda self, deps: deps.data.get(),
    }
    attrs.update(overrides)
    return type("TestStage", (Stage,), attrs)


# -- registration -------------------------------------------------------------


def test_subclassing_registers_automatically():
    cls = make_stage()
    assert registry.get("stage", "smooth_readings") is cls


def test_missing_name_fails_at_definition():
    with pytest.raises(RegistrationError, match="name"):
        type("TestStage", (Stage,), {"version": "1.0.0"})


def test_dotted_name_rejected():
    with pytest.raises(RegistrationError, match="no dots"):
        make_stage(name="smooth.readings")


def test_uppercase_name_rejected():
    with pytest.raises(RegistrationError, match="invalid"):
        make_stage(name="SmoothReadings")


def test_duplicate_name_fails():
    make_stage()
    with pytest.raises(RegistrationError, match="duplicate stage"):
        make_stage()


# -- class-definition-time contract rules --------------------------------------


def test_defining_init_fails_at_class_definition():
    with pytest.raises(ContractViolation, match="__init__"):
        make_stage(**{"__init__": lambda self: None})


def test_mixin_with_init_rejected():
    class Sneaky:
        def __init__(self):
            pass

    with pytest.raises(ContractViolation, match="mixes in"):
        type(
            "TestStage",
            (Stage, Sneaky),
            {
                "name": "sneaky_stage",
                "version": "1.0.0",
                "settings_model": SmoothSettings,
                "dependencies_model": SmoothDeps,
                "run": lambda self, deps: None,
            },
        )


def test_missing_version_fails():
    with pytest.raises(ContractViolation, match="version"):
        make_stage(version=None)


def test_missing_settings_model_fails():
    with pytest.raises(ContractViolation, match="settings_model"):
        make_stage(settings_model=None)


def test_missing_dependencies_model_fails():
    with pytest.raises(ContractViolation, match="dependencies_model"):
        make_stage(dependencies_model=None)


def test_missing_run_fails():
    with pytest.raises(ContractViolation, match="run"):
        type(
            "TestStage",
            (Stage,),
            {
                "name": "runless_stage",
                "version": "1.0.0",
                "settings_model": SmoothSettings,
                "dependencies_model": SmoothDeps,
            },
        )


def test_overriding_final_reporting_method_fails():
    with pytest.raises(ContractViolation, match="set_status"):
        make_stage(set_status=lambda self, s: None)


def test_progress_is_overridable():
    cls = make_stage(progress=lambda self: 0.5)
    assert cls({"window_len": 3}).progress() == 0.5


def test_post_definition_init_assignment_blocked():
    # __init_subclass__ guards the class body; the metaclass closes the
    # remaining bypass: monkey-patching __init__ after the class exists.
    cls = make_stage()
    with pytest.raises(ContractViolation, match="__init__"):
        cls.__init__ = lambda self: None
    stage = cls({"window_len": 3})  # validation still intact
    assert stage.settings.window_len == 3


def test_post_definition_final_method_assignment_blocked():
    cls = make_stage()
    with pytest.raises(ContractViolation, match="set_status"):
        cls.set_status = lambda self, s: None


def test_base_class_itself_cannot_be_patched():
    with pytest.raises(ContractViolation, match="__init__"):
        Stage.__init__ = lambda self: None


# -- construction and settings validation --------------------------------------


def test_valid_settings_construct_frozen():
    stage = make_stage()({"window_len": 5})
    assert stage.settings.window_len == 5
    assert stage.settings.method == "mean"
    with pytest.raises(Exception, match="frozen"):
        stage.settings.window_len = 6


def test_out_of_range_setting_names_stage_and_field():
    with pytest.raises(SettingsError, match="stage 'smooth_readings'.*window_len"):
        make_stage()({"window_len": 0})


def test_unknown_setting_key_names_offender():
    with pytest.raises(SettingsError, match="bogus"):
        make_stage()({"window_len": 5, "bogus": 1})


def test_missing_required_setting_named():
    with pytest.raises(SettingsError, match="window_len"):
        make_stage()({})


def test_bad_literal_choice_named():
    with pytest.raises(SettingsError, match="method"):
        make_stage()({"window_len": 5, "method": "meen"})


def test_base_stage_not_instantiable():
    with pytest.raises(ContractViolation, match="abstract"):
        Stage({})


# -- reporting machinery --------------------------------------------------------


def test_status_progress_warnings_roundtrip():
    stage = make_stage()({"window_len": 3})
    assert stage.status() == ""
    stage.set_status("smoothing 100 rows")
    assert stage.status() == "smoothing 100 rows"

    assert stage.progress() is None
    stage.set_progress(0.25)
    assert stage.progress() == 0.25
    with pytest.raises(StageError, match=r"\[0, 1\]"):
        stage.set_progress(1.5)

    stage.add_warning("clipped 3 outliers")
    assert stage.warnings == ("clipped 3 outliers",)


def test_run_receives_dependencies():
    stage = make_stage()({"window_len": 3})
    deps = SmoothDeps(data=LazyReference.from_value([1.0, 2.0]))
    assert stage.run(deps) == [1.0, 2.0]
