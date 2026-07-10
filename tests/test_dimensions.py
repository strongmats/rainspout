from datetime import date, datetime

import pytest

from rainspout.config import (
    IterationBlock,
    RangeSpec,
    RootConfig,
    RunBlock,
    SeedEntry,
    StageEntry,
    expand_dimensions,
    iteration_order,
)
from rainspout.errors import ConfigError


def config_with(dimensions, iteration=None):
    return RootConfig(
        run=RunBlock(name="demo", mode="retrograde"),
        dimensions=dimensions,
        iteration=IterationBlock(order=iteration) if iteration else None,
        seed={"raw": SeedEntry(handler="h", dimensions={"r": next(iter(dimensions))})},
        stages={"s": StageEntry(stage="x")},
    )


def test_date_range_inclusive():
    cfg = config_with(
        {"day": RangeSpec(start=date(2026, 1, 1), stop=date(2026, 1, 3), step="1d")}
    )
    assert expand_dimensions(cfg)["day"] == (
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    )


def test_datetime_range_hourly():
    cfg = config_with(
        {
            "t": RangeSpec(
                start=datetime(2026, 1, 1, 0), stop=datetime(2026, 1, 1, 2), step="1h"
            )
        }
    )
    assert len(expand_dimensions(cfg)["t"]) == 3


def test_numeric_range():
    cfg = config_with({"n": RangeSpec(start=0, stop=10, step=5)})
    assert expand_dimensions(cfg)["n"] == (0, 5, 10)


def test_stop_before_start_rejected():
    cfg = config_with({"n": RangeSpec(start=10, stop=0, step=1)})
    with pytest.raises(ConfigError, match="precedes"):
        expand_dimensions(cfg)


def test_bad_duration_step_rejected():
    cfg = config_with({"day": RangeSpec(start=date(2026, 1, 1), stop=date(2026, 1, 2), step="1x")})
    with pytest.raises(ConfigError, match="step '1x' is invalid"):
        expand_dimensions(cfg)


def test_subday_step_on_date_range_rejected():
    cfg = config_with({"day": RangeSpec(start=date(2026, 1, 1), stop=date(2026, 1, 2), step="6h")})
    with pytest.raises(ConfigError, match="whole-day"):
        expand_dimensions(cfg)


def test_nonpositive_numeric_step_rejected():
    cfg = config_with({"n": RangeSpec(start=0, stop=10, step=0)})
    with pytest.raises(ConfigError, match="positive"):
        expand_dimensions(cfg)


def test_mismatched_range_types_rejected():
    cfg = config_with({"n": RangeSpec(start=date(2026, 1, 1), stop=5, step=1)})
    with pytest.raises(ConfigError, match="both"):
        expand_dimensions(cfg)


def test_list_form_preserves_order():
    cfg = config_with({"sensor": ["bravo", "alpha"]})
    assert expand_dimensions(cfg)["sensor"] == ("bravo", "alpha")


def test_duplicate_list_values_rejected():
    cfg = config_with({"sensor": ["a", "a"]})
    with pytest.raises(ConfigError, match="duplicate"):
        expand_dimensions(cfg)


def test_empty_list_rejected():
    cfg = config_with({"sensor": []})
    with pytest.raises(ConfigError, match="empty"):
        expand_dimensions(cfg)


def test_non_scalar_list_value_rejected():
    cfg = config_with({"sensor": [["nested"]]})
    with pytest.raises(ConfigError, match="scalar"):
        expand_dimensions(cfg)


def test_iteration_omittable_with_single_dimension():
    cfg = config_with({"day": [date(2026, 1, 1)]})
    assert iteration_order(cfg) == ("day",)


def test_iteration_required_with_two_dimensions():
    cfg = config_with({"day": [date(2026, 1, 1)], "sensor": ["a"]})
    with pytest.raises(ConfigError, match="iteration.order is required"):
        iteration_order(cfg)


def test_iteration_must_cover_every_dimension_once():
    cfg = config_with({"day": [date(2026, 1, 1)], "sensor": ["a"]}, iteration=["day"])
    with pytest.raises(ConfigError, match="missing.*sensor"):
        iteration_order(cfg)
    cfg = config_with({"day": [date(2026, 1, 1)]}, iteration=["day", "ghost"])
    with pytest.raises(ConfigError, match="unknown.*ghost"):
        iteration_order(cfg)


def test_iteration_order_respected():
    cfg = config_with(
        {"day": [date(2026, 1, 1)], "sensor": ["a"]}, iteration=["sensor", "day"]
    )
    assert iteration_order(cfg) == ("sensor", "day")
