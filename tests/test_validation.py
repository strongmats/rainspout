from datetime import date

import pytest
import yaml

import sample_components  # noqa: F401  (importing registers the components)
from rainspout.errors import ConfigError, DefinitionError, ResourcesError, SettingsError
from rainspout.validation import validate_config


def base() -> dict:
    return {
        "run": {"name": "demo", "mode": "retrograde"},
        "dimensions": {
            "day": {"start": date(2026, 1, 1), "stop": date(2026, 1, 3), "step": "1d"},
            "sensor": ["s1", "s2"],
        },
        "iteration": {"order": ["day", "sensor"]},
        "seed": {
            "raw": {
                "handler": "val_readings_csv",
                "resources": {"base_dir": "/data/raw"},
                "dimensions": {"day": "day", "sensor": "sensor"},
            }
        },
        "handlers": {
            "out": {
                "handler": "val_readings_csv",
                "resources": {"base_dir": "/data/out"},
                "dimensions": {"day": "day", "sensor": "sensor"},
            }
        },
        "stages": {
            "smooth": {
                "stage": "val_smooth",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {"window_len": 3},
                "save": {"handler": "out"},
            }
        },
    }


def validate(tmp_path, cfg):
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return validate_config(path)


def test_happy_path(tmp_path):
    run = validate(tmp_path, base())
    assert run.seed_name == "raw"
    assert run.order == ("day", "sensor")
    assert run.dimension_values["day"] == (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3))
    assert run.stage_order == ("smooth",)
    assert run.stage_instances["smooth"].settings.window_len == 3
    assert run.handler_instances["out"].resources.base_dir == "/data/out"
    assert type(run.seed_handler).name == "val_readings_csv"


def test_two_stage_chain_with_auxiliary(tmp_path):
    cfg = base()
    cfg["handlers"]["events_in"] = {
        "handler": "val_events_json",
        "resources": {"base_dir": "/data/events"},
    }
    cfg["stages"]["detect"] = {
        "stage": "val_detect",
        "dependencies": {"data": {"from": "smooth"}, "events": {"handler": "events_in"}},
        "settings": {"threshold": 3.5},
    }
    run = validate(tmp_path, cfg)
    assert run.stage_order == ("smooth", "detect")
    # the auxiliary carries no dimensions map, and that's fine — presence-and-wiring only
    assert "events_in" in run.handler_instances


# -- seed rule ------------------------------------------------------------------


def test_multiple_seeds_rejected(tmp_path):
    cfg = base()
    cfg["seed"]["second"] = dict(cfg["seed"]["raw"])
    with pytest.raises(ConfigError, match="multiple seeds are not supported in v1"):
        validate(tmp_path, cfg)


def test_unknown_seed_handler_names_owner_and_lists_known(tmp_path):
    cfg = base()
    cfg["seed"]["raw"]["handler"] = "nonexistent_handler"
    with pytest.raises(DefinitionError, match="seed 'raw'.*unknown handler 'nonexistent_handler'"):
        validate(tmp_path, cfg)


def test_seed_unmapped_role_named(tmp_path):
    cfg = base()
    del cfg["seed"]["raw"]["dimensions"]["sensor"]
    with pytest.raises(ConfigError, match="seed 'raw'.*unmapped roles.*sensor"):
        validate(tmp_path, cfg)


def test_seed_unknown_role_named(tmp_path):
    cfg = base()
    cfg["seed"]["raw"]["dimensions"]["ghost_role"] = "day"
    with pytest.raises(ConfigError, match="unknown roles.*ghost_role"):
        validate(tmp_path, cfg)


def test_seed_mapping_to_nonexistent_dimension(tmp_path):
    cfg = base()
    cfg["seed"]["raw"]["dimensions"]["sensor"] = "sneaky"
    with pytest.raises(ConfigError, match="'sneaky', which is not a declared dimension"):
        validate(tmp_path, cfg)


def test_seed_must_cover_every_iterated_dimension(tmp_path):
    cfg = base()
    # map both roles onto 'day', leaving 'sensor' uncovered
    cfg["seed"]["raw"]["dimensions"] = {"day": "day", "sensor": "day"}
    with pytest.raises(ConfigError, match="uncovered dimensions.*sensor"):
        validate(tmp_path, cfg)


def test_seed_type_coercion_failure_named(tmp_path):
    cfg = base()
    # feed sensor strings into the date-typed 'day' role
    cfg["seed"]["raw"]["dimensions"] = {"day": "sensor", "sensor": "day"}
    with pytest.raises(ConfigError, match="does not coerce to date"):
        validate(tmp_path, cfg)


def test_seed_bad_resources_named(tmp_path):
    cfg = base()
    cfg["seed"]["raw"]["resources"] = {"base_dir": ""}
    with pytest.raises(ResourcesError, match="seed 'raw'.*base_dir"):
        validate(tmp_path, cfg)


# -- handler instances ------------------------------------------------------------


def test_unknown_handler_registry_key_names_owner(tmp_path):
    cfg = base()
    cfg["handlers"]["out"]["handler"] = "bogus_handler"
    with pytest.raises(
        DefinitionError, match="handler instance 'out'.*unknown handler 'bogus_handler'"
    ):
        validate(tmp_path, cfg)


def test_bad_handler_resources_named(tmp_path):
    cfg = base()
    cfg["handlers"]["out"]["resources"] = {"base_dir": "/data", "extra_knob": 1}
    with pytest.raises(ResourcesError, match="handler instance 'out'.*extra_knob"):
        validate(tmp_path, cfg)


def test_dangling_dimension_in_aux_map(tmp_path):
    cfg = base()
    cfg["handlers"]["out"]["dimensions"]["day"] = "dya"
    with pytest.raises(ConfigError, match="'dya', which is not a declared dimension"):
        validate(tmp_path, cfg)


# -- save targets -------------------------------------------------------------------


def test_save_target_requires_role_map(tmp_path):
    cfg = base()
    del cfg["handlers"]["out"]["dimensions"]
    with pytest.raises(ConfigError, match="save target.*dimensions"):
        validate(tmp_path, cfg)


def test_save_target_map_held_to_seed_standard(tmp_path):
    cfg = base()
    del cfg["handlers"]["out"]["dimensions"]["sensor"]
    with pytest.raises(ConfigError, match="save target.*unmapped roles.*sensor"):
        validate(tmp_path, cfg)


def test_save_names_unknown_instance(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["save"] = {"handler": "nowhere"}
    with pytest.raises(ConfigError, match="save names unknown handler instance 'nowhere'"):
        validate(tmp_path, cfg)


# -- stages -----------------------------------------------------------------------


def test_unknown_stage_registry_key_names_owner(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["stage"] = "bogus_stage"
    with pytest.raises(
        DefinitionError, match="stage instance 'smooth'.*unknown stage 'bogus_stage'"
    ):
        validate(tmp_path, cfg)


def test_bad_setting_names_instance_and_field(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["settings"] = {"window_len": 0}
    with pytest.raises(SettingsError, match="stage instance 'smooth'.*window_len"):
        validate(tmp_path, cfg)


def test_missing_dependency_named(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["dependencies"] = {}
    with pytest.raises(ConfigError, match="missing dependencies.*data"):
        validate(tmp_path, cfg)


def test_emptied_dependencies_key_reports_missing_dependency(tmp_path):
    # deleting every entry under `dependencies:` leaves the key parsing as
    # YAML None — the reader must still get the real error, not a type complaint
    cfg = base()
    cfg["stages"]["smooth"]["dependencies"] = None
    with pytest.raises(ConfigError, match="stage 'smooth' is missing dependencies.*data"):
        validate(tmp_path, cfg)


def test_emptied_settings_key_reaches_settings_check(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["settings"] = None
    with pytest.raises(SettingsError, match="stage instance 'smooth'.*window_len"):
        validate(tmp_path, cfg)


def test_emptied_handlers_key_treated_as_none_declared(tmp_path):
    cfg = base()
    cfg["handlers"] = None
    del cfg["stages"]["smooth"]["save"]
    run = validate(tmp_path, cfg)
    assert run.handler_instances == {}


def test_extra_dependency_named(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["dependencies"]["extra"] = {"from": "raw"}
    with pytest.raises(ConfigError, match="unknown dependency 'extra'"):
        validate(tmp_path, cfg)


def test_lazyreference_field_wired_with_handler_rejected(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["dependencies"]["data"] = {"handler": "out"}
    with pytest.raises(ConfigError, match="must be wired with 'from:'"):
        validate(tmp_path, cfg)


def test_handler_field_wired_with_from_rejected(tmp_path):
    cfg = base()
    cfg["handlers"]["events_in"] = {
        "handler": "val_events_json",
        "resources": {"base_dir": "/data/events"},
    }
    cfg["stages"]["detect"] = {
        "stage": "val_detect",
        "dependencies": {"data": {"from": "smooth"}, "events": {"from": "smooth"}},
        "settings": {"threshold": 1.0},
    }
    with pytest.raises(ConfigError, match="must be wired with 'handler:'"):
        validate(tmp_path, cfg)


def test_handler_dependency_names_unknown_instance(tmp_path):
    cfg = base()
    cfg["stages"]["detect"] = {
        "stage": "val_detect",
        "dependencies": {"data": {"from": "smooth"}, "events": {"handler": "ghost"}},
        "settings": {"threshold": 1.0},
    }
    with pytest.raises(ConfigError, match="unknown handler instance 'ghost'"):
        validate(tmp_path, cfg)


def test_from_unknown_upstream_named(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["dependencies"]["data"] = {"from": "rew"}
    with pytest.raises(ConfigError, match="'from: rew' names no stage instance or seed entry"):
        validate(tmp_path, cfg)


def test_stage_name_may_not_shadow_seed(tmp_path):
    cfg = base()
    cfg["stages"]["raw"] = {
        "stage": "val_smooth",
        "dependencies": {"data": {"from": "smooth"}},
        "settings": {"window_len": 1},
    }
    with pytest.raises(ConfigError, match="names both the seed entry and a stage"):
        validate(tmp_path, cfg)


# -- graph rules ---------------------------------------------------------------------


def test_cycle_rejected(tmp_path):
    cfg = base()
    cfg["stages"]["smooth"]["dependencies"]["data"] = {"from": "smooth2"}
    cfg["stages"]["smooth2"] = {
        "stage": "val_smooth",
        "dependencies": {"data": {"from": "smooth"}},
        "settings": {"window_len": 1},
    }
    with pytest.raises(ConfigError, match="cycle"):
        validate(tmp_path, cfg)


def test_branching_rejected_in_v1(tmp_path):
    cfg = base()
    cfg["stages"]["smooth2"] = {
        "stage": "val_smooth",
        "dependencies": {"data": {"from": "raw"}},
        "settings": {"window_len": 1},
    }
    with pytest.raises(ConfigError, match="not supported in v1"):
        validate(tmp_path, cfg)


# --- optional dependencies (`X | None`) ---------------------------------------


def _optional_cfg(wire_table: bool):
    """A config using val_optional, with the `table` dependency wired or not."""
    cfg = base()
    deps = {"data": {"from": "raw"}}
    if wire_table:
        deps["table"] = {"handler": "out"}
    cfg["stages"] = {
        "opt": {"stage": "val_optional", "dependencies": deps, "settings": {}},
    }
    return cfg


def test_optional_dependency_may_be_left_unwired(tmp_path):
    """The whole point: `table: Handler | None` is the stage's business to
    require or not, so validation must not insist on it."""
    validate(tmp_path, _optional_cfg(wire_table=False))


def test_optional_dependency_may_also_be_wired(tmp_path):
    validate(tmp_path, _optional_cfg(wire_table=True))


def test_optional_dependency_still_type_checks_its_wiring(tmp_path):
    """Optional means 'may be absent', not 'anything goes'. A Handler-annotated
    dependency wired with `from:` is still an error."""
    cfg = _optional_cfg(wire_table=True)
    cfg["stages"]["opt"]["dependencies"]["table"] = {"from": "raw"}
    with pytest.raises(ConfigError, match="must be wired with 'handler:'"):
        validate(tmp_path, cfg)


def test_required_dependency_is_still_required(tmp_path):
    cfg = _optional_cfg(wire_table=False)
    cfg["stages"]["opt"]["dependencies"] = {}
    with pytest.raises(ConfigError, match="missing dependencies.*data"):
        validate(tmp_path, cfg)
