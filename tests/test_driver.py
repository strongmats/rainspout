from datetime import date
from pathlib import Path

import pytest
import yaml

import runner_components  # noqa: F401  (importing registers the components)
from rainspout.config import load_config
from rainspout.driver import (
    StopFlag,
    compute_plan,
    drive,
    new_run_id,
    parse_selects,
    resolve_oplog_path,
)
from rainspout.errors import ConfigError, HandlerError
from rainspout.oplog import OpLog
from rainspout.validation import validate_config
from roundtrip_handlers import RtReadingsCsv, write_example_cell

D1, D2, D3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)


def make_run(tmp_path, days=(D1, D2, D3), sensors=("s1", "s2"), mode="retrograde", mutate=None):
    src = tmp_path / "raw"
    for day in days:
        for sensor in sensors:
            write_example_cell(src, str(day), sensor)
    cfg = {
        "run": {"name": "drv_demo", "mode": mode},
        "dimensions": {"day": list(days), "sensor": list(sensors)},
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
    if mode == "realtime":
        cfg["run"]["poll_frequency"] = 0.01
    if mutate:
        mutate(cfg)
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return validate_config(path), OpLog(tmp_path / "oplog.jsonl"), src


def corrupt(src, day, sensor):
    (src / str(day) / f"{sensor}.csv").write_text("total garbage\nnot,csv\n")


def delete(src, day, sensor):
    (src / str(day) / f"{sensor}.csv").unlink()


# -- the plan / delta -----------------------------------------------------------


def test_fresh_plan_runs_everything_cataloged(tmp_path):
    validated, oplog, src = make_run(tmp_path)
    delete(src, D3, "s2")  # never cataloged => never a work item
    plan = compute_plan(validated, oplog, select={})
    assert len(plan.items) == 5
    assert plan.existing == 5
    assert plan.missing == 1
    assert plan.done == plan.failed == 0
    # iteration order: day outer, sensor inner
    assert plan.items[0] == {"day": D1, "sensor": "s1"}
    assert plan.items[1] == {"day": D1, "sensor": "s2"}


def test_delta_is_exists_minus_attempted(tmp_path):
    validated, oplog, src = make_run(tmp_path, days=(D1,), sensors=("s1", "s2"))
    corrupt(src, D1, "s2")
    summary = drive(validated, oplog=oplog, run_id="r1")
    assert (summary.succeeded, summary.failed) == (1, 1)

    plan = compute_plan(validated, oplog, select={})
    assert plan.items == ()  # the failure was ATTEMPTED: not re-run
    assert (plan.done, plan.failed) == (1, 1)


def test_retry_failed_requeues_only_failures(tmp_path):
    validated, oplog, src = make_run(tmp_path, days=(D1,), sensors=("s1", "s2"))
    corrupt(src, D1, "s2")
    drive(validated, oplog=oplog, run_id="r1")
    write_example_cell(src, str(D1), "s2")  # fix the input

    plan = compute_plan(validated, oplog, select={}, retry_failed=True)
    assert plan.items == ({"day": D1, "sensor": "s2"},)
    summary = drive(validated, oplog=oplog, run_id="r2", retry_failed=True)
    assert (summary.succeeded, summary.failed) == (1, 0)


def test_force_rewrite_requeues_successes(tmp_path):
    validated, oplog, _ = make_run(tmp_path, days=(D1,), sensors=("s1",))
    drive(validated, oplog=oplog, run_id="r1")
    plan = compute_plan(validated, oplog, select={}, force_rewrite=True)
    assert plan.items == ({"day": D1, "sensor": "s1"},)
    # and without the flag, nothing
    assert compute_plan(validated, oplog, select={}).items == ()


def test_select_narrows_but_still_respects_the_log(tmp_path):
    validated, oplog, _ = make_run(tmp_path)
    select = parse_selects(["day=2026-01-02"], validated)
    summary = drive(validated, oplog=oplog, run_id="r1", select=select)
    assert summary.succeeded == 2  # both sensors of the selected day

    # selecting the same day again: already attempted => skipped
    plan = compute_plan(validated, oplog, select=select)
    assert plan.items == ()
    assert plan.done == 2
    # the other days were never attempted and are still in the full delta
    assert len(compute_plan(validated, oplog, select={}).items) == 4


def test_select_composes_with_retry_failed(tmp_path):
    # D1 stays healthy so the startup probe (first cataloged cell) passes
    validated, oplog, src = make_run(tmp_path, days=(D1, D2, D3), sensors=("s1",))
    corrupt(src, D2, "s1")
    corrupt(src, D3, "s1")
    drive(validated, oplog=oplog, run_id="r1")
    write_example_cell(src, str(D2), "s1")
    write_example_cell(src, str(D3), "s1")

    select = parse_selects(["day=2026-01-02"], validated)
    plan = compute_plan(validated, oplog, select=select, retry_failed=True)
    assert plan.items == ({"day": D2, "sensor": "s1"},)  # only the SELECTED failure


def test_parse_selects_validates(tmp_path):
    validated, _, _ = make_run(tmp_path)
    with pytest.raises(ConfigError, match="dim=value"):
        parse_selects(["day"], validated)
    with pytest.raises(ConfigError, match="unknown dimension 'ghost'"):
        parse_selects(["ghost=1"], validated)
    with pytest.raises(ConfigError, match="not among the dimension's values"):
        parse_selects(["day=1999-01-01"], validated)


# -- drive: retrograde ---------------------------------------------------------------


def test_retrograde_drains_and_isolates_failures(tmp_path):
    validated, oplog, src = make_run(tmp_path)
    corrupt(src, D3, "s2")
    events = []
    summary = drive(
        validated, oplog=oplog, run_id="r1", notify=lambda kind, p: events.append(kind)
    )
    assert (summary.succeeded, summary.failed) == (5, 1)
    assert summary.cycles == 1
    assert events[0] == "preflight_ok"
    assert events.count("work_item") == 6
    # outputs exist for the five successes
    reader = RtReadingsCsv({"base_dir": tmp_path / "out"})
    data, _ = reader.load_one({"day": D3, "sensor": "s1"})
    assert data == [2.0, 8.0, 3.0]


def test_dry_run_plans_and_executes_nothing(tmp_path):
    validated, oplog, _ = make_run(tmp_path)
    plans = []
    summary = drive(
        validated, oplog=oplog, run_id="r1", dry_run=True,
        notify=lambda kind, p: plans.append(p) if kind == "plan" else None,
    )
    assert summary.dry_run is True
    assert len(plans[0].items) == 6
    assert not (tmp_path / "out").exists()  # nothing executed
    assert oplog.attempted_cells() == frozenset()  # nothing logged


def test_preflight_probe_failure_kills_run_before_work(tmp_path):
    validated, oplog, src = make_run(tmp_path, days=(D1,), sensors=("s1",))
    corrupt(src, D1, "s1")  # the first (only) cataloged cell fails its probe
    with pytest.raises(HandlerError, match="pre-flight probe failed"):
        drive(validated, oplog=oplog, run_id="r1")
    assert oplog.attempted_cells() == frozenset()


def test_preflight_empty_catalog_skips_probe_with_notice(tmp_path):
    validated, oplog, src = make_run(tmp_path, days=(D1,), sensors=("s1",))
    delete(src, D1, "s1")
    notices = []
    summary = drive(
        validated, oplog=oplog, run_id="r1",
        notify=lambda kind, p: notices.append(p) if kind == "preflight_empty" else None,
    )
    assert len(notices) == 1
    assert "structural probe skipped" in notices[0]
    assert (summary.succeeded, summary.failed) == (0, 0)


# -- drive: realtime -------------------------------------------------------------------


def test_realtime_picks_up_new_data_between_cycles(tmp_path):
    validated, oplog, src = make_run(
        tmp_path, days=(D1, D2), sensors=("s1",), mode="realtime"
    )
    delete(src, D2, "s1")  # not there yet

    def on_event(kind, payload):
        if kind == "cycle_end" and payload == 1:
            write_example_cell(src, str(D2), "s1")  # data arrives mid-run

    summary = drive(validated, oplog=oplog, run_id="r1", notify=on_event, max_cycles=3)
    assert summary.succeeded == 2  # D1 in cycle 1, D2 once it appeared
    assert summary.cycles == 3


def test_realtime_never_redoes_attempted_cells(tmp_path):
    validated, oplog, src = make_run(
        tmp_path, days=(D1,), sensors=("s1", "s2"), mode="realtime"
    )
    corrupt(src, D1, "s2")
    summary = drive(validated, oplog=oplog, run_id="r1", max_cycles=3)
    # the failure is attempted once and never hammered on later polls
    assert (summary.succeeded, summary.failed) == (1, 1)


def test_clean_stop_between_work_items(tmp_path):
    validated, oplog, _ = make_run(tmp_path)
    stop = StopFlag()

    def stop_after_first(kind, payload):
        if kind == "work_item":
            stop.set()

    summary = drive(validated, oplog=oplog, run_id="r1", notify=stop_after_first, stop=stop)
    assert summary.stopped is True
    assert summary.succeeded == 1  # the in-flight item finished; nothing else started
    assert len(oplog.attempted_cells()) == 1


# -- identity & log location -------------------------------------------------------------


def test_new_run_id_shape_and_uniqueness():
    a, b = new_run_id("demo"), new_run_id("demo")
    assert a.startswith("demo-")
    assert a != b


def test_oplog_default_location_follows_the_config(tmp_path):
    validated, _, _ = make_run(tmp_path)
    config = load_config(tmp_path / "run.yml")
    resolved = resolve_oplog_path(tmp_path / "run.yml", config)
    assert resolved == tmp_path.resolve() / ".rainspout" / "drv_demo.oplog.jsonl"


def test_oplog_override_resolves_against_config_dir(tmp_path):
    def declare(cfg):
        cfg["run"]["oplog"] = "logs/history.jsonl"

    make_run(tmp_path, mutate=declare)
    config = load_config(tmp_path / "run.yml")
    assert resolve_oplog_path(tmp_path / "run.yml", config) == (
        tmp_path.resolve() / "logs" / "history.jsonl"
    )

    def declare_absolute(cfg):
        cfg["run"]["oplog"] = str(Path("/var/lib/rainspout/history.jsonl"))

    make_run(tmp_path, mutate=declare_absolute)
    config = load_config(tmp_path / "run.yml")
    assert resolve_oplog_path(tmp_path / "run.yml", config) == Path(
        "/var/lib/rainspout/history.jsonl"
    )
