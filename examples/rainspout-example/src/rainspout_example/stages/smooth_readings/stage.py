"""Tutorial 2's stage, verbatim: a thin orchestrator around science.py."""

from typing import Literal

from pydantic import Field

from rainspout.contracts import (
    LazyReference,
    Stage,
    StageDependencies,
    StageError,
    StageSettings,
)

from .science import smooth


class SmoothReadingsSettings(StageSettings):
    window_len: int = Field(ge=1, le=10_000)
    method: Literal["mean", "median"] = "mean"


class SmoothReadingsDependencies(StageDependencies):
    data: LazyReference


class SmoothReadings(Stage):
    name = "smooth_readings"
    version = "1.0.0"
    settings_model = SmoothReadingsSettings
    dependencies_model = SmoothReadingsDependencies

    def run(self, deps: SmoothReadingsDependencies) -> list[float]:
        values = deps.data.get()  # pull once
        if not isinstance(values, list):  # cheap shape check only
            raise StageError(
                f"smooth_readings expected list, got {type(values).__name__}"
            )
        self.set_status(f"smoothing {len(values)} values ({self.settings.method})")
        try:
            return smooth(values, self.settings.window_len, self.settings.method)
        except ValueError as e:
            raise StageError(f"smooth_readings: {e}") from e
