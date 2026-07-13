from datetime import date

import pytest
import yaml

import runner_components  # noqa: F401  (importing registers the components)
from rainspout.oplog import OpLog, StageRecord, WorkItemRecord
from rainspout.runner import cell_id, prepare_stages, run_work_item
from rainspout.validation import validate_config
from roundtrip_handlers import RtReadingsCsv, write_example_cell

DAY = date(2026, 1, 1)


def base_config(src, out):
    return {
        "run": {"name": "runner_demo", "mode": "retrograde"},
        "dimensions": {"day": [DAY], "sensor": ["s1"]},
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
                "resources": {"base_dir": str(out)},
                "dimensions": {"day": "day", "sensor": "sensor"},
            },
            "out2": {
                "handler": "rt_readings_csv",
                "resources": {"base_dir": str(out) + "_2"},
                "dimensions": {"day": "day", "sensor": "sensor"},
            },
        },
        "stages": {
            "scale": {
                "stage": "run_scale",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {"factor": 2.0},
                "save": {"handler": "out"},          # the mid-DAG save
            },
            "total": {
                "stage": "run_total",
                "dependencies": {"data": {"from": "scale"}},
                "settings": {},
                "save": {"handler": "out2"},         # the terminal save
            },
        },
    }


def make_run(tmp_path, mutate=None):
    src = tmp_path / "raw"
    out = tmp_path / "out"
    write_example_cell(src)  # values 1.0, 4.0, 1.5
    cfg = base_config(src, out)
    if mutate:
        mutate(cfg)
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return validate_config(path), OpLog(tmp_path / "oplog.jsonl"), out


COORDS = {"day": DAY, "sensor": "s1"}


def test_work_item_end_to_end_with_mid_dag_save(tmp_path):
    validated, oplog, out = make_run(tmp_path)
    prepare_stages(validated)
    result = run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)

    assert result.status == "succeeded"
    assert result.cell_id == "day=2026-01-01|sensor=s1"
    assert [s.instance for s in result.stages] == ["scale", "total"]
    assert result.stages[0].status_line == "scaled 3 values at 2026-01-01"

    # the mid-DAG save persisted scale's output...
    reader = RtReadingsCsv({"base_dir": out})
    data, meta = reader.load_one(COORDS)
    assert data == [2.0, 8.0, 3.0]
    # ...with the provenance chain up to that point (scale only)
    assert [e.stage_name for e in meta.provenance] == ["run_scale"]
    assert meta.provenance[0].stage_version == "1.2.0"
    assert meta.provenance[0].settings_used == {"factor": 2.0}
    assert len(meta.provenance[0].code_hash) == 64
    assert meta.run_id == "run-1"
    assert meta.coords == {"day": "2026-01-01", "sensor": "s1"}

    # the terminal save carries the full chain, in order
    reader2 = RtReadingsCsv({"base_dir": str(out) + "_2"})
    data2, meta2 = reader2.load_one(COORDS)
    assert data2 == [13.0]
    assert [e.stage_name for e in meta2.provenance] == ["run_scale", "run_total"]


def test_oplog_records_verified(tmp_path):
    validated, oplog, _ = make_run(tmp_path)
    run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)

    records = oplog.records()
    stage_records = [r for r in records if isinstance(r, StageRecord)]
    item_records = [r for r in records if isinstance(r, WorkItemRecord)]
    assert [(r.stage, r.status) for r in stage_records] == [
        ("scale", "succeeded"),
        ("total", "succeeded"),
    ]
    assert all(r.cell_id == "day=2026-01-01|sensor=s1" for r in records)
    assert all(r.run_id == "run-1" for r in records)
    assert [r.status for r in item_records] == ["succeeded"]
    assert oplog.attempted_cells() == {"day=2026-01-01|sensor=s1"}
    assert oplog.failed_cells() == frozenset()


def test_failure_isolated_downstream_skipped(tmp_path):
    def make_total_fail(cfg):
        cfg["stages"]["total"]["settings"] = {"fail_above": 1.0}

    validated, oplog, out = make_run(tmp_path, make_total_fail)
    result = run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)

    assert result.status == "failed"
    assert result.failed_stage == "total"
    assert "exceeds fail_above" in result.stages[-1].error
    # the mid-DAG save from the SUCCEEDED stage still happened
    data, _ = RtReadingsCsv({"base_dir": out}).load_one(COORDS)
    assert data == [2.0, 8.0, 3.0]
    # oplog: scale succeeded, total failed, work item failed
    stage_status = [
        (r.stage, r.status) for r in oplog.records() if isinstance(r, StageRecord)
    ]
    assert stage_status == [("scale", "succeeded"), ("total", "failed")]
    assert oplog.failed_cells() == {"day=2026-01-01|sensor=s1"}
    # the failure never propagates as an exception — it was returned


def test_save_failure_fails_the_work_item(tmp_path):
    def save_to_bad_target(cfg):
        cfg["handlers"]["bad"] = {
            "handler": "run_bad_save",
            "resources": {},
            "dimensions": {"day": "day", "sensor": "sensor"},
        }
        cfg["stages"]["scale"]["save"] = {"handler": "bad"}

    validated, oplog, _ = make_run(tmp_path, save_to_bad_target)
    result = run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)
    assert result.status == "failed"
    assert result.failed_stage == "scale"
    assert "save through handler instance 'bad' failed" in result.stages[0].error
    assert "disk full" in result.stages[0].error


def test_warnings_recorded_per_work_item_not_cumulative(tmp_path):
    def warn_always(cfg):
        cfg["dimensions"]["day"] = [DAY, date(2026, 1, 2)]
        cfg["stages"]["total"]["settings"] = {"warn_above": 1.0}

    validated, oplog, _ = make_run(tmp_path, warn_always)
    write_example_cell(tmp_path / "raw", "2026-01-02", "s1")

    run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)
    run_work_item(
        validated, {"day": date(2026, 1, 2), "sensor": "s1"}, run_id="run-1", oplog=oplog
    )
    total_records = [
        r for r in oplog.records() if isinstance(r, StageRecord) and r.stage == "total"
    ]
    # one warning each — the second work item did not inherit the first's
    assert [len(r.warnings) for r in total_records] == [1, 1]
    # and the warning landed in the saved provenance too
    _, meta = RtReadingsCsv({"base_dir": str(tmp_path / "out") + "_2"}).load_one(COORDS)
    assert meta.provenance[-1].warnings != ()


def test_foreign_seed_data_gets_fresh_provenance_base(tmp_path):
    # the example cell is plain CSV (no meta line): the chain must start fresh,
    # containing exactly the stages of this run
    validated, oplog, out = make_run(tmp_path)
    run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)
    _, meta = RtReadingsCsv({"base_dir": out}).load_one(COORDS)
    assert [e.stage_name for e in meta.provenance] == ["run_scale"]


def test_chained_runs_extend_provenance(tmp_path):
    # run once; then a second config seeds from the first run's output —
    # its provenance must EXTEND the existing chain, not replace it
    validated, oplog, out = make_run(tmp_path)
    run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)

    def seed_from_out(cfg):
        cfg["seed"]["raw"]["resources"] = {"base_dir": str(out)}
        cfg["stages"]["scale"]["save"] = {"handler": "out2"}
        del cfg["stages"]["total"]

    src2 = tmp_path / "unused"
    write_example_cell(src2)
    cfg = base_config(src2, tmp_path / "out_b")
    seed_from_out(cfg)
    path = tmp_path / "run2.yml"
    path.write_text(yaml.safe_dump(cfg))
    validated2 = validate_config(path)
    run_work_item(
        validated2, COORDS, run_id="run-2", oplog=OpLog(tmp_path / "oplog2.jsonl")
    )
    _, meta = RtReadingsCsv({"base_dir": str(tmp_path / "out_b") + "_2"}).load_one(COORDS)
    assert [e.stage_name for e in meta.provenance] == ["run_scale", "run_scale"]
    assert meta.run_id == "run-2"


def test_prepare_stages_runs_setup_once_per_call(tmp_path):
    def swap_stage(cfg):
        cfg["stages"]["scale"]["stage"] = "run_setup_probe"
        cfg["stages"]["scale"]["settings"] = {}

    validated, _, _ = make_run(tmp_path, swap_stage)
    prepare_stages(validated)
    stage = validated.stage_instances["scale"]
    assert stage.setup_calls == 1
    prepare_stages(validated)  # setup must be idempotent-safe
    assert stage.setup_calls == 2


def test_cell_id_follows_iteration_order():
    assert cell_id({"a": 1, "b": "x"}, ("b", "a")) == "b=x|a=1"


def test_handler_dependency_injected(tmp_path):
    # a mid-DAG auxiliary: RtCoordProbe-style stages are covered in the
    # testing-helper suite; here we prove the runner injects the instance
    from rainspout.contracts import Handler, Stage, StageDependencies, StageSettings
    from rainspout.contracts import LazyReference as LR

    class AuxDeps(StageDependencies):
        data: LR
        side: Handler

    class AuxSettings(StageSettings):
        pass

    class RunAuxProbe(Stage):
        name = "run_aux_probe"
        version = "1.0.0"
        settings_model = AuxSettings
        dependencies_model = AuxDeps

        def run(self, deps):
            self.set_status("checking injected handler")
            data, _ = deps.side.load_one({"day": deps.data.coords["day"], "sensor": "s1"})
            return data

    def add_aux(cfg):
        cfg["handlers"]["side"] = {
            "handler": "rt_readings_csv",
            "resources": {"base_dir": str(tmp_path / "raw")},
        }
        cfg["stages"]["total"] = {
            "stage": "run_aux_probe",
            "dependencies": {"data": {"from": "scale"}, "side": {"handler": "side"}},
            "settings": {},
        }

    validated, oplog, _ = make_run(tmp_path, add_aux)
    result = run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)
    assert result.status == "succeeded"


def test_outputs_released_after_last_consumer(tmp_path):
    # memory contract: an intermediate output is freed as soon as its last
    # `from:` consumer has run — not held for the whole work item. A stage
    # downstream of the release point observes the weakref dying; the
    # terminal save still carries the full provenance chain even though the
    # seed cell's data was freed (its Meta is retained).
    import gc
    import weakref

    from rainspout.contracts import LazyReference as LR
    from rainspout.contracts import Stage, StageDependencies, StageSettings

    probe = {}

    class ChainDeps(StageDependencies):
        data: LR

    class ChainSettings(StageSettings):
        pass

    class Payload(list):
        pass  # plain lists reject weakrefs; a subclass carries __weakref__

    class RunBox(Stage):
        name = "run_box"
        version = "1.0.0"
        settings_model = ChainSettings
        dependencies_model = ChainDeps

        def run(self, deps):
            out = Payload(deps.data.get())
            probe["boxed"] = weakref.ref(out)
            self.set_status("boxed")
            return out

    class RunRelay(Stage):
        name = "run_relay"
        version = "1.0.0"
        settings_model = ChainSettings
        dependencies_model = ChainDeps

        def run(self, deps):
            self.set_status("relayed")
            return list(deps.data.get())

    class RunObserve(Stage):
        name = "run_observe"
        version = "1.0.0"
        settings_model = ChainSettings
        dependencies_model = ChainDeps

        def run(self, deps):
            gc.collect()
            probe["boxed_alive_downstream"] = probe["boxed"]() is not None
            self.set_status("observed")
            return list(deps.data.get())

    def chain3(cfg):
        cfg["stages"] = {
            "box": {
                "stage": "run_box",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {},
            },
            "relay": {  # the LAST consumer of box's output
                "stage": "run_relay",
                "dependencies": {"data": {"from": "box"}},
                "settings": {},
            },
            "observe": {
                "stage": "run_observe",
                "dependencies": {"data": {"from": "relay"}},
                "settings": {},
                "save": {"handler": "out2"},
            },
        }

    validated, oplog, _ = make_run(tmp_path, chain3)
    result = run_work_item(validated, COORDS, run_id="run-1", oplog=oplog)
    assert result.status == "succeeded"
    # box's output was freed before observe ran (relay was its last consumer)
    assert probe["boxed_alive_downstream"] is False
    gc.collect()
    assert probe["boxed"]() is None
    # the terminal save still assembled the full chain after the seed's data
    # was released (base_meta reads the retained Meta, not the data)
    _, meta = RtReadingsCsv({"base_dir": str(tmp_path / "out") + "_2"}).load_one(COORDS)
    assert [e.stage_name for e in meta.provenance] == ["run_box", "run_relay", "run_observe"]


def test_settings_error_message_unaffected_by_runner(tmp_path):
    # sanity: nothing in the runner path weakens validation-time guarantees
    with pytest.raises(Exception, match="factor"):
        make_run(tmp_path, lambda cfg: cfg["stages"]["scale"].update(settings={"factor": 99}))
