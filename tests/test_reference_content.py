"""The reference content run end-to-end THROUGH THE CLI — the machinery-proving
pipeline: metadata-ignoring seed → coordinate-aware stage → stage with a
mid-DAG auxiliary handler dependency and a setup hook that run() requires."""

import json

import yaml
from typer.testing import CliRunner

import reference_content.components  # noqa: F401  (import = registration)
from rainspout.cli.main import app
from rainspout.contracts import Meta

runner = CliRunner()

GAINS = {"alpha": (2.0, 1.0), "bravo": (3.0, 0.0)}  # station -> (gain, offset)


def build_world(tmp_path):
    raw = tmp_path / "raw"
    calib = tmp_path / "calib"
    for node in ("alpha", "bravo"):
        for tick in range(3):
            path = raw / node / f"{tick}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{10.0 * tick}\n")
        gain, offset = GAINS[node]
        calib.mkdir(exist_ok=True)
        (calib / f"{node}.json").write_text(
            json.dumps({"data": {"gain": gain, "offset": offset}, "meta": None})
        )
    cfg = {
        "run": {"name": "reference_run", "mode": "retrograde"},
        "dimensions": {
            "tick": {"start": 0, "stop": 2, "step": 1},
            "node": ["alpha", "bravo"],
        },
        "iteration": {"order": ["tick", "node"]},
        "seed": {
            "raw": {
                "handler": "ref_lines_txt",
                "resources": {"base_dir": str(raw)},
                "dimensions": {"tick": "tick", "node": "node"},
            }
        },
        "handlers": {
            "calib": {
                "handler": "ref_table_json",
                "resources": {"base_dir": str(calib)},
                # stage-callable: no dimensions map, on purpose
            },
            "out": {
                "handler": "ref_grid_json",
                "resources": {"base_dir": str(tmp_path / "out")},
                "dimensions": {"tick": "tick", "node": "node"},
            },
        },
        "stages": {
            "snip": {
                "stage": "ref_snip",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {"tick_dim": "tick"},
            },
            "enrich": {
                "stage": "ref_enrich",
                "dependencies": {"data": {"from": "snip"}, "calibration": {"handler": "calib"}},
                "settings": {"node_dim": "node"},
                "save": {"handler": "out"},
            },
        },
    }
    path = tmp_path / "reference_run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_reference_pipeline_end_to_end_via_cli(tmp_path):
    config = build_world(tmp_path)

    validated = runner.invoke(app, ["validate", "--config", str(config)])
    assert validated.exit_code == 0, validated.output

    result = runner.invoke(app, ["run", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "pre-flight: seed raw ✓" in result.output
    assert "plan: 6 work items — 6 to run, 0 done, 0 previously failed" in result.output
    assert "done: 6 succeeded, 0 failed" in result.output

    # value math: raw 10t --snip--> 10t - t --enrich--> (9t)*gain + offset
    for node in ("alpha", "bravo"):
        gain, offset = GAINS[node]
        for tick in range(3):
            payload = json.loads((tmp_path / "out" / f"{tick}_{node}.json").read_text())
            assert payload["data"] == [9.0 * tick * gain + offset]
            meta = Meta.model_validate(payload["meta"])
            # the seed IGNORES metadata, so provenance starts fresh here:
            # exactly this run's two stages, in order, settings recorded
            assert [e.stage_name for e in meta.provenance] == ["ref_snip", "ref_enrich"]
            assert meta.provenance[0].settings_used == {"tick_dim": "tick"}
            assert meta.provenance[1].settings_used == {"node_dim": "node"}
            assert meta.coords == {"tick": str(tick), "node": node}

    # resume: everything attempted, nothing re-runs
    again = runner.invoke(app, ["run", "--config", str(config)])
    assert "plan: 6 work items — 0 to run, 6 done, 0 previously failed" in again.output


def test_reference_package_is_itself_conforming(tmp_path):
    result = runner.invoke(app, ["test-package", "reference_content", "--static-only"])
    assert result.exit_code == 0, result.output
    for component in (
        "ref_snip",
        "ref_enrich",
        "ref_lines_txt",
        "ref_table_json",
        "ref_grid_json",
    ):
        assert f"{component} ✓" in result.output


def test_setup_ordering_is_load_bearing(tmp_path):
    # the observable setup exercise: bypass prepare_stages and the guard trips
    import reference_content.stages.ref_enrich.stage as enrich_mod
    from rainspout.contracts import StageDependencies

    stage = enrich_mod.RefEnrich({"node_dim": "node"})
    with_no_setup = type(stage).dependencies_model
    assert issubclass(with_no_setup, StageDependencies)
    from rainspout.contracts import LazyReference
    from rainspout.testing import from_handler_data

    deps = with_no_setup(
        data=LazyReference.from_value([1.0], coords={"node": "alpha"}),
        calibration=from_handler_data({"gain": 1.0, "offset": 0.0}),
    )
    import pytest

    with pytest.raises(Exception, match="setup"):
        stage.run(deps)
    stage.setup()
    assert stage.run(deps) == [1.0]
