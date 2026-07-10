"""The runner: one work item through the DAG, end to end.

Per work item the runner seeds a coordinate-stamped lazy reference, injects
each stage's declared dependencies (upstream references for `from:`, handler
instances for `handler:`), executes the chain in topological order, performs
config-designated saves with the accumulated provenance chain, and writes the
operational log. A stage failure (or a failure saving its output) fails this
one work item only — recorded, downstream skipped — and never propagates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .contracts import LazyReference, Meta, ProvenanceEntry, Stage
from .oplog import OpLog, StageRecord, WorkItemRecord
from .provenance import provenance_entry
from .validation import ValidatedRun


@dataclass(frozen=True)
class StageOutcome:
    instance: str
    status: Literal["succeeded", "failed"]
    status_line: str
    warnings: tuple[str, ...]
    error: str | None = None
    saved_to: str | None = None  # the handler instance a config-designated save wrote to


@dataclass(frozen=True)
class WorkItemResult:
    cell_id: str
    coords: dict[str, Any]
    status: Literal["succeeded", "failed"]
    stages: tuple[StageOutcome, ...]
    failed_stage: str | None = None


def cell_id(coords: Mapping[str, Any], order: tuple[str, ...]) -> str:
    """The canonical serialized coordinate — the per-work-item sub-key to run_id."""
    return "|".join(f"{dimension}={coords[dimension]}" for dimension in order)


def prepare_stages(validated: ValidatedRun) -> None:
    """Run every stage's setup() once, after validation, before any work item."""
    for instance_name in validated.stage_order:
        validated.stage_instances[instance_name].setup()


def _fresh_warnings(stage: Stage, offset: int) -> tuple[str, ...]:
    return tuple(stage.warnings[offset:])


def run_work_item(
    validated: ValidatedRun,
    coords: Mapping[str, Any],
    *,
    run_id: str,
    oplog: OpLog,
) -> WorkItemResult:
    """Execute the whole stage chain for one point in the dimension space."""
    config = validated.config
    coords = dict(coords)
    cid = cell_id(coords, validated.order)

    # The seed cell: loaded lazily (and once), coordinate stamped by us.
    seed_entry = config.seed[validated.seed_name]
    seed_coords = {role: coords[dimension] for role, dimension in seed_entry.dimensions.items()}
    seed_cache: dict[str, tuple[Any, Meta]] = {}

    def seed_cell() -> tuple[Any, Meta]:
        if "cell" not in seed_cache:
            seed_cache["cell"] = validated.seed_handler.load_one(seed_coords)
        return seed_cache["cell"]

    def base_meta() -> Meta:
        """The provenance base: the seed cell's block if it was loaded, else fresh."""
        if "cell" in seed_cache:
            return seed_cache["cell"][1]
        return Meta.fresh(coords=coords, run_id=run_id)

    outputs: dict[str, LazyReference] = {
        validated.seed_name: LazyReference(lambda: seed_cell()[0], coords=coords)
    }

    outcomes: list[StageOutcome] = []
    chain: list[ProvenanceEntry] = []

    for instance_name in validated.stage_order:
        stage = validated.stage_instances[instance_name]
        stage_entry = config.stages[instance_name]
        warning_offset = len(stage.warnings)
        started_at = datetime.now(UTC)

        field_values: dict[str, Any] = {}
        for field_name, wiring in stage_entry.dependencies.items():
            if wiring.from_ is not None:
                field_values[field_name] = outputs[wiring.from_]
            elif wiring.handler is not None:
                field_values[field_name] = validated.handler_instances[wiring.handler]
        deps = type(stage).dependencies_model(**field_values)

        try:
            output = stage.run(deps)
            chain.append(provenance_entry(stage, warnings=_fresh_warnings(stage, warning_offset)))
            if stage_entry.save is not None:
                target_name = stage_entry.save.handler
                target_map = config.handlers[target_name].dimensions or {}
                spec = {role: (coords[dimension],) for role, dimension in target_map.items()}
                meta = Meta(
                    run_id=run_id,
                    coords=coords,
                    provenance=(*base_meta().provenance, *chain),
                )
                try:
                    validated.handler_instances[target_name].save(spec, output, meta)
                except Exception as exc:
                    raise RuntimeError(
                        f"save through handler instance '{target_name}' failed: {exc}"
                    ) from exc
        except Exception as exc:  # noqa: BLE001 — per-work-item isolation is the contract
            error = f"{type(exc).__name__}: {exc}"
            warnings = _fresh_warnings(stage, warning_offset)
            outcomes.append(
                StageOutcome(instance_name, "failed", stage.status(), warnings, error)
            )
            finished_at = datetime.now(UTC)
            oplog.append(
                StageRecord(
                    run_id=run_id, cell_id=cid, stage=instance_name, status="failed",
                    status_line=stage.status(), warnings=warnings, error=error,
                    started_at=started_at, finished_at=finished_at,
                )
            )
            oplog.append(
                WorkItemRecord(
                    run_id=run_id, cell_id=cid, status="failed",
                    failed_stage=instance_name, finished_at=finished_at,
                )
            )
            return WorkItemResult(
                cell_id=cid, coords=coords, status="failed",
                stages=tuple(outcomes), failed_stage=instance_name,
            )

        warnings = _fresh_warnings(stage, warning_offset)
        outcomes.append(
            StageOutcome(
                instance_name, "succeeded", stage.status(), warnings,
                saved_to=stage_entry.save.handler if stage_entry.save else None,
            )
        )
        oplog.append(
            StageRecord(
                run_id=run_id, cell_id=cid, stage=instance_name, status="succeeded",
                status_line=stage.status(), warnings=warnings,
                started_at=started_at, finished_at=datetime.now(UTC),
            )
        )
        outputs[instance_name] = LazyReference.from_value(output, coords=coords)

    oplog.append(
        WorkItemRecord(
            run_id=run_id, cell_id=cid, status="succeeded", finished_at=datetime.now(UTC)
        )
    )
    return WorkItemResult(cell_id=cid, coords=coords, status="succeeded", stages=tuple(outcomes))
