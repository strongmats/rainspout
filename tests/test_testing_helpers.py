import pytest
from pydantic import Field

from rainspout.contracts import (
    Handler,
    LazyReference,
    Stage,
    StageDependencies,
    StageSettings,
)
from rainspout.errors import RainspoutError
from rainspout.testing import assert_roundtrip, from_handler_data, run_stage, values_equal
from roundtrip_handlers import (
    RtDataAlteringCsv,
    RtIgnoringCsv,
    RtMetaAlteringCsv,
    RtReadingsCsv,
    write_example_cell,
)


class EchoSettings(StageSettings):
    scale: float = Field(ge=0, le=100, default=1.0)


class EchoDeps(StageDependencies):
    data: LazyReference


class RtEcho(Stage):
    name = "rt_echo_stage"
    version = "1.0.0"
    settings_model = EchoSettings
    dependencies_model = EchoDeps

    def run(self, deps):
        self.set_status("echoing")
        return [v * self.settings.scale for v in deps.data.get()]


class ProbeSettings(StageSettings):
    day_dim: str = Field(pattern=r"^[a-z_]+$", default="day")


class ProbeDeps(StageDependencies):
    data: LazyReference
    events: Handler


class RtCoordProbe(Stage):
    """Mirrors HANDLER_AUTHORING §6's worked example: reads its coordinate,
    computes unrelated coordinates, and loops the auxiliary handler."""

    name = "rt_coord_probe_stage"
    version = "1.0.0"
    settings_model = ProbeSettings
    dependencies_model = ProbeDeps

    def run(self, deps):
        day = deps.data.coords[self.settings.day_dim]
        gathered = []
        for hour in range(3):  # a "window" is just a loop
            data, _meta = deps.events.load_one({"lat": 1.5, "lon": -2.5, "hour": hour})
            gathered.append(data)
        return {"day": day, "events": gathered, "readings": deps.data.get()}


# -- run_stage ---------------------------------------------------------------------


def test_run_stage_wraps_values_and_stamps_coords():
    out = run_stage(
        RtEcho, {"scale": 2.0}, deps={"data": [1.0, 2.0]}, coords={"day": "2026-01-01"}
    )
    assert out == [2.0, 4.0]


def test_run_stage_with_handler_dep_and_stage_computed_coords():
    out = run_stage(
        RtCoordProbe,
        {"day_dim": "day"},
        deps={"data": [9.0], "events": from_handler_data(["ev"])},
        coords={"day": "2026-01-02", "sensor": "s1"},
    )
    assert out == {"day": "2026-01-02", "events": [["ev"], ["ev"], ["ev"]], "readings": [9.0]}


def test_run_stage_missing_dep_named():
    with pytest.raises(RainspoutError, match="missing a value for dependency 'data'"):
        run_stage(RtEcho, {}, deps={})


def test_run_stage_extra_dep_named():
    with pytest.raises(RainspoutError, match="undeclared dependencies.*extra"):
        run_stage(RtEcho, {}, deps={"data": [1.0], "extra": 1})


def test_run_stage_handler_field_requires_handler():
    with pytest.raises(RainspoutError, match="handler instance or from_handler_data"):
        run_stage(
            RtCoordProbe, {}, deps={"data": [1.0], "events": ["not-a-handler"]},
            coords={"day": "d"},
        )


def test_run_stage_settings_validated_through_real_path():
    from rainspout.errors import SettingsError

    with pytest.raises(SettingsError, match="scale"):
        run_stage(RtEcho, {"scale": 1000}, deps={"data": []})


# -- assert_roundtrip -----------------------------------------------------------------


def test_roundtrip_passes_for_metadata_capable_handler(tmp_path):
    source = tmp_path / "example_data"
    write_example_cell(source)
    assert_roundtrip(
        RtReadingsCsv,
        {"base_dir": source},
        {"day": "2026-01-01", "sensor": "s1"},
        tmp_path / "out",
    )


def test_roundtrip_passes_for_metadata_ignoring_handler(tmp_path):
    source = tmp_path / "example_data"
    write_example_cell(source)
    # never failed merely for not handling metadata
    assert_roundtrip(
        RtIgnoringCsv,
        {"base_dir": source},
        {"day": "2026-01-01", "sensor": "s1"},
        tmp_path / "out",
    )


def test_roundtrip_fails_when_data_altered(tmp_path):
    source = tmp_path / "example_data"
    write_example_cell(source)
    with pytest.raises(AssertionError, match="data was altered"):
        assert_roundtrip(
            RtDataAlteringCsv,
            {"base_dir": source},
            {"day": "2026-01-01", "sensor": "s1"},
            tmp_path / "out",
        )


def test_roundtrip_fails_when_claimed_metadata_altered(tmp_path):
    source = tmp_path / "example_data"
    write_example_cell(source)
    with pytest.raises(AssertionError, match="metadata block was altered"):
        assert_roundtrip(
            RtMetaAlteringCsv,
            {"base_dir": source},
            {"day": "2026-01-01", "sensor": "s1"},
            tmp_path / "out",
        )


def test_roundtrip_requires_base_dir_or_explicit_save_resources(tmp_path):
    from rainspout.testing import _FakeDataHandler

    with pytest.raises(RainspoutError, match="save_resources"):
        assert_roundtrip(_FakeDataHandler, {}, {"key": "k"}, tmp_path)


# -- values_equal ----------------------------------------------------------------------


def test_values_equal_float_tolerance_and_structure():
    assert values_equal([1.0, {"a": 2.0000000001}], [1.0, {"a": 2.0}])
    assert not values_equal([1.0], [1.1])
    assert not values_equal({"a": 1}, {"b": 1})
    assert not values_equal([1, 2], [1, 2, 3])
    assert values_equal((1, "x"), (1, "x"))
    assert not values_equal(True, 1)  # bools are not numbers here
