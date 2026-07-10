"""Sample components used by the validation and CLI tests.

Importing this module registers them (the same gesture a content package's
collector module performs).
"""

from datetime import date
from typing import Literal

from pydantic import Field

from rainspout.contracts import (
    Handler,
    HandlerResources,
    LazyReference,
    Stage,
    StageDependencies,
    StageSettings,
)


class ReadingsResources(HandlerResources):
    base_dir: str = Field(min_length=1)


class ValReadingsCsv(Handler):
    name = "val_readings_csv"
    resources_model = ReadingsResources
    dimension_roles = ("day", "sensor")
    dimension_types = {"day": date, "sensor": str}

    def _load_cell(self, coords):
        return [1.0], {"coords": dict(coords)}

    def _save_cell(self, coords, data, meta):
        pass

    def _catalog_cells(self, spec):
        return iter(())


class ValEventsJson(Handler):
    name = "val_events_json"
    resources_model = ReadingsResources
    dimension_roles = ("lat", "lon", "hour")
    dimension_types = {"lat": float, "lon": float, "hour": int}

    def _load_cell(self, coords):
        return [], {}

    def _save_cell(self, coords, data, meta):
        pass

    def _catalog_cells(self, spec):
        return iter(())


class SmoothSettings(StageSettings):
    window_len: int = Field(ge=1, le=100)
    method: Literal["mean", "median"] = "mean"


class SmoothDeps(StageDependencies):
    data: LazyReference


class ValSmooth(Stage):
    name = "val_smooth"
    version = "1.0.0"
    settings_model = SmoothSettings
    dependencies_model = SmoothDeps

    def run(self, deps):
        return deps.data.get()


class DetectSettings(StageSettings):
    threshold: float = Field(ge=0, le=100)


class DetectDeps(StageDependencies):
    data: LazyReference
    events: Handler


class ValDetect(Stage):
    name = "val_detect"
    version = "1.0.0"
    settings_model = DetectSettings
    dependencies_model = DetectDeps

    def run(self, deps):
        return deps.data.get()
