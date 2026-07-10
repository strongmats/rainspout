"""The status file, the reporting hook, `spout status`, and the run lock."""

from datetime import date

import pytest
import yaml
from typer.testing import CliRunner

import roundtrip_handlers as rt
import runner_components  # noqa: F401  (importing registers the components)
import sample_components  # noqa: F401
from rainspout.cli.main import app
from rainspout.driver import acquire_run_lock
from rainspout.errors import ConfigError
from rainspout.status import StatusReporter, make_stage_hook, read_status

runner = CliRunner()


def make_reporter(tmp_path, **kwargs):
    return StatusReporter(
        tmp_path / ".rainspout" / "demo.status.json",
        run_name="demo", run_id="demo-20260101T000000Z-abc123", mode="retrograde",
        **kwargs,
    )


def test_reporter_lifecycle_roundtrip(tmp_path):
    reporter = make_reporter(tmp_path)
    reporter.plan(cycle=1, to_run=3, done=1, failed=1, missing=0)
    reporter.stage_started("day=2026-01-01|sensor=s1", "smooth")
    reporter.item_finished("succeeded")
    reporter.item_finished("failed")
    reporter.finished(stopped=False)

    doc = read_status(tmp_path / ".rainspout" / "demo.status.json")
    assert doc.state == "finished"
    assert doc.run_name == "demo"
    assert (doc.succeeded, doc.failed) == (1, 1)
    assert doc.plan is not None and doc.plan.to_run == 3 and doc.plan.done == 1
    assert doc.current is None  # cleared on finish


def test_stage_ticks_are_throttled_but_boundaries_always_write(tmp_path):
    now = {"t": 0.0}
    reporter = make_reporter(tmp_path, min_interval=10.0, clock=lambda: now["t"])
    path = tmp_path / ".rainspout" / "demo.status.json"

    reporter.stage_started("day=2026-01-01|sensor=s1", "smooth")  # boundary: writes
    reporter.stage_tick("first", 0.1)   # within interval of the boundary write: skipped
    assert read_status(path).current.status_line == ""

    now["t"] = 11.0
    reporter.stage_tick("second", 0.5)  # interval elapsed: written
    doc = read_status(path)
    assert doc.current.status_line == "second"
    assert doc.current.progress == 0.5

    now["t"] = 11.5
    reporter.item_finished("succeeded")  # boundary: writes despite the interval
    assert read_status(path).succeeded == 1


def test_set_status_and_set_progress_drive_the_hook(tmp_path):
    stage = sample_components.ValSmooth({"window_len": 3})
    calls = []
    stage._report_hook = lambda line, progress: calls.append((line, progress))
    stage.set_status("working")
    stage.set_progress(0.25)
    assert calls == [("working", None), ("working", 0.25)]


def test_tick_reaches_the_file_with_current_stage(tmp_path):
    reporter = make_reporter(tmp_path, min_interval=0.0)
    reporter.stage_started("day=2026-01-01|sensor=s1", "smooth")
    make_stage_hook(reporter)("halfway there", 0.5)
    doc = read_status(tmp_path / ".rainspout" / "demo.status.json")
    assert doc.state == "running"
    assert doc.current.cell_id == "day=2026-01-01|sensor=s1"
    assert doc.current.stage == "smooth"
    assert doc.current.status_line == "halfway there"
    assert doc.current.progress == 0.5


def world(tmp_path):
    src = tmp_path / "raw"
    rt.write_example_cell(src, "2026-01-01", "s1")
    cfg = {
        "run": {"name": "status_demo", "mode": "retrograde"},
        "dimensions": {"day": [date(2026, 1, 1)], "sensor": ["s1"]},
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
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_run_publishes_status_and_the_command_reads_it(tmp_path):
    config = world(tmp_path)
    assert runner.invoke(app, ["run", "--config", str(config)]).exit_code == 0

    result = runner.invoke(app, ["status", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "run 'status_demo' — finished" in result.output
    assert "this run: 1 succeeded, 0 failed" in result.output
    assert "mode retrograde, cycle 1" in result.output


def test_dry_run_publishes_nothing(tmp_path):
    config = world(tmp_path)
    assert runner.invoke(app, ["run", "--config", str(config), "--dry-run"]).exit_code == 0
    result = runner.invoke(app, ["status", "--config", str(config)])
    assert result.exit_code == 1
    assert "no status recorded" in result.output


def test_status_before_any_run_reports_missing(tmp_path):
    config = world(tmp_path)
    result = runner.invoke(app, ["status", "--config", str(config)])
    assert result.exit_code == 1
    assert "no status recorded for run 'status_demo'" in result.output


def test_run_lock_admits_one_run_per_definition(tmp_path):
    oplog_path = tmp_path / ".rainspout" / "demo.oplog.jsonl"
    release = acquire_run_lock(oplog_path, run_name="demo", run_id="demo-1")
    with pytest.raises(ConfigError, match="run 'demo' is already active.*pid.*demo-1"):
        acquire_run_lock(oplog_path, run_name="demo", run_id="demo-2")
    release()
    release_again = acquire_run_lock(oplog_path, run_name="demo", run_id="demo-3")
    release_again()


def test_second_concurrent_run_fails_loudly_via_cli(tmp_path):
    config = world(tmp_path)
    oplog_path = tmp_path / ".rainspout" / "status_demo.oplog.jsonl"
    release = acquire_run_lock(oplog_path, run_name="status_demo", run_id="held-elsewhere")
    try:
        result = runner.invoke(app, ["run", "--config", str(config)])
        assert result.exit_code == 1
        assert "already active" in result.output
    finally:
        release()
