"""Live run status: the file behind `spout status`.

A running `spout run` publishes its state to a small JSON **status file** so
that `spout status --config <run.yml>` in another terminal (or a script) can
see where the run is — without threads, sockets, or polling machinery inside
the runner. The mechanism is event-driven: every `set_status`/`set_progress`
call a stage makes is an execution point inside the running process, and the
base class forwards it here; the reporter throttles actual disk writes (at
most one per ``min_interval`` seconds) and always writes atomically
(temp file + rename), so readers never see a torn document.

The status file **follows the run definition**, like the operational log: it
lives next to the oplog as ``<run.name>.status.json``. Writing is strictly
best-effort — a status-file problem must never fail science — so write
errors are swallowed.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .config import RootConfig
from .errors import ConfigError


class CurrentStage(BaseModel):
    """What is executing right now."""

    model_config = ConfigDict(extra="forbid")

    cell_id: str
    stage: str
    status_line: str = ""
    progress: float | None = None


class PlanCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_run: int
    done: int
    failed: int
    missing: int


class StatusDocument(BaseModel):
    """One run's published state, as `spout status` reads it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_name: str
    run_id: str
    pid: int
    mode: str
    state: Literal["starting", "running", "polling", "finished", "stopped"]
    started_at: datetime
    updated_at: datetime
    cycle: int = 0
    plan: PlanCounts | None = None
    succeeded: int = 0  # this run's counters, not the all-time oplog totals
    failed: int = 0
    current: CurrentStage | None = None


def resolve_status_path(oplog_path: Path, config: RootConfig) -> Path:
    """The status file lives next to the operational log, named for the run."""
    return oplog_path.parent / f"{config.run.name}.status.json"


def read_status(path: Path) -> StatusDocument:
    """Parse a status file, or raise a ConfigError naming what's wrong."""
    try:
        raw = path.read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read status file {path}: {exc}") from exc
    try:
        return StatusDocument.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ConfigError(
            f"status file {path} is not a valid status document "
            f"(written by an incompatible rainspout version?): {exc}"
        ) from exc


class StatusReporter:
    """Publishes a run's state to the status file, throttled and atomic.

    Boundary events (plan computed, stage started, work item finished, run
    finished) always write; the high-frequency ``stage_tick`` — driven by the
    stage's own ``set_status``/``set_progress`` calls — writes at most once
    per ``min_interval`` seconds. All writes are best-effort.
    """

    def __init__(
        self,
        path: Path,
        *,
        run_name: str,
        run_id: str,
        mode: str,
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = path
        self._min_interval = min_interval
        self._clock = clock
        self._last_write: float | None = None
        now = datetime.now(UTC)
        self._doc = StatusDocument(
            run_name=run_name, run_id=run_id, pid=os.getpid(), mode=mode,
            state="starting", started_at=now, updated_at=now,
        )

    # -- events from the driver ------------------------------------------------

    def plan(self, *, cycle: int, to_run: int, done: int, failed: int, missing: int) -> None:
        self._doc.cycle = cycle
        self._doc.plan = PlanCounts(to_run=to_run, done=done, failed=failed, missing=missing)
        self._doc.state = "running"
        self._write(force=True)

    def item_finished(self, status: str) -> None:
        if status == "succeeded":
            self._doc.succeeded += 1
        else:
            self._doc.failed += 1
        self._doc.current = None
        self._write(force=True)

    def polling(self, cycle: int) -> None:
        self._doc.state = "polling"
        self._doc.current = None
        self._doc.cycle = cycle
        self._write(force=True)

    def finished(self, *, stopped: bool) -> None:
        self._doc.state = "stopped" if stopped else "finished"
        self._doc.current = None
        self._write(force=True)

    # -- events from the runner / the stage's own reporting calls ---------------

    def stage_started(self, cell_id: str, instance: str) -> None:
        self._doc.state = "running"
        self._doc.current = CurrentStage(cell_id=cell_id, stage=instance)
        self._write(force=True)

    def stage_tick(self, status_line: str, progress: float | None) -> None:
        if self._doc.current is None:  # a tick outside a work item: nothing to attach it to
            return
        self._doc.current.status_line = status_line
        self._doc.current.progress = progress
        self._write()

    # -- the write ---------------------------------------------------------------

    def _write(self, force: bool = False) -> None:
        now = self._clock()
        if (
            not force
            and self._last_write is not None
            and now - self._last_write < self._min_interval
        ):
            return
        self._doc.updated_at = datetime.now(UTC)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(self._doc.model_dump_json(indent=2))
            tmp.replace(self._path)
            self._last_write = now
        except OSError:
            # best-effort by contract: a status-file problem never fails science
            return


ReportHook = Callable[[str, "float | None"], None]


def make_stage_hook(reporter: StatusReporter) -> ReportHook:
    """The callable the runner attaches to a stage for the duration of run()."""

    def hook(status_line: str, progress: float | None) -> None:
        reporter.stage_tick(status_line, progress)

    return hook
