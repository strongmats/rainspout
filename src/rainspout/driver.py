"""The driver: enumerate work items, subtract the log, drain the delta, poll.

Retrograde and realtime are one mechanism: the seed's `catalog` says what
EXISTS in the (possibly `--select`-narrowed) window; the operational log says
what was already ATTEMPTED (success or failure alike); the driver runs the
delta. Retrograde drains it once; realtime drains, sleeps `poll_frequency`,
recomputes — forever, until stopped. `--retry-failed` re-queues failures and
`--force-rewrite` re-queues successes, each applied to the FIRST cycle only
(re-applying them every poll would re-run the same cells forever).

The operational log's location follows the RUN DEFINITION: by default
`.rainspout/<run.name>.oplog.jsonl` next to the config file, overridable via
`run.oplog:` (relative paths resolve against the config's directory). It is
never derived from the working directory — a resumed run must always find the
history it is supposed to subtract.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

from .config import RootConfig
from .errors import ConfigError
from .oplog import OpLog
from .runner import WorkItemResult, cell_id, prepare_stages, run_work_item
from .status import StatusReporter
from .validation import ValidatedRun

Notify = Callable[[str, Any], None]


def _silent(kind: str, payload: Any) -> None:
    return None


class StopFlag:
    """A latch the CLI wires to SIGINT/SIGTERM; the driver checks it between
    work items and while sleeping — the clean-stop contract."""

    def __init__(self) -> None:
        self._stopped = False

    def set(self, *_args: Any) -> None:
        self._stopped = True

    def __bool__(self) -> bool:
        return self._stopped


@dataclass(frozen=True)
class Plan:
    """One delta computation: what exists, minus what was attempted."""

    items: tuple[dict[str, Any], ...]  # coords to run, in iteration order
    existing: int  # enumerated cells the seed's catalog reports
    done: int      # attempted and succeeded (skipped unless --force-rewrite)
    failed: int    # attempted and failed (skipped unless --retry-failed)
    missing: int   # enumerated but not cataloged: no data, never a work item


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    succeeded: int
    failed: int
    cycles: int
    stopped: bool
    dry_run: bool
    results: tuple[WorkItemResult, ...]


def new_run_id(run_name: str) -> str:
    """Per-run identity: name + UTC stamp + short random suffix."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{run_name}-{stamp}-{uuid.uuid4().hex[:6]}"


def resolve_oplog_path(config_path: Path, config: RootConfig) -> Path:
    """Where this run definition's operational log lives (see module docstring)."""
    declared = config.run.oplog
    base = config_path.resolve().parent
    if declared is not None:
        path = Path(declared)
        return path if path.is_absolute() else base / path
    return base / ".rainspout" / f"{config.run.name}.oplog.jsonl"


def acquire_run_lock(oplog_path: Path, *, run_name: str, run_id: str) -> Callable[[], None]:
    """Take the exclusive lock for this run definition, or fail naming the holder.

    One run definition (config location + run.name) = one operational log =
    at most ONE active run: two concurrent runs would each drain the same
    delta, double-processing every cell and interleaving both logs. The lock
    file lives next to the oplog and is held for the run's duration; the OS
    releases it automatically if the process dies, so there are no stale
    locks. Returns the release callable.

    On platforms without ``fcntl`` (Windows) the lock is not enforced.
    """
    lock_path = oplog_path.parent / f"{run_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115 — held for the run's duration; close = unlock
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-POSIX platform: unenforced
        return handle.close
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        holder = handle.read().strip() or "holder unknown"
        handle.close()
        raise ConfigError(
            f"run '{run_name}' is already active ({holder}) — one active run per run "
            f"definition; wait for it, stop it, or use a different run.name "
            f"(lock: {lock_path})"
        ) from None
    handle.truncate(0)
    handle.seek(0)
    handle.write(f"pid {os.getpid()}, run_id {run_id}\n")
    handle.flush()
    return handle.close  # closing the descriptor releases the lock


def parse_selects(pairs: Iterable[str], validated: ValidatedRun) -> dict[str, set[str]]:
    """Parse --select dim=value pairs into {dimension: canonical values}."""
    selected: dict[str, set[str]] = {}
    for pair in pairs:
        dimension, separator, value = pair.partition("=")
        if not separator or not dimension or not value:
            raise ConfigError(f"--select expects dim=value, got {pair!r}")
        if dimension not in validated.dimension_values:
            raise ConfigError(
                f"--select names unknown dimension '{dimension}' "
                f"(declared: {', '.join(validated.dimension_values)})"
            )
        canonical = {str(v) for v in validated.dimension_values[dimension]}
        if value not in canonical:
            raise ConfigError(
                f"--select {dimension}={value}: value is not among the dimension's "
                f"values ({', '.join(sorted(canonical))})"
            )
        selected.setdefault(dimension, set()).add(value)
    return selected


def _selected_values(
    validated: ValidatedRun, select: Mapping[str, set[str]]
) -> dict[str, tuple[Any, ...]]:
    values: dict[str, tuple[Any, ...]] = {}
    for dimension in validated.order:
        candidates = validated.dimension_values[dimension]
        if dimension in select:
            candidates = tuple(v for v in candidates if str(v) in select[dimension])
        values[dimension] = candidates
    return values


def enumerate_items(
    validated: ValidatedRun, select: Mapping[str, set[str]]
) -> list[dict[str, Any]]:
    """Every point of the (narrowed) dimension cross-product, in iteration order."""
    values = _selected_values(validated, select)
    if any(not candidates for candidates in values.values()):
        return []
    dimensions = validated.order
    return [
        dict(zip(dimensions, combo, strict=True))
        for combo in product(*(values[dimension] for dimension in dimensions))
    ]


def _seed_spec(
    validated: ValidatedRun, select: Mapping[str, set[str]]
) -> dict[str, tuple[Any, ...]] | None:
    role_map = validated.config.seed[validated.seed_name].dimensions
    values = _selected_values(validated, select)
    if any(not values[dimension] for dimension in values):
        return None
    return {role: values[dimension] for role, dimension in role_map.items()}


def existing_cell_ids(
    validated: ValidatedRun, select: Mapping[str, set[str]]
) -> frozenset[str]:
    """What the seed's catalog reports in the window, as canonical cell ids."""
    spec = _seed_spec(validated, select)
    if spec is None:
        return frozenset()
    role_map = validated.config.seed[validated.seed_name].dimensions
    ids = set()
    for entry in validated.seed_handler.catalog(spec):
        coords = {dimension: entry.coords[role] for role, dimension in role_map.items()}
        ids.add(cell_id(coords, validated.order))
    return frozenset(ids)


def compute_plan(
    validated: ValidatedRun,
    oplog: OpLog,
    *,
    select: Mapping[str, set[str]],
    retry_failed: bool = False,
    force_rewrite: bool = False,
) -> Plan:
    """The delta: exists − attempted, plus the explicit re-queue flags."""
    existing = existing_cell_ids(validated, select)
    attempted = oplog.attempted_cells()
    failed_cells = oplog.failed_cells()

    to_run: list[dict[str, Any]] = []
    done = failed = missing = 0
    for coords in enumerate_items(validated, select):
        cid = cell_id(coords, validated.order)
        if cid not in existing:
            missing += 1
        elif cid not in attempted:
            to_run.append(coords)
        elif cid in failed_cells:
            failed += 1
            if retry_failed:
                to_run.append(coords)
        else:
            done += 1
            if force_rewrite:
                to_run.append(coords)
    return Plan(
        items=tuple(to_run), existing=len(existing), done=done, failed=failed, missing=missing
    )


def run_preflight(
    validated: ValidatedRun, select: Mapping[str, set[str]], notify: Notify
) -> None:
    """The startup structural probe: the first cataloged cell in the run window.

    An empty catalog skips the probe with a loud notice (legitimate in
    realtime, where a run may start before data arrives); a probe failure
    kills the run before any work item executes.
    """
    spec = _seed_spec(validated, select)
    first = next(iter(validated.seed_handler.catalog(spec)), None) if spec else None
    if first is None:
        notify(
            "preflight_empty",
            f"pre-flight: seed '{validated.seed_name}' catalog reports NOTHING in the "
            "run window — structural probe skipped (this is legitimate in realtime; "
            "in retrograde it usually means the config points at the wrong place)",
        )
        return
    validated.seed_handler.preflight(first.coords)
    notify("preflight_ok", (validated.seed_name, type(validated.seed_handler).name, first.coords))


def _sleep(seconds: float, stop: StopFlag) -> None:
    deadline = time.monotonic() + seconds
    while not stop and time.monotonic() < deadline:
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def drive(
    validated: ValidatedRun,
    *,
    oplog: OpLog,
    run_id: str,
    select: Mapping[str, set[str]] | None = None,
    retry_failed: bool = False,
    force_rewrite: bool = False,
    dry_run: bool = False,
    notify: Notify | None = None,
    stop: StopFlag | None = None,
    max_cycles: int | None = None,
    reporter: StatusReporter | None = None,
) -> RunSummary:
    """Execute (or plan) the run. Retrograde: one cycle. Realtime: cycles forever."""
    notify = notify or _silent
    stop = stop if stop is not None else StopFlag()
    select = select or {}

    run_preflight(validated, select, notify)

    if dry_run:
        plan = compute_plan(
            validated, oplog, select=select,
            retry_failed=retry_failed, force_rewrite=force_rewrite,
        )
        notify("plan", plan)
        return RunSummary(
            run_id=run_id, succeeded=0, failed=0, cycles=0,
            stopped=bool(stop), dry_run=True, results=(),
        )

    prepare_stages(validated)
    realtime = validated.config.run.mode == "realtime"
    succeeded = failed = cycles = 0
    results: list[WorkItemResult] = []

    while True:
        cycles += 1
        plan = compute_plan(
            validated, oplog, select=select,
            # the explicit re-queue flags apply to the first cycle only
            retry_failed=retry_failed and cycles == 1,
            force_rewrite=force_rewrite and cycles == 1,
        )
        notify("plan", plan)
        if reporter is not None:
            reporter.plan(
                cycle=cycles, to_run=len(plan.items), done=plan.done,
                failed=plan.failed, missing=plan.missing,
            )
        for coords in plan.items:
            if stop:
                break
            result = run_work_item(
                validated, coords, run_id=run_id, oplog=oplog, reporter=reporter
            )
            results.append(result)
            if result.status == "succeeded":
                succeeded += 1
            else:
                failed += 1
            if reporter is not None:
                reporter.item_finished(result.status)
            notify("work_item", result)
        if not realtime or stop:
            break
        if max_cycles is not None and cycles >= max_cycles:
            break
        notify("cycle_end", cycles)
        if reporter is not None:
            reporter.polling(cycles)
        _sleep(float(validated.config.run.poll_frequency or 0), stop)
        if stop:
            break

    if reporter is not None:
        reporter.finished(stopped=bool(stop))
    return RunSummary(
        run_id=run_id, succeeded=succeeded, failed=failed, cycles=cycles,
        stopped=bool(stop), dry_run=False, results=tuple(results),
    )
