"""The two adversarial exercises in one stage:

- a MID-DAG auxiliary `handler:` dependency, called with STAGE-COMPUTED
  coordinates in the handler's own unrelated vocabulary ('station'), and
- an OBSERVABLE setup hook: `run` refuses to work unless `setup()` fired
  first, so any break in the setup-before-work-items ordering fails loudly
  in the end-to-end run.
"""

from pydantic import Field

from rainspout.contracts import (
    Handler,
    LazyReference,
    Stage,
    StageDependencies,
    StageError,
    StageSettings,
)


class RefEnrichSettings(StageSettings):
    node_dim: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=50, default="node")


class RefEnrichDeps(StageDependencies):
    data: LazyReference
    calibration: Handler


class RefEnrich(Stage):
    name = "ref_enrich"
    version = "1.0.0"
    settings_model = RefEnrichSettings
    dependencies_model = RefEnrichDeps

    def setup(self):
        # the observable exercise: a flag run() REQUIRES
        self.ready = True
        self.setup_calls = getattr(self, "setup_calls", 0) + 1

    def run(self, deps):
        if not getattr(self, "ready", False):
            raise StageError("ref_enrich: setup() never ran — the setup ordering is broken")
        station = str(deps.data.coords[self.settings.node_dim])
        table, _meta = deps.calibration.load_one({"station": station})
        if "gain" not in table or "offset" not in table:
            raise StageError(f"ref_enrich: calibration for '{station}' lacks gain/offset")
        values = deps.data.get()
        self.set_status(f"enriching {len(values)} values with station '{station}'")
        return [value * table["gain"] + table["offset"] for value in values]
