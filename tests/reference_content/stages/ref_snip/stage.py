"""Coordinate-AWARE stage: its science depends on where it is on the grid.

Reads its work-item coordinate through the recommended pattern — the
dimension name arrives as a bounded setting, never hardcoded."""

from pydantic import Field

from rainspout.contracts import (
    LazyReference,
    Stage,
    StageDependencies,
    StageError,
    StageSettings,
)


class RefSnipSettings(StageSettings):
    tick_dim: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=50, default="tick")


class RefSnipDeps(StageDependencies):
    data: LazyReference


class RefSnip(Stage):
    name = "ref_snip"
    version = "1.0.0"
    settings_model = RefSnipSettings
    dependencies_model = RefSnipDeps

    def run(self, deps):
        coords = deps.data.coords
        if self.settings.tick_dim not in coords:
            raise StageError(
                f"ref_snip: coordinate has no '{self.settings.tick_dim}' key "
                f"(has: {sorted(coords)}); set tick_dim to your config's dimension name"
            )
        tick = int(coords[self.settings.tick_dim])
        values = deps.data.get()
        self.set_status(f"snipping {len(values)} values at tick {tick}")
        return [value - tick for value in values]
