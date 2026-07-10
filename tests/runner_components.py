"""Sample stages and a misbehaving save target for the runner tests."""

from datetime import date

from pydantic import Field

from rainspout.contracts import (
    Handler,
    HandlerResources,
    LazyReference,
    Stage,
    StageDependencies,
    StageError,
    StageSettings,
)


class ScaleSettings(StageSettings):
    factor: float = Field(ge=0, le=10)


class ScaleDeps(StageDependencies):
    data: LazyReference


class RunScale(Stage):
    name = "run_scale"
    version = "1.2.0"
    settings_model = ScaleSettings
    dependencies_model = ScaleDeps

    def run(self, deps):
        values = deps.data.get()
        self.set_status(f"scaled {len(values)} values at {deps.data.coords['day']}")
        return [value * self.settings.factor for value in values]


class TotalSettings(StageSettings):
    fail_above: float = Field(ge=0, le=1e9, default=1e9)
    warn_above: float = Field(ge=0, le=1e9, default=1e9)


class TotalDeps(StageDependencies):
    data: LazyReference


class RunTotal(Stage):
    name = "run_total"
    version = "0.3.1"
    settings_model = TotalSettings
    dependencies_model = TotalDeps

    def run(self, deps):
        total = sum(deps.data.get())
        if total > self.settings.fail_above:
            raise StageError(f"total {total} exceeds fail_above")
        if total > self.settings.warn_above:
            self.add_warning(f"total {total} exceeds warn_above")
        self.set_status(f"totaled to {total}")
        return [total]


class SetupProbeSettings(StageSettings):
    pass


class SetupProbeDeps(StageDependencies):
    data: LazyReference


class RunSetupProbe(Stage):
    name = "run_setup_probe"
    version = "1.0.0"
    settings_model = SetupProbeSettings
    dependencies_model = SetupProbeDeps

    def setup(self):
        self.setup_calls = getattr(self, "setup_calls", 0) + 1

    def run(self, deps):
        self.set_status("probed")
        return deps.data.get()


class BadSaveResources(HandlerResources):
    base_dir: str = "unused"


class RunBadSave(Handler):
    """A save target that always fails to write."""

    name = "run_bad_save"
    resources_model = BadSaveResources
    dimension_roles = ("day", "sensor")
    dimension_types = {"day": date, "sensor": str}

    def _load_cell(self, coords):
        raise OSError("nothing here to load")

    def _save_cell(self, coords, data, meta):
        raise OSError("disk full")

    def _catalog_cells(self, spec):
        return iter(())
