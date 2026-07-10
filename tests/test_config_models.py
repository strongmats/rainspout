from datetime import date

import pytest
import yaml

from rainspout.config import load_config
from rainspout.errors import ConfigError


def minimal() -> dict:
    return {
        "run": {"name": "demo", "mode": "retrograde"},
        "dimensions": {"day": [date(2026, 1, 1)]},
        "seed": {
            "raw": {
                "handler": "some_handler",
                "resources": {},
                "dimensions": {"day": "day"},
            }
        },
        "stages": {"smooth": {"stage": "some_stage", "dependencies": {}, "settings": {}}},
    }


def write(tmp_path, cfg):
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_minimal_config_parses(tmp_path):
    config = load_config(write(tmp_path, minimal()))
    assert config.run.name == "demo"
    assert config.iteration is None
    assert config.handlers == {}


def test_unknown_top_level_key(tmp_path):
    cfg = minimal() | {"parallelism": 4}
    with pytest.raises(ConfigError, match="parallelism"):
        load_config(write(tmp_path, cfg))


def test_missing_top_level_key(tmp_path):
    cfg = minimal()
    del cfg["stages"]
    with pytest.raises(ConfigError, match="stages"):
        load_config(write(tmp_path, cfg))


def test_extra_key_in_run(tmp_path):
    cfg = minimal()
    cfg["run"]["threads"] = 8
    with pytest.raises(ConfigError, match="threads"):
        load_config(write(tmp_path, cfg))


def test_bad_run_name(tmp_path):
    cfg = minimal()
    cfg["run"]["name"] = "has spaces!"
    with pytest.raises(ConfigError, match="run.name"):
        load_config(write(tmp_path, cfg))


def test_poll_frequency_forbidden_for_retrograde(tmp_path):
    cfg = minimal()
    cfg["run"]["poll_frequency"] = 60
    with pytest.raises(ConfigError, match="forbidden"):
        load_config(write(tmp_path, cfg))


def test_poll_frequency_required_for_realtime(tmp_path):
    cfg = minimal()
    cfg["run"]["mode"] = "realtime"
    with pytest.raises(ConfigError, match="required"):
        load_config(write(tmp_path, cfg))


def test_realtime_with_poll_frequency_ok(tmp_path):
    cfg = minimal()
    cfg["run"]["mode"] = "realtime"
    cfg["run"]["poll_frequency"] = 60
    assert load_config(write(tmp_path, cfg)).run.poll_frequency == 60


def test_dependency_wired_with_both_kinds_rejected(tmp_path):
    cfg = minimal()
    cfg["stages"]["smooth"]["dependencies"] = {"data": {"from": "raw", "handler": "x"}}
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(write(tmp_path, cfg))


def test_dependency_wired_with_neither_kind_rejected(tmp_path):
    cfg = minimal()
    cfg["stages"]["smooth"]["dependencies"] = {"data": {}}
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(write(tmp_path, cfg))


def test_empty_seed_rejected(tmp_path):
    cfg = minimal()
    cfg["seed"] = {}
    with pytest.raises(ConfigError, match="seed"):
        load_config(write(tmp_path, cfg))


def test_non_mapping_yaml_rejected(tmp_path):
    path = tmp_path / "run.yml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)


def test_invalid_yaml_rejected(tmp_path):
    path = tmp_path / "run.yml"
    path.write_text("run: [unclosed\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(path)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yml")
