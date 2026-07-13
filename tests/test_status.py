"""The live status line, the reporting hook, and the run lock."""

import io
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
from rainspout.status import LiveStatus, make_stage_hook

runner = CliRunner()


def make_live(**kwargs):
    stream = io.StringIO()
    kwargs.setdefault("width", 120)
    kwargs.setdefault("min_interval", 0.0)
    return LiveStatus(stream, **kwargs), stream


def frames(stream):
    """Each in-place redraw, oldest first, trailing pad spaces stripped."""
    return [chunk.rstrip(" ") for chunk in stream.getvalue().split("\r")]


def test_live_line_lifecycle(tmp_path):
    live, stream = make_live()
    live.plan(cycle=1, to_run=3, done=1, failed=1, missing=0)
    live.stage_started("day=2026-01-01|sensor=s1", "smooth")
    make_stage_hook(live)("halfway there", 0.5)
    live.item_finished("succeeded")
    live.item_finished("failed")
    live.finished(stopped=False)

    drawn = frames(stream)
    assert "0/3" in drawn
    assert "0/3 · [day=2026-01-01|sensor=s1] smooth" in drawn
    assert "0/3 · [day=2026-01-01|sensor=s1] smooth — halfway there 50%" in drawn
    assert "1/3" in drawn
    assert "2/3 · 1 failed" in drawn
    # finished() clears: the stream ends on an empty, blanked-out line
    assert stream.getvalue().endswith("\r")
    assert drawn[-1] == ""


def test_stage_ticks_are_throttled_but_boundaries_always_draw():
    now = {"t": 0.0}
    live, stream = make_live(min_interval=10.0, clock=lambda: now["t"])

    live.stage_started("day=2026-01-01|sensor=s1", "smooth")  # boundary: draws
    live.stage_tick("first", 0.1)   # within interval of the boundary draw: skipped
    assert not any("first" in f for f in frames(stream))

    now["t"] = 11.0
    live.stage_tick("second", 0.5)  # interval elapsed: drawn
    assert any("second" in f and "50%" in f for f in frames(stream))

    now["t"] = 11.5
    live.item_finished("succeeded")  # boundary: draws despite the interval
    assert frames(stream)[-1].startswith("1/0")


def test_tick_outside_a_work_item_draws_nothing():
    live, stream = make_live()
    live.stage_tick("orphan", 0.5)
    assert stream.getvalue() == ""


def test_clear_blanks_the_whole_previous_line():
    live, stream = make_live()
    live.plan(cycle=1, to_run=12, done=0, failed=0, missing=0)
    live.stage_started("day=2026-01-01|sensor=s1", "smooth")
    drawn_len = len(frames(stream)[-1])
    live.clear()
    assert stream.getvalue().endswith("\r" + " " * drawn_len + "\r")
    live.clear()  # idempotent: a second clear writes nothing more
    assert stream.getvalue().endswith("\r" + " " * drawn_len + "\r")


def test_line_is_truncated_to_the_terminal_width():
    live, stream = make_live(width=24)
    live.stage_started("day=2026-01-01|sensor=s1", "a_very_long_stage_name")
    assert all(len(f) <= 23 for f in frames(stream))


def test_set_status_and_set_progress_drive_the_hook(tmp_path):
    stage = sample_components.ValSmooth({"window_len": 3})
    calls = []
    stage._report_hook = lambda line, progress: calls.append((line, progress))
    stage.set_status("working")
    stage.set_progress(0.25)
    assert calls == [("working", None), ("working", 0.25)]


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


def test_run_without_a_terminal_draws_no_live_line(tmp_path):
    result = runner.invoke(app, ["run", "--config", str(world(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "\r" not in result.output  # stderr is not a TTY here: live is off
    assert "done: 1 succeeded, 0 failed" in result.output


def test_run_with_live_forced_redraws_in_place(tmp_path):
    result = runner.invoke(app, ["run", "--config", str(world(tmp_path)), "--live"])
    assert result.exit_code == 0, result.output
    assert "\r" in result.output  # in-place redraws happened
    # permanent lines survive the live line (it is cleared before they print)
    assert "done: 1 succeeded, 0 failed" in result.output


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
