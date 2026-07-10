"""The run configuration: Pydantic models, YAML loading, dimension expansion.

This module knows the *shape* of a config (docs/CONFIG_AUTHORING.md) and how
to expand dimension ranges into explicit values. Cross-referencing the config
against the registry, the DAG rules, and component models is
:mod:`rainspout.validation`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from .errors import ConfigError, named_offender

# An emptied YAML key (`dependencies:` with nothing left under it) parses as
# None; treat it as the empty mapping it reads as, so validation reaches the
# real check (e.g. "missing dependencies") instead of a type complaint.
_EmptiedKeyIsEmpty = BeforeValidator(lambda value: {} if value is None else value)

_SCALAR_TYPES = (str, int, float, bool, date, datetime)
_STEP_RE = re.compile(r"^(\d+)\s*(d|h|m|s)$")
_STEP_UNITS = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}


class RunBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=100)
    mode: Literal["retrograde", "realtime"]
    poll_frequency: float | None = Field(default=None, gt=0)
    # Where the operational log lives. The log follows the RUN DEFINITION:
    # default is .rainspout/<name>.oplog.jsonl next to the config file, and a
    # relative override here resolves against the config file's directory —
    # never the working directory, so resume/delta cannot silently miss the
    # prior history.
    oplog: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _poll_frequency_iff_realtime(self) -> RunBlock:
        if self.mode == "realtime" and self.poll_frequency is None:
            raise ValueError("run.poll_frequency is required when mode is realtime")
        if self.mode != "realtime" and self.poll_frequency is not None:
            raise ValueError("run.poll_frequency is forbidden unless mode is realtime")
        return self


class RangeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: Any
    stop: Any
    step: Any


class IterationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: list[str] = Field(min_length=1)


class SeedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handler: str
    resources: Annotated[dict[str, Any], _EmptiedKeyIsEmpty] = Field(default_factory=dict)
    dimensions: dict[str, str] = Field(min_length=1)


class HandlerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handler: str
    resources: Annotated[dict[str, Any], _EmptiedKeyIsEmpty] = Field(default_factory=dict)
    dimensions: dict[str, str] | None = None


class DependencyWiring(BaseModel):
    """Exactly one of `from:` (upstream stage or seed entry) or `handler:`."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str | None = Field(default=None, alias="from")
    handler: str | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> DependencyWiring:
        if (self.from_ is None) == (self.handler is None):
            raise ValueError("a dependency is wired with exactly one of 'from' or 'handler'")
        return self


class SaveBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handler: str


class StageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    dependencies: Annotated[dict[str, DependencyWiring], _EmptiedKeyIsEmpty] = Field(
        default_factory=dict
    )
    settings: Annotated[dict[str, Any], _EmptiedKeyIsEmpty] = Field(default_factory=dict)
    save: SaveBlock | None = None


class RootConfig(BaseModel):
    """The whole file: exactly the six top-level keys."""

    model_config = ConfigDict(extra="forbid")

    run: RunBlock
    dimensions: dict[str, list[Any] | RangeSpec] = Field(min_length=1)
    iteration: IterationBlock | None = None
    seed: dict[str, SeedEntry] = Field(min_length=1)
    handlers: Annotated[dict[str, HandlerEntry], _EmptiedKeyIsEmpty] = Field(default_factory=dict)
    stages: dict[str, StageEntry] = Field(min_length=1)


def load_config(path: Path) -> RootConfig:
    """Parse a YAML file into a validated RootConfig, or fail naming the key."""
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must be a YAML mapping of the six top-level keys")
    try:
        return RootConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(named_offender("config", str(path), "key", exc)) from exc


def _parse_step_duration(step: Any, dimension: str) -> timedelta:
    if isinstance(step, str):
        match = _STEP_RE.fullmatch(step.strip())
        if match:
            return timedelta(**{_STEP_UNITS[match.group(2)]: int(match.group(1))})
    raise ConfigError(
        f"dimension '{dimension}': step {step!r} is invalid for a date/datetime range "
        "(use e.g. '1d', '6h', '30m', '15s')"
    )


def _expand_range(dimension: str, spec: RangeSpec) -> tuple[Any, ...]:
    start, stop = spec.start, spec.stop
    if isinstance(start, datetime) and isinstance(stop, datetime):
        step: Any = _parse_step_duration(spec.step, dimension)
    elif isinstance(start, date) and isinstance(stop, date):
        step = _parse_step_duration(spec.step, dimension)
        if step.total_seconds() % 86_400:
            raise ConfigError(
                f"dimension '{dimension}': a date range needs a whole-day step, got {spec.step!r}"
            )
    elif (
        isinstance(start, (int, float))
        and not isinstance(start, bool)
        and isinstance(stop, (int, float))
        and not isinstance(stop, bool)
    ):
        if not isinstance(spec.step, (int, float)) or isinstance(spec.step, bool) or spec.step <= 0:
            raise ConfigError(
                f"dimension '{dimension}': step {spec.step!r} is invalid for a numeric range "
                "(use a positive number)"
            )
        step = spec.step
    else:
        raise ConfigError(
            f"dimension '{dimension}': start/stop must both be numbers, both dates, or both "
            f"datetimes (got {type(start).__name__}/{type(stop).__name__})"
        )
    if stop < start:
        raise ConfigError(f"dimension '{dimension}': stop {stop!r} precedes start {start!r}")

    values: list[Any] = []
    current = start
    while current <= stop:
        values.append(current)
        current = current + step
    return tuple(values)


def _expand_list(dimension: str, values: list[Any]) -> tuple[Any, ...]:
    if not values:
        raise ConfigError(f"dimension '{dimension}': the value list is empty")
    seen: list[Any] = []
    for value in values:
        if not isinstance(value, _SCALAR_TYPES):
            raise ConfigError(
                f"dimension '{dimension}': values must be scalars, got {type(value).__name__}"
            )
        if value in seen:
            raise ConfigError(f"dimension '{dimension}': duplicate value {value!r}")
        seen.append(value)
    return tuple(values)


def expand_dimensions(config: RootConfig) -> dict[str, tuple[Any, ...]]:
    """Expand every dimension to explicit values; handlers never see range syntax."""
    return {
        name: _expand_range(name, spec) if isinstance(spec, RangeSpec) else _expand_list(name, spec)
        for name, spec in config.dimensions.items()
    }


def iteration_order(config: RootConfig) -> tuple[str, ...]:
    """The iteration order: every dimension exactly once (omittable iff one dimension)."""
    dimensions = tuple(config.dimensions)
    if config.iteration is None:
        if len(dimensions) == 1:
            return dimensions
        raise ConfigError(
            "iteration.order is required when there is more than one dimension "
            f"(dimensions: {', '.join(dimensions)})"
        )
    order = tuple(config.iteration.order)
    missing = set(dimensions) - set(order)
    unknown = set(order) - set(dimensions)
    if missing or unknown or len(set(order)) != len(order):
        raise ConfigError(
            "iteration.order must list every dimension exactly once "
            f"(missing: {sorted(missing) or 'none'}, unknown: {sorted(unknown) or 'none'}, "
            f"order given: {list(order)})"
        )
    return order
