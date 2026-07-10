from datetime import date

import yaml
from typer.testing import CliRunner

import sample_components  # noqa: F401  (importing registers the components)
from rainspout.cli.main import app

runner = CliRunner()


def write_config(tmp_path, mutate=None):
    cfg = {
        "run": {"name": "demo", "mode": "retrograde"},
        "dimensions": {"day": [date(2026, 1, 1)]},
        "seed": {
            "raw": {
                "handler": "val_readings_csv",
                "resources": {"base_dir": "/data/raw"},
                "dimensions": {"day": "day", "sensor": "day"},
            }
        },
        "stages": {
            "smooth": {
                "stage": "val_smooth",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {"window_len": 3},
            }
        },
    }
    if mutate:
        mutate(cfg)
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_validate_success(tmp_path):
    # single 'day' dimension; both seed roles legitimately map onto it —
    # but sensor role is date-typed here? No: map sensor role onto day works
    # only if values coerce to str, which dates do not. Use a str dimension.
    def fix(cfg):
        cfg["dimensions"] = {"day": [date(2026, 1, 1)], "sensor": ["s1"]}
        cfg["iteration"] = {"order": ["day", "sensor"]}
        cfg["seed"]["raw"]["dimensions"] = {"day": "day", "sensor": "sensor"}

    result = runner.invoke(app, ["validate", "--config", str(write_config(tmp_path, fix))])
    assert result.exit_code == 0, result.output
    assert "config ✓" in result.output


def test_run_end_to_end_then_resume(tmp_path):
    import roundtrip_handlers as rt

    src = tmp_path / "raw"
    rt.write_example_cell(src, "2026-01-01", "s1")
    rt.write_example_cell(src, "2026-01-02", "s1")
    (src / "2026-01-02" / "s1.csv").write_text("garbage\nnot,a,value\n")  # corrupt one cell
    cfg = {
        "run": {"name": "cli_demo", "mode": "retrograde"},
        "dimensions": {"day": [date(2026, 1, 1), date(2026, 1, 2)], "sensor": ["s1"]},
        "iteration": {"order": ["day", "sensor"]},
        "seed": {
            "raw": {
                "handler": "rt_readings_csv",
                "resources": {"base_dir": str(src)},
                "dimensions": {"day": "day", "sensor": "sensor"},
            }
        },
        "handlers": {
            "out": {
                "handler": "rt_readings_csv",
                "resources": {"base_dir": str(tmp_path / "out")},
                "dimensions": {"day": "day", "sensor": "sensor"},
            }
        },
        "stages": {
            "scale": {
                "stage": "run_scale",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {"factor": 2.0},
                "save": {"handler": "out"},
            }
        },
    }
    import runner_components  # noqa: F401

    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))

    dry = runner.invoke(app, ["run", "--config", str(path), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "plan: 2 work items — 2 to run, 0 done, 0 previously failed" in dry.output

    first = runner.invoke(app, ["run", "--config", str(path)])
    assert first.exit_code == 0, first.output
    assert "pre-flight: seed raw ✓" in first.output
    assert "scale ✓  saved → out" in first.output
    assert "FAILED" in first.output
    assert "done: 1 succeeded, 1 failed" in first.output

    resume = runner.invoke(app, ["run", "--config", str(path)])
    assert "plan: 2 work items — 0 to run, 1 done, 1 previously failed" in resume.output

    rt.write_example_cell(src, "2026-01-02", "s1")  # fix the input
    retry = runner.invoke(app, ["run", "--config", str(path), "--retry-failed"])
    assert "done: 1 succeeded, 0 failed" in retry.output


def test_validate_failure_exits_nonzero(tmp_path):
    def broken(cfg):
        cfg["stages"]["smooth"]["settings"] = {"window_len": 0}
        cfg["dimensions"] = {"day": [date(2026, 1, 1)], "sensor": ["s1"]}
        cfg["iteration"] = {"order": ["day", "sensor"]}
        cfg["seed"]["raw"]["dimensions"] = {"day": "day", "sensor": "sensor"}

    result = runner.invoke(app, ["validate", "--config", str(write_config(tmp_path, broken))])
    assert result.exit_code == 1
    assert "validation failed" in result.output
    assert "window_len" in result.output
