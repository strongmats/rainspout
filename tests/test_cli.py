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


def _valid_config(tmp_path):
    """write_config's default maps the sensor role onto a date dimension, which
    does not coerce; give both roles their own string-valued axis."""
    def fix(cfg):
        cfg["dimensions"] = {"day": [date(2026, 1, 1)], "sensor": ["s1"]}
        cfg["iteration"] = {"order": ["day", "sensor"]}
        cfg["seed"]["raw"]["dimensions"] = {"day": "day", "sensor": "sensor"}

    return write_config(tmp_path, fix)


def test_sigint_aborts_the_in_flight_item(tmp_path, monkeypatch):
    """Ctrl-C must return to the prompt now, not at the next item boundary.

    The graceful stop only lands between work items, so on a long item a
    caught SIGINT reads as a hang. `run` therefore installs a handler that
    raises, and reports the abandonment rather than a clean stop.
    """
    import signal

    import rainspout.cli.main as cli

    seen = {}

    def fake_drive(*_args, **_kwargs):
        # stand where a long work item stands: the handler is installed, and
        # the signal arrives mid-item. Invoke it exactly as the OS would.
        handler = signal.getsignal(signal.SIGINT)
        seen["handler_is_a_bare_latch"] = handler is _kwargs["stop"].set
        handler(signal.SIGINT, None)  # must raise
        raise AssertionError("SIGINT handler returned instead of raising")

    monkeypatch.setattr(cli, "drive", fake_drive)
    result = runner.invoke(app, ["run", "--config", str(_valid_config(tmp_path))])

    assert seen["handler_is_a_bare_latch"] is False, "SIGINT must not merely set the flag"
    assert result.exit_code == 130, result.output
    assert "interrupted" in result.output
    assert "rerun to resume" in result.output
    # a second Ctrl-C must reach the OS, the only thing that can interrupt a
    # long call inside a C extension
    assert signal.getsignal(signal.SIGINT) is signal.SIG_DFL


def test_sigterm_keeps_the_graceful_contract(tmp_path, monkeypatch):
    """`kill` and schedulers expect a clean boundary stop, not an abandoned item."""
    import signal

    import rainspout.cli.main as cli

    captured = {}

    def fake_drive(*_args, **kwargs):
        captured["handler"] = signal.getsignal(signal.SIGTERM)
        captured["stop_set"] = kwargs["stop"].set
        raise KeyboardInterrupt  # unwind without running a real DAG

    monkeypatch.setattr(cli, "drive", fake_drive)
    runner.invoke(app, ["run", "--config", str(_valid_config(tmp_path))])

    assert captured["handler"] == captured["stop_set"]
